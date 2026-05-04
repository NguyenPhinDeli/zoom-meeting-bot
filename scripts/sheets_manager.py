"""Quản lý Google Sheets: Team config, Meetings log, Action Items tracker."""

import os
import json
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE       = os.path.expanduser('~/Claude/token.json')
SHEETS_ID_FILE   = os.path.expanduser('~/Claude/zoom-meeting-bot/sheets_id.txt')
SCOPES           = ['https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/spreadsheets']


def _get_creds() -> Credentials:
    """Load + refresh Google credentials từ token.json."""
    # Nếu chạy trong GitHub Actions → dùng env var
    token_json = os.environ.get('GOOGLE_TOKEN_JSON')
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    else:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _sheets_service():
    return build('sheets', 'v4', credentials=_get_creds(), cache_discovery=False)


def _drive_service():
    return build('drive', 'v3', credentials=_get_creds(), cache_discovery=False)


def get_or_create_spreadsheet() -> str:
    """Lấy hoặc tạo mới spreadsheet IDS Meeting Bot."""
    # Đọc từ file cục bộ
    if os.path.exists(SHEETS_ID_FILE):
        with open(SHEETS_ID_FILE) as f:
            sid = f.read().strip()
        if sid:
            return sid

    # Đọc từ env (GitHub Actions)
    sid = os.environ.get('SHEETS_ID')
    if sid:
        return sid

    # Tạo mới
    sheets = _sheets_service()
    body = {
        'properties': {'title': 'IDS Meeting Bot — Data'},
        'sheets': [
            {'properties': {'title': 'Team',         'index': 0}},
            {'properties': {'title': 'Meetings',     'index': 1}},
            {'properties': {'title': 'ActionItems',  'index': 2}},
        ]
    }
    result = sheets.spreadsheets().create(body=body).execute()
    sid = result['spreadsheetId']

    # Tạo header rows
    _init_headers(sheets, sid)

    # Lưu ID vào file
    os.makedirs(os.path.dirname(SHEETS_ID_FILE), exist_ok=True)
    with open(SHEETS_ID_FILE, 'w') as f:
        f.write(sid)

    print(f"  ✓ Spreadsheet tạo mới: https://docs.google.com/spreadsheets/d/{sid}")
    return sid


def _init_headers(sheets, sid: str):
    """Khởi tạo header cho 3 tabs."""
    headers = {
        'Team': [['Tên', 'Email', 'Vai trò', 'Active (TRUE/FALSE)']],
        'Meetings': [['Meeting ID', 'Tiêu đề', 'Ngày', 'Participants', 'Keywords', 'Minutes URL', 'Created At']],
        'ActionItems': [['Meeting ID', 'Task', 'Assignee Email', 'Deadline', 'Type', 'Priority', 'Status', 'Reminded', 'Created At']]
    }
    data = []
    for sheet_name, rows in headers.items():
        data.append({
            'range': f'{sheet_name}!A1',
            'values': rows
        })
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sid,
        body={'valueInputOption': 'RAW', 'data': data}
    ).execute()


def get_team() -> list[dict]:
    """Lấy danh sách team từ tab Team (chỉ Active = TRUE)."""
    sheets = _sheets_service()
    sid    = get_or_create_spreadsheet()
    result = sheets.spreadsheets().values().get(
        spreadsheetId=sid, range='Team!A2:D'
    ).execute()
    rows = result.get('values', [])
    team = []
    for row in rows:
        if len(row) < 4:
            continue
        active = row[3].strip().upper()
        if active == 'TRUE':
            team.append({'name': row[0], 'email': row[1], 'role': row[2]})
    return team


def get_participants_for_meeting(emails: list[str]) -> list[dict]:
    """Map email list → participant dicts (với name + role từ Team sheet)."""
    team       = get_team()
    team_by_email = {p['email'].lower(): p for p in team}
    result = []
    for email in emails:
        info = team_by_email.get(email.lower())
        if info:
            result.append(info)
        else:
            result.append({'name': email.split('@')[0], 'email': email, 'role': 'Khách'})
    return result


def log_meeting(meeting_id: str, title: str, start_time: str,
                participants: list[dict], keywords: list[str]):
    """Ghi cuộc họp vào tab Meetings."""
    sheets = _sheets_service()
    sid    = get_or_create_spreadsheet()
    date   = start_time[:10]
    names  = ', '.join(p['name'] for p in participants)
    kws    = ', '.join(keywords)

    sheets.spreadsheets().values().append(
        spreadsheetId=sid,
        range='Meetings!A:G',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': [[
            meeting_id, title, date, names, kws, '', datetime.now().isoformat()
        ]]}
    ).execute()


def log_action_items(meeting_id: str, action_items: list[dict]):
    """Ghi action items vào tab ActionItems."""
    if not action_items:
        return
    sheets = _sheets_service()
    sid    = get_or_create_spreadsheet()
    now    = datetime.now().isoformat()
    rows   = []
    for item in action_items:
        rows.append([
            meeting_id,
            item.get('task', ''),
            item.get('assignee_email', ''),
            item.get('deadline', ''),
            item.get('type', ''),
            item.get('priority', ''),
            'pending',      # status
            'FALSE',        # reminded
            now
        ])
    sheets.spreadsheets().values().append(
        spreadsheetId=sid,
        range='ActionItems!A:I',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': rows}
    ).execute()
    print(f"  ✓ Ghi {len(rows)} action items vào Google Sheets")


def get_due_soon_tasks(hours_ahead: int = 48) -> list[dict]:
    """Lấy tasks có deadline trong vòng `hours_ahead` giờ và chưa nhắc."""
    from datetime import timezone, timedelta
    sheets = _sheets_service()
    sid    = get_or_create_spreadsheet()
    result = sheets.spreadsheets().values().get(
        spreadsheetId=sid, range='ActionItems!A2:I'
    ).execute()
    rows = result.get('values', [])

    now        = datetime.now(timezone.utc)
    cutoff     = now + timedelta(hours=hours_ahead)
    due_tasks  = []

    for idx, row in enumerate(rows, start=2):
        if len(row) < 8:
            continue
        meeting_id, task, email, deadline, typ, priority, status, reminded = row[:8]

        if typ != 'deadline' or not deadline:
            continue
        if status.lower() in ('done', 'completed'):
            continue
        if reminded.upper() == 'TRUE':
            continue

        try:
            dl = datetime.strptime(deadline, '%Y-%m-%d').replace(
                hour=9, tzinfo=timezone.utc)
        except ValueError:
            continue

        if now <= dl <= cutoff:
            due_tasks.append({
                'row_idx': idx,
                'meeting_id': meeting_id,
                'task': task,
                'email': email,
                'deadline': deadline,
                'priority': priority,
                'status': status
            })

    return due_tasks


def mark_reminded(row_indices: list[int]):
    """Đánh dấu đã nhắc cho các rows."""
    sheets = _sheets_service()
    sid    = get_or_create_spreadsheet()
    data   = [{'range': f'ActionItems!H{i}', 'values': [['TRUE']]}
              for i in row_indices]
    if data:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=sid,
            body={'valueInputOption': 'RAW', 'data': data}
        ).execute()
