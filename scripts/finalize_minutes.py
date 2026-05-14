"""
Phase 2: CEO đã duyệt → gửi link Google Doc cho team + log Sheets + notify.
Triggered bởi GH Actions khi nhận /send_all từ Telegram.
"""

import os, sys, traceback, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sheets_manager  import get_draft, log_meeting, log_action_items, mark_draft_sent
from gdoc_manager    import read_doc_as_text
from telegram_notify import notify_meeting_done, notify_owner

SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USER = os.environ.get('GMAIL_ADDRESS', '')
SMTP_PASS = os.environ.get('GMAIL_APP_PASSWORD', '')


def send_doc_link(topic: str, meeting_date: str, doc_url: str, doc_content: str,
                  participant: dict, action_items: list):
    """Gửi email: nội dung Google Doc + link gốc."""
    email = participant['email']
    name  = participant.get('name', email)

    # Task của người này
    my_tasks = [
        item for item in action_items
        if (item.get('pic_email') or item.get('assignee_email', '')).lower() == email.lower()
    ]
    my_tasks_html = ''
    if my_tasks:
        def _task_row(item):
            dl = '🔴 Làm ngay' if item.get('type') == 'immediate' else f'📅 {item.get("deadline","?")}'
            task = item.get('viec') or item.get('task', '')
            return f'<li>{dl} — {task}</li>'
        rows = ''.join(_task_row(item) for item in my_tasks)
        my_tasks_html = f"""
<div style="background:#fff8e1;border-left:4px solid #f39c12;padding:12px 16px;margin:16px 0;border-radius:4px">
  <strong>⚠️ Việc được giao cho bạn:</strong>
  <ul style="margin:6px 0 0;padding-left:18px">{rows}</ul>
</div>"""

    # Nội dung Google Doc → thay newline bằng <br>
    doc_html = doc_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    doc_html = '<br>'.join(doc_html.splitlines())

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#333;font-size:14px">
  <div style="background:#1a73e8;color:white;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px">📋 Biên Bản Cuộc Họp</h1>
    <p style="margin:4px 0 0;opacity:.85">{topic} · {meeting_date}</p>
  </div>
  <div style="padding:20px 24px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px">
    <p>Kính gửi <strong>{name}</strong>,</p>
    {my_tasks_html}
    <div style="background:#f9f9f9;border:1px solid #e0e0e0;border-radius:6px;padding:16px 20px;margin:16px 0;line-height:1.7">
      {doc_html}
    </div>
    <div style="text-align:center;margin:20px 0">
      <a href="{doc_url}"
         style="background:#1a73e8;color:white;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px">
        📄 Mở Google Doc gốc
      </a>
    </div>
    <hr style="border:none;border-top:1px solid #eee">
    <p style="color:#aaa;font-size:12px;margin-bottom:0">
      Email tự động từ IDS Meeting Bot · nguyenpd@ids-international.vn
    </p>
  </div>
</body></html>"""

    msg = MIMEMultipart('alternative')
    msg['From']    = f'"IDS Meeting Bot" <{SMTP_USER}>'
    msg['To']      = email
    msg['Subject'] = f'[Biên Bản] {topic} · {meeting_date}'
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"  ✓ Gửi → {email}")
    except Exception as e:
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx, timeout=20) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"  ✓ Gửi (SSL) → {email}")


def run():
    meeting_id = os.environ.get('MEETING_ID', '').strip()
    if not meeting_id:
        print("❌ Thiếu MEETING_ID")
        return 1

    print(f"== Phase 2: Gửi biên bản meeting {meeting_id} ==")

    draft = get_draft(meeting_id)
    if not draft:
        notify_owner(f"⚠️ Không tìm thấy draft cho meeting {meeting_id}")
        return 1

    topic        = draft['topic']
    start_time   = draft['start_time']
    participants = draft['participants']
    doc_url      = draft['doc_url']
    meeting_date = start_time[:10] if start_time else 'N/A'
    analysis     = draft.get('analysis') or {}
    action_items = analysis.get('action_items', [])
    keywords     = analysis.get('keywords', [])

    print(f"  Meeting : {topic}")
    print(f"  Doc     : {doc_url}")
    print(f"  Gửi cho : {[p['email'] for p in participants]}")

    # Đọc nội dung Google Doc
    print("\n[1/3] Đọc nội dung Google Doc...")
    doc_id      = draft['doc_id']
    doc_content = read_doc_as_text(doc_id)
    print(f"  ✓ {len(doc_content)} ký tự")

    # Gửi email
    print("\n[2/3] Gửi email...")
    for p in participants:
        try:
            send_doc_link(topic, meeting_date, doc_url, doc_content, p, action_items)
        except Exception as e:
            print(f"  ❌ Lỗi → {p['email']}: {e}")

    # Log Sheets
    print("\n[3/3] Ghi Sheets + Notify...")
    log_meeting(meeting_id, topic, start_time, participants, keywords)
    log_action_items(meeting_id, action_items)
    mark_draft_sent(meeting_id)
    try:
        notify_meeting_done(topic, meeting_date, len(action_items), participants)
    except Exception:
        pass

    print("\n== PHASE 2 HOÀN THÀNH ==")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except Exception:
        err = traceback.format_exc()
        print(f"❌ Finalize lỗi:\n{err}", file=sys.stderr)
        try:
            notify_owner(f"❌ Finalize lỗi:\n{err[-800:]}")
        except Exception:
            pass
        sys.exit(1)
