"""Gửi email mời họp sau khi tạo Zoom meeting."""

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
    VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
except ImportError:
    HAS_ICAL = False
    VN_TZ = None

SMTP_HOST = os.environ.get('IDS_SMTP_HOST', 'pro201.emailserver.vn')
SMTP_PORT = int(os.environ.get('IDS_SMTP_PORT', '587'))
SMTP_USER = os.environ['IDS_EMAIL']
SMTP_PASS = os.environ['IDS_EMAIL_PASSWORD']


def _create_invite_ics(title, start_time_str, duration_min, join_url, password, organizer_email):
    """Tạo file .ics calendar invite."""
    if not HAS_ICAL:
        return None
    try:
        cal = Calendar()
        cal.add('prodid', '-//IDS Meeting Bot//ids-international.vn//')
        cal.add('version', '2.0')
        cal.add('method', 'REQUEST')

        evt = Event()
        evt.add('summary', f'[IDS Họp] {title}')

        # Parse start time
        dt = datetime.fromisoformat(start_time_str)
        if dt.tzinfo is None:
            dt = VN_TZ.localize(dt)

        evt.add('dtstart', dt)
        evt.add('dtend', dt + timedelta(minutes=duration_min))
        evt.add('dtstamp', datetime.now(pytz.utc))
        evt.add('organizer', f'MAILTO:{organizer_email}')
        evt.add('description',
            f'Cuộc họp IDS\n\n'
            f'🔗 Join: {join_url}\n'
            f'🔑 Passcode: {password}\n\n'
            f'Tạo bởi IDS Meeting Bot'
        )
        evt.add('location', join_url)
        evt.add('status', 'CONFIRMED')
        cal.add_component(evt)
        return cal.to_ical()
    except Exception as e:
        print(f"  ⚠️ Không tạo được .ics: {e}")
        return None


def send_invite_to_participant(email, name, title, start_time_str, duration_min,
                                join_url, password, meeting_id):
    """Gửi email mời họp cho 1 người."""
    # Format thời gian
    try:
        dt = datetime.fromisoformat(start_time_str)
        if VN_TZ and dt.tzinfo is None:
            dt = VN_TZ.localize(dt)
        weekdays = ['Thứ Hai','Thứ Ba','Thứ Tư','Thứ Năm','Thứ Sáu','Thứ Bảy','Chủ Nhật']
        day_str = weekdays[dt.weekday()]
        time_str = f"{day_str}, {dt.strftime('%d/%m/%Y')} lúc {dt.strftime('%H:%M')}"
    except Exception:
        time_str = start_time_str

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#333">
  <div style="background:#1a73e8;color:white;padding:20px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:22px">📅 Thư Mời Họp</h1>
    <p style="margin:6px 0 0;opacity:.9">{title}</p>
  </div>
  <div style="padding:24px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px">
    <p>Xin chào <b>{name}</b>,</p>
    <p>Bạn được mời tham dự cuộc họp:</p>

    <table style="width:100%;border-collapse:collapse;margin:16px 0">
      <tr><td style="padding:8px 0;color:#666;width:120px">📌 Chủ đề</td>
          <td style="padding:8px 0"><b>{title}</b></td></tr>
      <tr><td style="padding:8px 0;color:#666">📅 Thời gian</td>
          <td style="padding:8px 0"><b>{time_str}</b></td></tr>
      <tr><td style="padding:8px 0;color:#666">⏱ Thời lượng</td>
          <td style="padding:8px 0">{duration_min} phút</td></tr>
      <tr><td style="padding:8px 0;color:#666">🆔 Meeting ID</td>
          <td style="padding:8px 0"><code>{meeting_id}</code></td></tr>
      <tr><td style="padding:8px 0;color:#666">🔑 Passcode</td>
          <td style="padding:8px 0"><code>{password}</code></td></tr>
    </table>

    <div style="text-align:center;margin:24px 0">
      <a href="{join_url}"
         style="background:#1a73e8;color:white;padding:14px 32px;border-radius:6px;
                text-decoration:none;font-size:16px;font-weight:bold;display:inline-block">
        🔗 Vào Họp Ngay
      </a>
    </div>

    <p style="color:#888;font-size:12px">
      📎 File .ics đính kèm — nhấn <em>Accept</em> để lưu vào lịch của bạn.<br>
      Email tự động từ IDS Meeting Bot · ids-international.vn
    </p>
  </div>
</body></html>"""

    msg             = MIMEMultipart('mixed')
    msg['From']     = f'"IDS Meeting Bot" <{SMTP_USER}>'
    msg['To']       = email
    msg['Subject']  = f'[Mời Họp] {title} · {time_str}'
    msg['Reply-To'] = SMTP_USER
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    # Đính kèm .ics
    ics_data = _create_invite_ics(title, start_time_str, duration_min,
                                   join_url, password, SMTP_USER)
    if ics_data:
        part = MIMEBase('text', 'calendar', method='REQUEST', name='invite.ics')
        part.set_payload(ics_data)
        part.add_header('Content-Disposition', 'attachment', filename='invite.ics')
        msg.attach(part)

    # Gửi
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"  ✓ Invite → {email}")
    except Exception:
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx, timeout=20) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"  ✓ Invite (SSL) → {email}")


def send_all_invites(meeting_title, start_time_str, duration_min,
                     join_url, password, meeting_id, participants):
    """Gửi invite cho tất cả participants."""
    print(f"Gửi invite cho {len(participants)} người...")
    for p in participants:
        try:
            send_invite_to_participant(
                email         = p['email'],
                name          = p.get('name', p['email'].split('@')[0]),
                title         = meeting_title,
                start_time_str= start_time_str,
                duration_min  = duration_min,
                join_url      = join_url,
                password      = password,
                meeting_id    = meeting_id
            )
        except Exception as e:
            print(f"  ❌ Lỗi → {p['email']}: {e}")
