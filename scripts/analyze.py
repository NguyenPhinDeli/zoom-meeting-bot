"""Phân tích transcript cuộc họp bằng Claude API → biên bản 6-section chuẩn."""

import os
import json
import time
import anthropic

CLAUDE_MODEL = "claude-haiku-4-5"  # nhanh + rẻ (~$0.001/cuộc họp)
MAX_TRANSCRIPT_CHARS = 60_000


def analyze_meeting(transcript: str, meeting_title: str,
                    participants: list[dict],
                    start_time: str = '', duration: int = 0,
                    host_email: str = '') -> dict:
    """
    params:
      participants: [{"name": "Nam", "email": "nam@ids.vn", "role": "Sales"}]
    returns dict theo 6-section biên bản chuẩn IDS
    """
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    participants_str = '\n'.join(
        f"- {p['name']} ({p.get('role','Nhân viên')}): {p['email']}"
        for p in participants
    )
    participant_emails = [p['email'] for p in participants]

    # Truncate transcript if too long
    transcript_trimmed = transcript[:MAX_TRANSCRIPT_CHARS]
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript_trimmed += '\n[... transcript đã được rút gọn ...]'

    # Host info
    host_info = f" (host: {host_email})" if host_email else ''

    # Format thời gian đẹp hơn
    time_str = start_time or 'Không rõ'
    duration_str = f"{duration} phút" if duration else ''

    prompt = f"""Bạn là trợ lý AI của công ty IDS (phân phối Castrol và L'Oréal tại TP.HCM).
Hãy phân tích transcript cuộc họp và tạo biên bản họp chính thức theo đúng 6 mục chuẩn.

Tiêu đề cuộc họp: {meeting_title}
Thời gian: {time_str} {duration_str}

Người tổ chức (host){host_info}: suy ra tên từ email hoặc transcript để điền vào chu_tri
Danh sách mời (có thể vắng nếu transcript không đề cập):
{participants_str}

Transcript:
---
{transcript_trimmed}
---

Trả về JSON (không thêm markdown, không comment):
{{
  "thong_tin_chung": {{
    "ten_cuoc_hop": "{meeting_title}",
    "thoi_gian": "{time_str}",
    "thoi_luong": "{duration_str}",
    "chu_tri": "Tên người chủ trì (suy ra từ transcript)",
    "tham_du": ["Tên (Chức vụ)"],
    "vang_mat": ["Tên (Chức vụ) - nếu có trong danh sách mời nhưng không xuất hiện trong transcript"]
  }},
  "muc_tieu": "1-2 câu mô tả mục tiêu/agenda của cuộc họp",
  "noi_dung_thao_luan": [
    {{
      "van_de": "Tên vấn đề / chủ đề thảo luận",
      "noi_dung": "Tóm tắt ngắn gọn nội dung đã bàn, ý kiến các bên"
    }}
  ],
  "quyet_dinh": {{
    "da_thong_nhat": ["Quyết định 1 đã được thống nhất", "Quyết định 2"],
    "chua_giai_quyet": ["Vấn đề 1 chưa có kết luận (nếu có)"]
  }},
  "action_items": [
    {{
      "stt": 1,
      "viec": "Mô tả rõ ràng việc cần làm",
      "pic_name": "Tên người phụ trách",
      "pic_email": "email@domain.com (dùng email từ danh sách nếu khớp tên)",
      "deadline": "YYYY-MM-DD hoặc null nếu làm ngay hôm nay",
      "type": "immediate (làm ngay) hoặc deadline (có ngày cụ thể)",
      "priority": "high hoặc medium hoặc low"
    }}
  ],
  "hop_tiep_theo": "DD/MM/YYYY HH:MM hoặc Chưa xác định",
  "summary_ceo": "Tóm tắt 5-7 dòng cho CEO: kết quả, quyết định quan trọng, rủi ro, điểm cần chú ý",
  "summaries_by_role": {{
    "email@domain.com": "Tóm tắt 2-3 câu liên quan trực tiếp đến người này và việc được giao"
  }},
  "keywords": ["từ khóa 1", "từ khóa 2", "từ khóa 3"]
}}

Lưu ý bắt buộc:
- action_items là phần QUAN TRỌNG NHẤT — liệt kê đầy đủ, rõ ràng, đúng người
- summaries_by_role phải có key là email của mỗi người trong danh sách tham dự
- pic_email trong action_items phải là email từ danh sách: {participant_emails}
- Nếu người phụ trách không rõ email → dùng email của host/chủ trì
- immediate = làm ngay (deadline = null), deadline = có ngày cụ thể
"""

    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            # Claude trả plain text → parse JSON từ content
            raw = resp.content[0].text.strip()
            # Bỏ markdown code block nếu có
            if raw.startswith('```'):
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            data = json.loads(raw)
            # Override chu_tri bằng host_email từ Zoom (chính xác hơn Claude đoán)
            if host_email and 'thong_tin_chung' in data:
                data['thong_tin_chung']['chu_tri'] = host_email
            # Backward-compat: đảm bảo key cũ vẫn tồn tại cho pipeline.py
            if 'action_items' in data:
                for i, item in enumerate(data['action_items']):
                    # Map key mới → key cũ nếu cần
                    if 'viec' in item and 'task' not in item:
                        item['task'] = item['viec']
                    if 'pic_email' in item and 'assignee_email' not in item:
                        item['assignee_email'] = item['pic_email']
            return data
        except Exception as e:
            print(f"  ⚠️ Claude API lỗi lần {attempt+1}: {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    # Fallback nếu Groq fail
    return {
        "thong_tin_chung": {
            "ten_cuoc_hop": meeting_title,
            "thoi_gian": time_str,
            "thoi_luong": duration_str,
            "chu_tri": "",
            "tham_du": [p['name'] for p in participants],
            "vang_mat": []
        },
        "muc_tieu": "",
        "noi_dung_thao_luan": [],
        "quyet_dinh": {"da_thong_nhat": [], "chua_giai_quyet": []},
        "action_items": [],
        "hop_tiep_theo": "Chưa xác định",
        "summary_ceo": "Không thể phân tích transcript tự động.",
        "summaries_by_role": {},
        "keywords": []
    }


def reanalyze_from_doc(doc_text: str, meeting_title: str,
                       participants: list, host_email: str = '') -> dict:
    """Re-parse nội dung Google Doc (sau khi CEO chỉnh sửa) → JSON 6-section."""
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    participant_emails = [p['email'] for p in participants]
    participants_str   = '\n'.join(
        f"- {p['name']} ({p.get('role','Nhân viên')}): {p['email']}"
        for p in participants
    )

    prompt = f"""Bạn là trợ lý AI của IDS. Dưới đây là nội dung biên bản họp đã được CEO chỉnh sửa.
Hãy đọc và trả về JSON 6-section chuẩn (không thêm markdown):

Tiêu đề: {meeting_title}
Host: {host_email}
Participants:
{participants_str}

Nội dung biên bản (đã được CEO chỉnh sửa):
---
{doc_text[:40000]}
---

Trả về JSON với cấu trúc giống như analyze_meeting (thong_tin_chung, muc_tieu, noi_dung_thao_luan, quyet_dinh, action_items, hop_tiep_theo, summary_ceo, summaries_by_role, keywords).
pic_email trong action_items phải dùng email từ danh sách: {participant_emails}
"""

    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith('```'):
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            data = json.loads(raw)
            if host_email and 'thong_tin_chung' in data:
                data['thong_tin_chung']['chu_tri'] = host_email
            if 'action_items' in data:
                for item in data['action_items']:
                    if 'viec' in item and 'task' not in item:
                        item['task'] = item['viec']
                    if 'pic_email' in item and 'assignee_email' not in item:
                        item['assignee_email'] = item['pic_email']
            return data
        except Exception as e:
            print(f"  ⚠️ Re-analyze lỗi lần {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return {}  # Fallback rỗng
