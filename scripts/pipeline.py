"""
Main pipeline: chạy sau khi Zoom recording.completed.
Được trigger bởi GitHub Actions (repository_dispatch từ CF Worker).

Input (env vars set bởi GH Actions):
  MEETING_ID, MEETING_UUID, TOPIC, START_TIME, DURATION, EMAILS_JSON, HOST_EMAIL
"""

import os
import sys
import json
import time
import tempfile
import traceback

from groq           import Groq
from zoom_api       import get_recordings, download_audio_file, compress_audio_if_needed
from analyze        import analyze_meeting
from email_sender   import send_all_minutes
from sheets_manager import get_participants_for_meeting, get_team, log_meeting, log_action_items, save_draft
from telegram_notify import notify_meeting_done, notify_owner, notify_draft_ready
from gdoc_manager   import create_draft_doc


WHISPER_PROMPT = (
    "Cuộc họp nội bộ công ty IDS (IDS International), TP. Hồ Chí Minh. "
    "Sản phẩm: Castrol, L'Oréal, LPD, LDB, CPD, L'Oréal Professionnel, Garnier, Maybelline. "
    "Đối thủ: Total, Motul, Mobil. "
    "Tên lãnh đạo: Nguyên, Bình, Giang, Lanh, Vy, Trí, Thức, Đạt, Khá, Vĩ. "
    "Thuật ngữ: doanh số, báo cáo, KPI, deadline, action item, "
    "kế hoạch, phân phối, đại lý, garage, workshop, cashier, sell-in, sell-out."
)


def transcribe_with_whisper(audio_path: str) -> str:
    """Dùng Groq Whisper để transcribe audio tiếng Việt + tiếng Anh chuyên ngành."""
    import groq as groq_lib
    client     = Groq(api_key=os.environ['GROQ_API_KEY'])
    audio_path = compress_audio_if_needed(audio_path)
    for attempt in range(5):
        try:
            with open(audio_path, 'rb') as f:
                result = client.audio.transcriptions.create(
                    model='whisper-large-v3',
                    file=f,
                    language='vi',
                    prompt=WHISPER_PROMPT,
                    response_format='text'
                )
            return result if isinstance(result, str) else result.text
        except groq_lib.RateLimitError as e:
            wait = 90 if attempt < 3 else 180
            print(f"  ⏳ Groq rate limit, chờ {wait}s (lần {attempt+1}/5)...")
            time.sleep(wait)
    raise Exception("Groq Whisper rate limit vượt quá 5 lần retry")


def run():
    print("== IDS Meeting Pipeline bắt đầu ==")

    # ── 1. Đọc thông tin meeting từ env ────────────────────────────────────
    meeting_id   = os.environ.get('MEETING_ID', '')
    meeting_uuid = os.environ.get('MEETING_UUID', '')
    topic        = os.environ.get('TOPIC', 'Cuộc họp IDS')
    start_time   = os.environ.get('START_TIME', '')
    emails_raw   = os.environ.get('EMAILS_JSON', '[]')
    host_email   = os.environ.get('HOST_EMAIL', '')

    try:
        emails = json.loads(emails_raw)
        if not isinstance(emails, list):
            emails = []
    except Exception:
        emails = []

    # Thêm host nếu chưa có
    if host_email and host_email not in emails:
        emails.insert(0, host_email)

    print(f"  Meeting: {topic} ({meeting_id})")
    print(f"  Participants: {emails}")

    # ── 2. Lấy audio → Whisper transcript ────────────────────────────────
    print("\n[1/5] Tải audio từ Zoom + transcribe bằng Groq Whisper...")

    # Mock transcript cho testing
    mock_transcript = os.environ.get('MOCK_TRANSCRIPT', '').strip()
    if mock_transcript:
        print("  ℹ️ Dùng MOCK_TRANSCRIPT để test")
        transcript_text = mock_transcript
        # Skip audio download
        print(f"  ✓ Transcript (mock): {len(transcript_text)} ký tự")

    if mock_transcript:
        pass  # đã set transcript_text ở trên, skip audio
    else:
      # Ưu tiên URL từ webhook payload (nhanh, không cần API call)
      audio_url  = os.environ.get('AUDIO_URL', '').strip()
      audio_type = os.environ.get('AUDIO_TYPE', 'm4a').strip() or 'm4a'

    # Fallback: gọi Zoom API nếu không có URL từ webhook
    if not mock_transcript and not audio_url:
        print("  ℹ️ Không có audio_url từ webhook, thử lấy qua API...")
        recordings = get_recordings(meeting_uuid, meeting_id=meeting_id)
        files = recordings.get('recording_files', [])
        audio_rec = (
            next((f for f in files if f.get('file_type') == 'M4A'), None) or
            next((f for f in files if f.get('file_type') == 'MP4'), None)
        )
        if audio_rec:
            audio_url  = audio_rec['download_url']
            audio_type = audio_rec['file_type'].lower()

    if not mock_transcript and not audio_url:
        notify_owner(f"⚠️ Cuộc họp <b>{topic}</b>: không lấy được recording.\nKiểm tra Zoom cloud recording đã bật chưa.")
        transcript_text = "(Không có audio recording)"
    elif not mock_transcript:
        with tempfile.NamedTemporaryFile(suffix=f'.{audio_type}', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            download_audio_file(audio_url, tmp_path)
            transcript_text = transcribe_with_whisper(tmp_path)
            print(f"  ✓ Transcript (Whisper): {len(transcript_text)} ký tự")
        finally:
            for p in [tmp_path, tmp_path.rsplit('.', 1)[0] + '_compressed.mp3']:
                try: os.unlink(p)
                except FileNotFoundError: pass

    # ── 3. Lấy thông tin participants + full team từ Sheets ───────────────
    print("\n[2/5] Lấy thông tin team từ Google Sheets...")
    participants = get_participants_for_meeting(emails)
    full_team    = get_team()  # toàn bộ team để Claude map tên → email chính xác
    print(f"  ✓ {len(participants)} người tham gia, {len(full_team)} thành viên team")

    # ── 4. Phân tích transcript bằng Groq ─────────────────────────────────
    print("\n[3/5] Phân tích transcript bằng Groq AI...")
    duration = int(os.environ.get('DURATION', '0') or '0')
    analysis = analyze_meeting(transcript_text, topic, participants,
                               start_time=start_time, duration=duration,
                               host_email=host_email, full_team=full_team)
    action_items = analysis.get('action_items', [])
    keywords     = analysis.get('keywords', [])
    print(f"  ✓ {len(action_items)} action item(s), {len(keywords)} keywords")

    meeting_date = start_time[:10] if start_time else 'N/A'

    # ── 5. Tạo Google Doc draft để CEO duyệt ──────────────────────────────
    print("\n[4/5] Tạo Google Doc draft...")
    doc_id, doc_url = create_draft_doc(topic, analysis, participants)

    # ── 6. Lưu draft vào Sheets + notify CEO qua Telegram ─────────────────
    print("\n[5/5] Lưu draft + notify Telegram...")
    save_draft(meeting_id, topic, start_time, host_email,
               emails, participants, doc_id, doc_url, analysis=analysis)
    notify_draft_ready(topic, meeting_date, meeting_id, doc_url, len(action_items))

    print("\n== PHASE 1 HOÀN THÀNH — Chờ CEO duyệt ==")
    print(f"  Google Doc: {doc_url}")
    print(f"  Gõ /send_all {meeting_id} trên Telegram để gửi team")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except Exception:
        err = traceback.format_exc()
        print(f"❌ Pipeline lỗi:\n{err}", file=sys.stderr)
        try:
            notify_owner(f"❌ Meeting pipeline lỗi:\n{err[-1000:]}")
        except Exception:
            pass
        sys.exit(1)
