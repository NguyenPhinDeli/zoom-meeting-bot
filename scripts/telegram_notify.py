"""Gửi thông báo Telegram cho anh Nguyên và team group."""

import os
import requests

TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID   = os.environ['TELEGRAM_CHAT_ID']          # anh Nguyên
TELEGRAM_GROUP_ID  = os.environ.get('TELEGRAM_GROUP_ID', '') # team group (optional)


def _send(chat_id: str, text: str, parse_mode: str = 'HTML') -> bool:
    if not chat_id:
        return False
    r = requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
        json={
            'chat_id'                 : chat_id,
            'text'                    : text,
            'parse_mode'              : parse_mode,
            'disable_web_page_preview': True
        },
        timeout=15
    )
    return r.status_code == 200


def notify_owner(text: str):
    """Gửi cho anh Nguyên."""
    return _send(TELEGRAM_CHAT_ID, text)


def notify_group(text: str):
    """Gửi cho team group (nếu đã cấu hình)."""
    if TELEGRAM_GROUP_ID:
        return _send(TELEGRAM_GROUP_ID, text)
    return False


def notify_meeting_done(meeting_title: str, meeting_date: str,
                        action_items_count: int, participants: list[dict]):
    """Thông báo sau khi pipeline hoàn tất."""
    names = ', '.join(p['name'] for p in participants)
    msg = (
        f'✅ <b>Biên bản đã gửi!</b>\n\n'
        f'📌 {meeting_title}\n'
        f'📅 {meeting_date}\n'
        f'👥 {names}\n'
        f'📋 {action_items_count} action item(s)\n\n'
        f'📨 Email đã gửi cho tất cả participants.'
    )
    notify_owner(msg)
    notify_group(msg)


def notify_reminder(task: str, assignee_name: str, deadline: str, priority: str):
    """Nhắc deadline cho anh (owner) — team group nhắc riêng."""
    icon = '🔥' if priority == 'high' else '⚡'
    msg = (
        f'{icon} <b>Nhắc việc — còn 48h</b>\n\n'
        f'👤 {assignee_name}\n'
        f'📝 {task}\n'
        f'📅 Deadline: <b>{deadline}</b>'
    )
    notify_owner(msg)


def notify_reminder_to_group(tasks_by_person: dict[str, list]):
    """Gửi nhắc deadline cho team group, nhóm theo người."""
    if not TELEGRAM_GROUP_ID:
        return
    lines = ['⏰ <b>Nhắc việc — deadline trong 48h</b>\n']
    for name, tasks in tasks_by_person.items():
        lines.append(f'<b>{name}:</b>')
        for t in tasks:
            lines.append(f'  • {t["task"]} → {t["deadline"]}')
        lines.append('')
    notify_group('\n'.join(lines))


def notify_meeting_reminder(meeting_title: str, meeting_time: str, join_url: str):
    """Nhắc anh 30 phút trước cuộc họp."""
    msg = (
        f'⏰ <b>Nhắc họp — 30 phút nữa!</b>\n\n'
        f'📌 {meeting_title}\n'
        f'🕐 {meeting_time}\n\n'
        f'🔗 <a href="{join_url}">Vào họp ngay</a>'
    )
    notify_owner(msg)


def notify_list_tasks(tasks: list[dict], chat_id: str):
    """Gửi danh sách tasks đang pending cho anh (trả lời lệnh /tasks)."""
    if not tasks:
        _send(chat_id, '✅ Không có action item nào đang pending!')
        return
    lines = ['📋 <b>Action Items đang pending:</b>\n']
    for t in tasks:
        icon = '🔥' if t.get('priority') == 'high' else '⚡'
        dl   = t.get('deadline', 'Làm ngay')
        lines.append(f'{icon} {t["task"]}\n   👤 {t["email"]} · 📅 {dl}\n')
    _send(chat_id, '\n'.join(lines))
