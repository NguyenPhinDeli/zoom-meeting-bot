"""
Main pipeline: chạy sau khi Zoom recording.completed.
Được trigger bởi GitHub Actions (repository_dispatch từ CF Worker).

Input (env vars set bởi GH Actions):
  MEETING_ID, MEETING_UUID, TOPIC, START_TIME, DURATION, EMAILS_JSON, HOST_EMAIL
"""

import os
import sys
import json
import tempfile
import traceback

from groq           import Groq
from zoom_api       import get_recordings, download_audio_file, compress_audio_if_needed
from analyze        import analyze_meeting
from email_sender   import send_all_minutes
from sheets_manager import get_participants_for_meeting, log_meeting, log_action_items
from telegram_notify import notify_meeting_done, notify_owner


def transcribe_with_whisper(audio_path: str) -> str:
    """Dùng Groq Whisper để transcribe audio tiếng Việt."""
    client = Groq(api_key=os.environ['GROQ_API_KEY'])
    audio_path = compress_audio_if_needed(audio_path)
    with open(audio_path, 'rb') as f:
        result = client.audio.transcriptions.create(
            model='whisper-large-v3',
            file=f,
            language='vi',
            response_format='text'
        )
    return result if isinstance(result, str) else result.text


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
    except Exception:
        emails = []

    # Thêm host nếu chưa có
    if host_email and host_email not in emails:
        emails.insert(0, host_email)

    print(f"  Meeting: {topic} ({meeting_id})")
    print(f"  Participants: {emails}")

    # ── 2. Lấy audio từ Zoom → Whisper transcript ─────────────────────────
    print("\n[1/5] Tải audio từ Zoom + transcribe bằng Groq Whisper...")
    recordings = get_recordings(meeting_uuid or meeting_id)

    files = recordings.get('recording_files', [])
    # Ưu tiên M4A (audio only, nhỏ hơn), fallback sang MP4
    audio_file = (
        next((f for f in files if f.get('file_type') == 'M4A'), None) or
        next((f for f in files if f.get('file_type') == 'MP4'), None)
    )

    if not audio_file:
        notify_owner(f"⚠️ Cuộc họp <b>{topic}</b> không có file audio.\nKiểm tra Zoom cloud recording đã bật chưa.")
        transcript_text = "(Không có audio recording)"
    else:
        ext = audio_file['file_type'].lower()
        with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            download_audio_file(audio_file['download_url'], tmp_path)
            transcript_text = transcribe_with_whisper(tmp_path)
            print(f"  ✓ Transcript (Whisper): {len(transcript_text)} ký tự")
        finally:
            # Dọn file tạm
            for p in [tmp_path, tmp_path.rsplit('.', 1)[0] + '_compressed.mp3']:
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass

    # ── 3. Lấy thông tin participants từ Sheets ────────────────────────────
    print("\n[2/5] Lấy thông tin team từ Google Sheets...")
    participants = get_participants_for_meeting(emails)
    print(f"  ✓ {len(participants)} người tham gia")

    # ── 4. Phân tích transcript bằng Groq ─────────────────────────────────
    print("\n[3/5] Phân tích transcript bằng Groq AI...")
    analysis = analyze_meeting(transcript_text, topic, participants)
    action_items = analysis.get('action_items', [])
    keywords     = analysis.get('keywords', [])
    print(f"  ✓ {len(action_items)} action item(s), {len(keywords)} keywords")

    # ── 5. Gửi email biên bản cho từng người ──────────────────────────────
    print("\n[4/5] Gửi email biên bản...")
    meeting_date = start_time[:10] if start_time else 'N/A'
    send_all_minutes(topic, meeting_date, participants, analysis)

    # ── 6. Ghi vào Google Sheets ───────────────────────────────────────────
    print("\n[5/5] Ghi vào Google Sheets...")
    log_meeting(meeting_id, topic, start_time, participants, keywords)
    log_action_items(meeting_id, action_items)

    # ── 7. Thông báo hoàn tất cho anh Nguyên ──────────────────────────────
    notify_meeting_done(topic, meeting_date, len(action_items), participants)

    print("\n== PIPELINE HOÀN THÀNH ==")
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
