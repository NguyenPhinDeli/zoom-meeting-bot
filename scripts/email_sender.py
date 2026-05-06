"""Gửi biên bản cuộc họp 6-section chuẩn qua SMTP Mắt Bão + đính kèm .ics."""

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


def _priority_label(priority: str) -> str:
    return {'high': '🔥 Cao', 'medium': '⚡ TB', 'low': '💬 Thấp'}.get(priority, '⚡ TB')


def _deadline_label(item: dict) -> str:
    if item.get('type') == 'immediate' or not item.get('deadline'):
        return '<span style="color:#c0392b;font-weight:bold">Làm ngay</span>'
    return item['deadline']


def _build_action_table(items: list[dict], highlight_email: str = '') -> str:
    """Render bảng action items dạng table HTML."""
    if not items:
        return '<p style="color:#888;font-style:italic">Không có action item.</p>'

    rows = ''
    for i, item in enumerate(items, 1):
        pic_name     = item.get('pic_name') or item.get('assignee_name', '')
        pic_email    = item.get('pic_email') or item.get('assignee_email', '')
        pic_display  = f"{pic_name}<br><small style='color:#888'>{pic_email}</small>" if pic_name else pic_email
        viec         = item.get('viec') or item.get('task', '')
        deadline_td  = _deadline_label(item)
        priority_td  = _priority_label(item.get('priority', 'medium'))

        # Highlight dòng của người nhận
        is_mine = pic_email == highlight_email
        row_bg  = '#fff8e1' if is_mine else ('white' if i % 2 else '#f9f9f9')
        marker  = ' ◀ Bạn' if is_mine else ''

        rows += f"""<tr style="background:{row_bg}">
          <td style="padding:8px 10px;text-align:center;color:#666">{i}</td>
          <td style="padding:8px 10px">{viec}{f'<strong style="color:#e67e22">{marker}</strong>' if is_mine else ''}</td>
          <td style="padding:8px 10px">{pic_display}</td>
          <td style="padding:8px 10px;text-align:center">{deadline_td}</td>
          <td style="padding:8px 10px;text-align:center">{priority_td}</td>
        </tr>"""

    return f"""<table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#1a73e8;color:white">
          <th style="padding:10px;width:40px">#</th>
          <th style="padding:10px;text-align:left">Việc cần làm</th>
          <th style="padding:10px;text-align:left;width:160px">PIC</th>
          <th style="padding:10px;width:120px">Deadline</th>
          <th style="padding:10px;width:80px">Ưu tiên</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def _build_html(meeting_title: str, meeting_date: str, recipient_name: str,
                personal_summary: str, analysis: dict,
                recipient_email: str, is_ceo: bool) -> str:

    tti      = analysis.get('thong_tin_chung', {})
    items    = analysis.get('action_items', [])
    quyet    = analysis.get('quyet_dinh', {})
    thao_luan = analysis.get('noi_dung_thao_luan', [])
    muc_tieu = analysis.get('muc_tieu', '')
    hop_sau  = analysis.get('hop_tiep_theo', 'Chưa xác định')
    ceo_sum  = analysis.get('summary_ceo', '')

    # ── 1. Thông tin chung ─────────────────────────────────────────────────
    chu_tri   = tti.get('chu_tri', 'Không rõ')
    tham_du   = ', '.join(tti.get('tham_du', [])) or 'Không rõ'
    vang_mat  = ', '.join(tti.get('vang_mat', [])) or 'Không có'
    thoi_luong = tti.get('thoi_luong', '')

    sec1 = f"""
<div class="section">
  <h2 class="sec-title">1. Thông tin chung</h2>
  <table class="info-table">
    <tr><td class="label">Tên cuộc họp</td><td><strong>{meeting_title}</strong></td></tr>
    <tr><td class="label">Thời gian</td><td>{meeting_date}{f' · {thoi_luong}' if thoi_luong else ''}</td></tr>
    <tr><td class="label">Người chủ trì</td><td>{chu_tri}</td></tr>
    <tr><td class="label">Tham dự</td><td>{tham_du}</td></tr>
    <tr><td class="label">Vắng mặt</td><td>{vang_mat}</td></tr>
  </table>
</div>"""

    # ── 2. Mục tiêu ────────────────────────────────────────────────────────
    sec2 = f"""
<div class="section">
  <h2 class="sec-title">2. Mục tiêu cuộc họp</h2>
  <p>{muc_tieu or '(Không rõ)'}</p>
</div>"""

    # ── 3. Nội dung thảo luận ──────────────────────────────────────────────
    if thao_luan:
        items_html = ''.join(
            f'<div style="margin-bottom:10px"><strong>🔹 {t["van_de"]}</strong><br>{t["noi_dung"]}</div>'
            for t in thao_luan
        )
    else:
        items_html = '<p style="color:#888;font-style:italic">Không có chi tiết.</p>'

    sec3 = f"""
<div class="section">
  <h2 class="sec-title">3. Nội dung thảo luận</h2>
  {items_html}
</div>"""

    # ── 4. Quyết định & Kết luận ───────────────────────────────────────────
    done_list = ''.join(f'<li>✅ {d}</li>' for d in quyet.get('da_thong_nhat', [])) \
                or '<li style="color:#888">Không có</li>'
    open_list = ''.join(f'<li>🔄 {d}</li>' for d in quyet.get('chua_giai_quyet', [])) \
                or '<li style="color:#888">Không có</li>'

    sec4 = f"""
<div class="section">
  <h2 class="sec-title">4. Quyết định & Kết luận</h2>
  <p><strong>Đã thống nhất:</strong></p>
  <ul>{done_list}</ul>
  <p><strong>Chưa giải quyết:</strong></p>
  <ul>{open_list}</ul>
</div>"""

    # ── 5. Kế hoạch hành động ──────────────────────────────────────────────
    # CEO thấy tất cả, người thường thấy tất cả (nhưng dòng của mình được highlight)
    action_table = _build_action_table(items, highlight_email=recipient_email)

    # Lọc my_items để highlight phần "Việc của bạn"
    my_items = [i for i in items if (i.get('pic_email') or i.get('assignee_email')) == recipient_email]
    my_items_html = ''
    if my_items and not is_ceo:
        def _my_row(i):
            dl = '🔴 Làm ngay' if i.get('type') == 'immediate' else f'📅 {i.get("deadline","?")}'
            task = i.get('viec') or i.get('task', '')
            return f'<li>{dl} — {task}</li>'
        my_rows = ''.join(_my_row(i) for i in my_items)
        my_items_html = f"""
<div style="background:#fff8e1;border-left:4px solid #f39c12;padding:12px 16px;margin-top:12px;border-radius:4px">
  <strong>⚠️ Việc được giao cho bạn:</strong>
  <ul style="margin:6px 0 0">{my_rows}</ul>
</div>"""

    sec5 = f"""
<div class="section">
  <h2 class="sec-title" style="color:#c0392b">5. Kế hoạch hành động (Action Items)</h2>
  {action_table}
  {my_items_html}
</div>"""

    # ── 6. Họp tiếp theo ──────────────────────────────────────────────────
    sec6 = f"""
<div class="section">
  <h2 class="sec-title">6. Lịch họp tiếp theo</h2>
  <p>{hop_sau}</p>
</div>"""

    # ── CEO block ─────────────────────────────────────────────────────────
    ceo_block = ''
    if is_ceo:
        # Tóm tắt tổng quan
        ceo_overview = f'<p style="margin:0">{ceo_sum}</p>' if ceo_sum else ''

        # Tóm tắt từng cá nhân
        summaries_by_role = analysis.get('summaries_by_role', {})
        individual_rows = ''
        if summaries_by_role:
            for email, summary in summaries_by_role.items():
                individual_rows += f"""
<tr style="border-bottom:1px solid #dde">
  <td style="padding:8px 10px;color:#555;width:180px;vertical-align:top"><small>{email}</small></td>
  <td style="padding:8px 10px">{summary}</td>
</tr>"""
            individuals_html = f"""
<h3 style="color:#2980b9;font-size:14px;margin:12px 0 6px">👤 Tóm tắt từng thành viên</h3>
<table style="width:100%;border-collapse:collapse;background:#f8fbff;border-radius:4px">
  {individual_rows}
</table>"""
        else:
            individuals_html = ''

        ceo_block = f"""
<div style="background:#e8f4fd;border-left:4px solid #2980b9;padding:14px 18px;margin-bottom:20px;border-radius:4px">
  <h2 style="margin-top:0;color:#2980b9;font-size:16px">📊 Tóm tắt cho CEO</h2>
  {ceo_overview}
  {individuals_html}
</div>"""

    # ── Personal summary (nếu không phải CEO) ─────────────────────────────
    personal_block = ''
    if not is_ceo and personal_summary:
        personal_block = f"""
<div style="background:#f0fdf4;border-left:4px solid #27ae60;padding:12px 16px;margin-bottom:20px;border-radius:4px">
  <strong style="color:#27ae60">📝 Tóm tắt cho bạn</strong>
  <p style="margin:6px 0 0">{personal_summary}</p>
</div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; max-width: 720px; margin: 0 auto; color: #333; font-size: 14px; }}
  .section {{ padding: 16px 0; border-bottom: 1px solid #eee; }}
  .section:last-child {{ border-bottom: none; }}
  .sec-title {{ font-size: 15px; color: #1a73e8; margin: 0 0 10px; padding-bottom: 4px; border-bottom: 2px solid #1a73e8; }}
  .info-table {{ border-collapse: collapse; width: 100%; }}
  .info-table td {{ padding: 5px 8px; vertical-align: top; }}
  .info-table .label {{ color: #666; width: 140px; white-space: nowrap; }}
  ul {{ margin: 6px 0; padding-left: 20px; }}
  li {{ margin-bottom: 4px; }}
</style>
</head>
<body>
  <div style="background:#1a73e8;color:white;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px">📋 Biên Bản Cuộc Họp</h1>
    <p style="margin:4px 0 0;opacity:.85">{meeting_title} · {meeting_date}</p>
  </div>
  <div style="padding:20px 24px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px">
    <p style="color:#555;margin-top:0">Kính gửi <strong>{recipient_name}</strong>,</p>
    {ceo_block}
    {personal_block}
    {sec1}
    {sec2}
    {sec3}
    {sec4}
    {sec5}
    {sec6}
    <hr style="margin-top:24px">
    <p style="color:#aaa;font-size:12px;margin-bottom:0">
      Email tự động từ IDS Meeting Bot · nguyenpd@ids-international.vn<br>
      File .ics đính kèm → nhấn <em>Accept</em> để lưu deadline vào lịch của bạn.
    </p>
  </div>
</body></html>"""


def send_to_participant(meeting_title: str, meeting_date: str,
                        participant: dict, analysis: dict, is_ceo: bool):
    """Gửi biên bản cá nhân hóa cho 1 người."""
    email  = participant['email']
    name   = participant.get('name', email)

    personal_summary = analysis.get('summaries_by_role', {}).get(email) \
                    or analysis.get('summary_ceo', '')
    action_items = analysis.get('action_items', [])

    msg             = MIMEMultipart('mixed')
    msg['From']     = f'"IDS Meeting Bot" <{SMTP_USER}>'
    msg['To']       = email
    msg['Subject']  = f'[Biên Bản] {meeting_title} · {meeting_date}'
    msg['Reply-To'] = SMTP_USER

    html = _build_html(meeting_title, meeting_date, name, personal_summary,
                       analysis, email, is_ceo)
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    # Đính kèm .ics cho các deadline task được giao cho người này
    my_deadline_items = [
        i for i in action_items
        if (i.get('pic_email') or i.get('assignee_email')) == email
        and i.get('type') == 'deadline'
        and i.get('deadline')
    ]
    for item in my_deadline_items:
        task_name = item.get('viec') or item.get('task', '')
        ics_data  = _create_ics(task_name, email, item['deadline'])
        if ics_data:
            safe_name = task_name[:25].replace(' ', '_').replace('/', '-')
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
