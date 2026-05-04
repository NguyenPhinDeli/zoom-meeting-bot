"""
Script chạy 1 lần để tạo Google Sheets và điền dữ liệu mẫu team.
Chạy: python setup_sheets.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from sheets_manager import get_or_create_spreadsheet, _sheets_service

SAMPLE_TEAM = [
    # Sửa lại theo đúng team IDS của anh
    ['Phạm Đình Nguyên', 'nguyenpd@ids-international.vn', 'CEO',     'TRUE'],
    ['Nhân viên 1',      'nv1@ids-international.vn',      'Sales',   'TRUE'],
    ['Nhân viên 2',      'nv2@ids-international.vn',      'Kế toán', 'TRUE'],
]


def main():
    print("Tạo Google Sheets cho IDS Meeting Bot...")
    sid = get_or_create_spreadsheet()
    print(f"  Spreadsheet ID: {sid}")
    print(f"  URL: https://docs.google.com/spreadsheets/d/{sid}")

    # Điền sample team
    sheets = _sheets_service()
    sheets.spreadsheets().values().append(
        spreadsheetId=sid,
        range='Team!A2',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': SAMPLE_TEAM}
    ).execute()
    print(f"  ✓ Đã thêm {len(SAMPLE_TEAM)} thành viên mẫu vào tab Team")
    print("\n⚠️  Hãy mở Spreadsheet và cập nhật đúng tên + email team IDS!")
    print(f"  https://docs.google.com/spreadsheets/d/{sid}/edit#gid=0")

    # Lưu SHEETS_ID vào file
    sheets_id_file = os.path.join(os.path.dirname(__file__), 'sheets_id.txt')
    with open(sheets_id_file, 'w') as f:
        f.write(sid)
    print(f"\n  Sheets ID đã lưu vào: {sheets_id_file}")
    print("  → Copy ID này vào GitHub Secret: SHEETS_ID")


if __name__ == '__main__':
    main()
