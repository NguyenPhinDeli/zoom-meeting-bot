"""Gửi biên bản cuộc họp qua SMTP Mắt Bão + đính kèm .ics calendar invite."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta

try:
    from icalendar import Calendar, Event
    import pytz
    HAS_ICAL = True
except ImportError:
    HAS_ICAL = False

SMTP_HOST = os.environ.get('IDS_SMTP_HOST', 'pro201.emailserver.vn')
SMTP_PORT = int(os.environ.get('IDS_SMTP_PORT', '587'))
SMTP_USER = os.environ['IDS_EMAIL']
SMTP_PASS = os.environ['IDS_EMAIL_PASSWORD']
VN_TZ     = None

if HAS_ICAL:
    import pytz
    VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')


def _create_ics(task: str, assignee_email: str, deadline_str: str) -> bytes | None:
    """Tạo file .ics để đính kèm vào email → recipient click Accept = lưu vào calendar."""
    if not HAS_ICAL or not VN_TZ:
        return None
    try:
        cal = Calendar()
        cal.add('prodid', '-//IDS Meeting Bot//ids-international.vn//')
        cal.add('version', '2.0')
        cal.add('method', 'REQUEST')

        evt = Event()
        evt.add('summary', f'[IDS] {task}')
        deadline = datetime.strptime(deadline_str, '%Y-%m-%d')
        deadline_vn = VN_TZ.localize(deadline.replace(hour=9, minute=0))
        evt.add('dtstart', deadline_vn.date())
        evt.add('dtend', (deadline + timedelta(days=1)).date())
        evt.add('dtstamp', datetime.now(pytz.utc))
        evt.add('organizer', f'MAILTO:{SMTP_USER}')
        evt.add('attendee', f'MAILTO:{assignee_email}')
        evt.add('description', f'Action item được giao trong cuộc họp IDS.\nTask: {task}')
        evt.add('status', 'CONFIRMED')

        cal.add_component(evt)
        return cal.to_ical()
    except Exception as e:
        print(f"  ⚠️ Không tạo được .ics: {e}")
        return None


def _build_html(meeting_title: str, meeting_date: str, recipient_name: str,
                personal_summary: str, action_items: list[dict],
                recipient_email: str, key_decisions: list[str],
                is_ceo: bool, ceo_summary: str) -> str:

    # Lọc action items của người này
    my_items  = [i for i in action_items if i.get('assignee_email') == recipient_email]
    all_items = action_items  # CEO thấy tất cả

    def render_item(item):
        if item['type'] == 'immediate':
            badge = '🔴 <span style="color:#c0392b">Làm ngay</span>'
        else:
            badge = f'📅 Deadline: <strong>{item.get("deadline","?")}</strong>'
        priority_map = {'high': '🔥', 'medium': '⚡', 'low': '💬'}
        icon = priority_map.get(item.get('priority','medium'), '⚡')
        return f"<li>{icon} {item['task']} — {badge}</li>"

    my_items_html = ''.join(render_item(i) for i in my_items) or '<li>Không có việc được giao</li>'

    ceo_section = ''
    if is_ceo:
        all_items_html = ''.join(render_item(i) for i in all_items) or '<li>Không có</li>'
        decisions_html = ''.join(f'<li>{d}</li>' for d in key_decisions) or '<li>Không có</li>'
        ceo_section = f"""
<div style="background:#f8f9fa;border-left:4px solid #2980b9;padding:12px 16px;margin:16px 0;">
  <h2 style="margin-top:0;color:#2980b9">📊 Tổng quan (CEO)</h2>
  <p>{ceo_summary}</p>
  <h3>🗂 Tất cả action items</h3>
  <ul>{all_items_html}</ul>
  <h3>✅ Quyết định đã đưa ra</h3>
  <ul>{decisions_html}</ul>
</div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#333">
  <div style="background:#1a73e8;color:white;padding:20px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px">📋 Biên Bản Cuộc Họp</h1>
    <p style="margin:4px 0 0;opacity:.85">{meeting_title}</p>
  </div>
  <div style="padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px">
    <p><strong>Ngày:</strong> {meeting_date}<br>
       <strong>Gửi đến:</strong> {recipient_name}</p>
    <hr>
    {ceo_section}
    <h2>📝 Tóm tắt của bạn</h2>
    <p>{personal_summary}</p>
    <h2>✅ Việc cần làm của bạn</h2>
    <ul>{my_items_html}</ul>
    <hr>
    <p style="color:#888;font-size:12px">
      Email tự động từ IDS Meeting Bot · nguyenpd@ids-international.vn<br>
      Các file .ics đính kèm → nhấn <em>Accept</em> để lưu vào lịch của bạn.
    </p>
  </div>
</body></html>"""


def send_to_participant(meeting_title: str, meeting_date: str,
                        participant: dict, analysis: dict, is_ceo: bool):
    """Gửi biên bản cá nhân hóa cho 1 người."""
    email   = participant['email']
    name    = participant.get('name', email)
    role    = participant.get('role', '')

    personal_summary = analysis.get('summaries_by_role', {}).get(email) \
                    or analysis.get('summary_ceo', '')
    action_items  = analysis.get('action_items', [])
    key_decisions = analysis.get('key_decisions', [])
    ceo_summary   = analysis.get('summary_ceo', '')

    msg              = MIMEMultipart('mixed')
    msg['From']      = f'"IDS Meeting Bot" <{SMTP_USER}>'
    msg['To']        = email
    msg['Subject']   = f'[Biên Bản] {meeting_title} · {meeting_date}'
    msg['Reply-To']  = SMTP_USER

    html = _build_html(meeting_title, meeting_date, name, personal_summary,
                       action_items, email, key_decisions, is_ceo, ceo_summary)
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    # Đính kèm .ics cho từng deadline task được giao cho người này
    my_deadline_items = [
        i for i in action_items
        if i.get('assignee_email') == email
        and i.get('type') == 'deadline'
        and i.get('deadline')
    ]
    for item in my_deadline_items:
        ics_data = _create_ics(item['task'], email, item['deadline'])
        if ics_data:
            safe_name = item['task'][:25].replace(' ', '_').replace('/', '-')
            part = MIMEBase('text', 'calendar', method='REQUEST', name=f'{safe_name}.ics')
            part.set_payload(ics_data)
            part.add_header('Content-Disposition', 'attachment', filename=f'{safe_name}.ics')
            msg.attach(part)

    # Gửi qua SMTP
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"  ✓ Email gửi thành công → {email}")
    except Exception:
        # Fallback: thử SSL port 465
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx, timeout=20) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"  ✓ Email gửi thành công (SSL) → {email}")


def send_all_minutes(meeting_title: str, meeting_date: str,
                     participants: list[dict], analysis: dict):
    """Gửi biên bản cho tất cả participants."""
    ceo_roles = {'ceo', 'giám đốc', 'director', 'giam doc'}
    for p in participants:
        is_ceo = p.get('role', '').lower().strip() in ceo_roles
        try:
            send_to_participant(meeting_title, meeting_date, p, analysis, is_ceo)
        except Exception as e:
            print(f"  ❌ Gửi email thất bại → {p['email']}: {e}")
