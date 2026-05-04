"""
Cron job hằng ngày: kiểm tra tasks có deadline trong 48h và gửi nhắc.
Chạy bởi GitHub Actions mỗi 8g sáng VN time.
"""

import sys
from sheets_manager import get_due_soon_tasks, mark_reminded, get_team
from telegram_notify import notify_reminder, notify_reminder_to_group


def run():
    print("== Reminder: kiểm tra deadline 48h ==")

    tasks = get_due_soon_tasks(hours_ahead=48)
    print(f"  Tìm thấy {len(tasks)} task(s) cần nhắc.")

    if not tasks:
        print("  Không có gì cần nhắc hôm nay.")
        return 0

    # Build team lookup
    team = get_team()
    team_by_email = {p['email'].lower(): p for p in team}

    reminded_rows = []
    tasks_by_person = {}

    for task in tasks:
        email = task['email'].lower()
        person = team_by_email.get(email, {'name': email})
        name   = person.get('name', email)

        # Nhắc anh Nguyên (owner) về từng task
        notify_reminder(
            task     = task['task'],
            assignee_name = name,
            deadline = task['deadline'],
            priority = task.get('priority', 'medium')
        )

        # Gom lại để nhắc group 1 lần
        if name not in tasks_by_person:
            tasks_by_person[name] = []
        tasks_by_person[name].append(task)

        reminded_rows.append(task['row_idx'])

    # Nhắc team group (1 message gộp tất cả)
    if tasks_by_person:
        notify_reminder_to_group(tasks_by_person)

    # Đánh dấu đã nhắc trong Sheets
    mark_reminded(reminded_rows)
    print(f"  ✓ Đã nhắc {len(reminded_rows)} task(s) và đánh dấu trong Sheets.")
    return 0


if __name__ == '__main__':
    sys.exit(run())
