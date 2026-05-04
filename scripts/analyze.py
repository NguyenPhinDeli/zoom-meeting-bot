"""Phân tích transcript cuộc họp bằng Groq → biên bản + action items."""

import os
import json
import time
from groq import Groq

GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_TRANSCRIPT_CHARS = 10_000  # Groq context limit buffer


def analyze_meeting(transcript: str, meeting_title: str,
                    participants: list[dict]) -> dict:
    """
    params:
      participants: [{"name": "Nam", "email": "nam@ids.vn", "role": "Sales"}]
    returns dict with keys:
      summary_ceo, summaries_by_role, action_items, key_decisions, keywords
    """
    client = Groq(api_key=os.environ['GROQ_API_KEY'])

    participants_str = '\n'.join(
        f"- {p['name']} ({p.get('role','Nhân viên')}): {p['email']}"
        for p in participants
    )

    # Truncate transcript if too long
    transcript_trimmed = transcript[:MAX_TRANSCRIPT_CHARS]
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript_trimmed += '\n[... transcript đã được rút gọn ...]'

    prompt = f"""Bạn là trợ lý AI của công ty IDS (phân phối Castrol và L'Oréal tại TP.HCM).
Hãy phân tích transcript cuộc họp dưới đây và tạo biên bản chính thức.

Tiêu đề cuộc họp: {meeting_title}

Thành viên tham gia:
{participants_str}

Transcript:
---
{transcript_trimmed}
---

Hãy trả về JSON với format sau (không thêm markdown code block):
{{
  "summary_ceo": "Tóm tắt 5-7 dòng cho CEO: kết quả đạt được, quyết định quan trọng, rủi ro nếu có",
  "summaries_by_role": {{
    "email@domain.com": "Tóm tắt 3-4 dòng liên quan trực tiếp đến người này"
  }},
  "action_items": [
    {{
      "task": "Mô tả rõ ràng việc cần làm",
      "assignee_email": "email@domain.com",
      "deadline": "YYYY-MM-DD hoặc null nếu làm ngay",
      "type": "immediate hoặc deadline",
      "priority": "high hoặc medium hoặc low"
    }}
  ],
  "key_decisions": ["Quyết định 1", "Quyết định 2"],
  "keywords": ["từ khóa 1", "từ khóa 2", "từ khóa 3"]
}}

Lưu ý:
- "immediate" = làm ngay hôm nay/ngay bây giờ (deadline = null)
- "deadline" = có ngày cụ thể
- summaries_by_role phải có key là email của mỗi người tham gia
"""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"  ⚠️ Groq lỗi lần {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    # Fallback nếu Groq fail
    return {
        "summary_ceo": "Không thể phân tích transcript tự động.",
        "summaries_by_role": {},
        "action_items": [],
        "key_decisions": [],
        "keywords": []
    }
