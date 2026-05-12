"""
Phase 2: CEO đã duyệt → đọc Google Doc → gửi email team + log Sheets + notify.
Triggered bởi GH Actions khi nhận /send_all từ Telegram.
"""

import os, sys, traceback

from sheets_manager  import get_draft, log_meeting, log_action_items, mark_draft_sent
from gdoc_manager    import read_doc_as_text
from analyze         import reanalyze_from_doc
from email_sender    import send_all_minutes
from telegram_notify import notify_meeting_done, notify_owner


def run():
    meeting_id = os.environ.get('MEETING_ID', '').strip()
    if not meeting_id:
        print("❌ Thiếu MEETING_ID")
        return 1

    print(f"== Phase 2: Finalize biên bản meeting {meeting_id} ==")

    # 1. Lấy draft info từ Sheets
    draft = get_draft(meeting_id)
    if not draft:
        notify_owner(f"⚠️ Không tìm thấy draft cho meeting {meeting_id}")
        return 1

    topic        = draft['topic']
    start_time   = draft['start_time']
    host_email   = draft['host_email']
    emails       = draft['emails']
    participants = draft['participants']
    doc_id       = draft['doc_id']
    doc_url      = draft['doc_url']
    meeting_date = start_time[:10] if start_time else 'N/A'

    print(f"  Meeting: {topic}")
    print(f"  Doc: {doc_url}")
    print(f"  Participants: {[p['email'] for p in participants]}")

    # 2. Đọc Google Doc (đã được CEO chỉnh sửa)
    print("\n[1/4] Đọc Google Doc...")
    doc_text = read_doc_as_text(doc_id)
    print(f"  ✓ Doc text: {len(doc_text)} ký tự")

    # 3. Re-analyze từ doc text
    print("\n[2/4] Re-analyze với Claude...")
    analysis = reanalyze_from_doc(doc_text, topic, participants, host_email)
    if not analysis:
        notify_owner(f"⚠️ Re-analyze thất bại cho meeting {meeting_id}")
        return 1
    action_items = analysis.get('action_items', [])
    keywords     = analysis.get('keywords', [])
    print(f"  ✓ {len(action_items)} action items, {len(keywords)} keywords")

    # 4. Gửi email cho cả team
    print("\n[3/4] Gửi email biên bản cho team...")
    if participants:
        send_all_minutes(topic, meeting_date, participants, analysis)
    else:
        print("  ⚠️ Không có participants")

    # 5. Log vào Sheets + mark draft sent
    print("\n[4/4] Ghi Sheets...")
    log_meeting(meeting_id, topic, start_time, participants, keywords)
    log_action_items(meeting_id, action_items)
    mark_draft_sent(meeting_id)

    # 6. Notify hoàn tất
    notify_meeting_done(topic, meeting_date, len(action_items), participants)

    print("\n== PHASE 2 HOÀN THÀNH ==")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except Exception:
        err = traceback.format_exc()
        print(f"❌ Finalize lỗi:\n{err}", file=sys.stderr)
        try:
            notify_owner(f"❌ Finalize pipeline lỗi:\n{err[-800:]}")
        except Exception:
            pass
        sys.exit(1)
