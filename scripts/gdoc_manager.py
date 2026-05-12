"""Tạo và đọc Google Doc draft biên bản họp."""

import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload


def _drive_service():
    from sheets_manager import _get_creds
    return build('drive', 'v3', credentials=_get_creds(), cache_discovery=False)


def create_draft_doc(meeting_title: str, analysis: dict, participants: list) -> tuple:
    """Tạo Google Doc với nội dung biên bản. Returns (doc_id, url)."""
    html = _build_doc_html(meeting_title, analysis, participants)
    drive = _drive_service()

    file_metadata = {
        'name': f'[DRAFT] Biên Bản - {meeting_title}',
        'mimeType': 'application/vnd.google-apps.document'
    }
    media = MediaInMemoryUpload(html.encode('utf-8'), mimetype='text/html')
    doc = drive.files().create(body=file_metadata, media_body=media).execute()
    doc_id = doc['id']

    # Cho phép bất kỳ ai có link đều chỉnh sửa được
    drive.permissions().create(
        fileId=doc_id,
        body={'type': 'anyone', 'role': 'writer'}
    ).execute()

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"  ✓ Google Doc tạo xong: {url}")
    return doc_id, url


def read_doc_as_text(doc_id: str) -> str:
    """Export Google Doc thành plain text để Claude re-parse."""
    drive = _drive_service()
    content = drive.files().export(fileId=doc_id, mimeType='text/plain').execute()
    return content.decode('utf-8') if isinstance(content, bytes) else str(content)


def _build_doc_html(meeting_title: str, analysis: dict, participants: list) -> str:
    """Build HTML đơn giản dễ đọc và dễ edit trong Google Doc."""
    tti       = analysis.get('thong_tin_chung', {})
    muc_tieu  = analysis.get('muc_tieu', '')
    thao_luan = analysis.get('noi_dung_thao_luan', [])
    quyet     = analysis.get('quyet_dinh', {})
    items     = analysis.get('action_items', [])
    hop_sau   = analysis.get('hop_tiep_theo', 'Chưa xác định')
    ceo_sum   = analysis.get('summary_ceo', '')

    # Thông tin chung
    s1 = f"""
<h2>1. THÔNG TIN CHUNG</h2>
<p><b>Tên cuộc họp:</b> {tti.get('ten_cuoc_hop', meeting_title)}</p>
<p><b>Thời gian:</b> {tti.get('thoi_gian', '')} {tti.get('thoi_luong', '')}</p>
<p><b>Người chủ trì:</b> {tti.get('chu_tri', '')}</p>
<p><b>Tham dự:</b> {', '.join(tti.get('tham_du', []))}</p>
<p><b>Vắng mặt:</b> {', '.join(tti.get('vang_mat', [])) or 'Không có'}</p>
"""

    # Tóm tắt CEO
    s_ceo = f"<h2>TÓM TẮT TỔNG QUAN</h2><p>{ceo_sum}</p>" if ceo_sum else ''

    # Mục tiêu
    s2 = f"<h2>2. MỤC TIÊU CUỘC HỌP</h2><p>{muc_tieu or '(Không rõ)'}</p>"

    # Nội dung thảo luận
    tl_html = ''.join(
        f"<p><b>{t['van_de']}</b><br>{t['noi_dung']}</p>"
        for t in thao_luan
    ) or '<p>(Không có chi tiết)</p>'
    s3 = f"<h2>3. NỘI DUNG THẢO LUẬN</h2>{tl_html}"

    # Quyết định
    done = ''.join(f"<li>{d}</li>" for d in quyet.get('da_thong_nhat', [])) or '<li>Không có</li>'
    open_ = ''.join(f"<li>{d}</li>" for d in quyet.get('chua_giai_quyet', [])) or '<li>Không có</li>'
    s4 = f"<h2>4. QUYẾT ĐỊNH & KẾT LUẬN</h2><p><b>Đã thống nhất:</b></p><ul>{done}</ul><p><b>Chưa giải quyết:</b></p><ul>{open_}</ul>"

    # Action items — dạng table dễ edit
    rows = ''
    for i, item in enumerate(items, 1):
        viec     = item.get('viec') or item.get('task', '')
        pic_name = item.get('pic_name', '')
        pic_email= item.get('pic_email') or item.get('assignee_email', '')
        deadline = item.get('deadline') or 'Làm ngay'
        priority = item.get('priority', 'medium')
        rows += f"<tr><td>{i}</td><td>{viec}</td><td>{pic_name} ({pic_email})</td><td>{deadline}</td><td>{priority}</td></tr>"

    s5 = f"""<h2>5. KẾ HOẠCH HÀNH ĐỘNG (ACTION ITEMS)</h2>
<table border="1" cellpadding="6" cellspacing="0">
<tr><th>#</th><th>Việc cần làm</th><th>PIC</th><th>Deadline</th><th>Ưu tiên</th></tr>
{rows or '<tr><td colspan="5">Không có action item</td></tr>'}
</table>"""

    s6 = f"<h2>6. LỊCH HỌP TIẾP THEO</h2><p>{hop_sau}</p>"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:40px auto">
<h1>BIÊN BẢN CUỘC HỌP</h1>
<h3>{meeting_title}</h3>
<hr>
{s_ceo}
{s1}{s2}{s3}{s4}{s5}{s6}
<hr>
<p><i>Draft tự động bởi IDS Meeting Bot. Vui lòng kiểm tra và chỉnh sửa trước khi gửi team.</i></p>
</body></html>"""
