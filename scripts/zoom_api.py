"""Zoom Server-to-Server OAuth API wrapper."""

import os
import base64
import time
import requests

ZOOM_ACCOUNT_ID    = os.environ['ZOOM_ACCOUNT_ID'].strip()
ZOOM_CLIENT_ID     = os.environ['ZOOM_CLIENT_ID'].strip()
ZOOM_CLIENT_SECRET = os.environ['ZOOM_CLIENT_SECRET'].strip()

_token_cache = {'token': None, 'expires_at': 0}


def get_access_token() -> str:
    """Get Zoom OAuth token (cached, auto-refresh)."""
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at'] - 60:
        return _token_cache['token']

    creds = base64.b64encode(f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={ZOOM_ACCOUNT_ID}",
        headers={'Authorization': f'Basic {creds}'},
        timeout=15
    )
    if not r.ok:
        raise Exception(f"Zoom token error {r.status_code}: {r.text}")
    data = r.json()
    _token_cache['token']      = data['access_token']
    _token_cache['expires_at'] = now + data.get('expires_in', 3600)
    return _token_cache['token']


def _encode_uuid(uuid: str) -> str:
    """Encode UUID đúng chuẩn Zoom: double-encode nếu bắt đầu / hoặc có //"""
    if uuid.startswith('/') or '//' in uuid:
        return requests.utils.quote(requests.utils.quote(uuid, safe=''), safe='')
    return requests.utils.quote(uuid, safe='')


def get_recordings(meeting_uuid: str, meeting_id: str = '', retries: int = 6, wait: int = 30) -> dict:
    """Get recording files. Thử UUID trước, fallback về numeric meeting_id nếu lỗi."""
    token = get_access_token()

    # Danh sách ID để thử theo thứ tự
    candidates = []
    if meeting_uuid:
        candidates.append(_encode_uuid(meeting_uuid))
    if meeting_id:
        candidates.append(meeting_id)

    for attempt in range(retries):
        success = False
        for candidate in candidates:
            r = requests.get(
                f"https://api.zoom.us/v2/meetings/{candidate}/recordings",
                headers={'Authorization': f'Bearer {token}'},
                timeout=15
            )
            if r.status_code in (400, 404):
                print(f"  ⚠️ {r.status_code} với {candidate[:30]}: {r.text[:300]}")
                continue
            if not r.ok:
                print(f"  ⚠️ Lỗi {r.status_code}: {r.text[:200]}")
                continue

            data = r.json()
            files = data.get('recording_files', [])
            has_audio = any(f.get('file_type') in ('M4A', 'MP4') for f in files)
            if not has_audio and attempt < retries - 1:
                print(f"  ⏳ Audio chưa sẵn (attempt {attempt+1}/{retries}), chờ {wait}s...")
                success = True  # candidate đúng, chỉ chưa có audio
                break
            return data

        if not success and attempt < retries - 1:
            print(f"  ⏳ Chưa lấy được recording (attempt {attempt+1}/{retries}), chờ {wait}s...")

        time.sleep(wait)
        token = get_access_token()

    return {}


def download_audio_file(download_url: str, output_path: str) -> str:
    """Download Zoom audio file (M4A/MP4) về local temp path."""
    token = get_access_token()
    r = requests.get(
        f"{download_url}?access_token={token}",
        timeout=300,
        stream=True
    )
    r.raise_for_status()
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✓ Downloaded audio: {size_mb:.1f} MB → {output_path}")
    return output_path


def compress_audio_if_needed(input_path: str) -> str:
    """Nén audio về ≤24MB bằng ffmpeg (nếu cần) để gửi Groq Whisper."""
    import subprocess
    size_mb = os.path.getsize(input_path) / (1024 * 1024)
    if size_mb <= 24:
        return input_path

    print(f"  ⚙️ File {size_mb:.1f}MB > 24MB, đang nén...")
    output_path = input_path.rsplit('.', 1)[0] + '_compressed.mp3'
    subprocess.run([
        'ffmpeg', '-i', input_path,
        '-ac', '1',
        '-b:a', '32k',
        '-y', output_path
    ], check=True, capture_output=True)
    new_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✓ Nén xong: {new_size:.1f}MB")
    return output_path
