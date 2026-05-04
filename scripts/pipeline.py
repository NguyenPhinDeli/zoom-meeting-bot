"""
Main pipeline: chạy sau khi Zoom recording.completed.
Được trigger bởi GitHub Actions (repository_dispatch từ CF Worker).

Input (env vars set bởi GH Actions):
  MEETING_ID, MEETING_UUID, TOPIC, START_TIME, DURATION, EMAILS_JSON, HOST_EMAIL
"""

import os
import sys
import json
import traceback

from zoom_api       import get_recordings, download_transcript, parse_vtt, get_access_token
from analyze        import analyze_meeting
from email_sender   import send_all_minutes
from sheets_manager import get_participants_for_meeting, log_meeting, log_action_items
from telegram_notify import notify_meeting_done, notify_owner


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

    # ── 2. Lấy recording + transcript từ Zoom ──────────────────────────────
    print("\n[1/5] Tải transcript từ Zoom...")
    recordings = get_recordings(meeting_uuid or meeting_id)

    files = recordings.get('recording_files', [])
    transcript_file = next(
        (f for f in files if f.get('file_type') == 'TRANSCRIPT'), None
    )

    if not transcript_file:
        notify_owner(f"⚠️ Cuộc họp <b>{topic}</b> không có transcript.\nKiểm tra Zoom AI Companion đã bật chưa.")
        # Vẫn tiếp tục với transcript rỗng
        transcript_text = "(Không có transcript tự động)"
    else:
        vtt_content     = download_transcript(transcript_file['download_url'])
        transcript_text = parse_vtt(vtt_content)
        print(f"  ✓ Transcript: {len(transcript_text)} ký tự")

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
