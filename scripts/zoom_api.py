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


def get_recordings(meeting_uuid: str, retries: int = 6, wait: int = 30) -> dict:
    """Get recording files for a meeting. Retries while audio is being processed."""
    token = get_access_token()
    # Double-encode chỉ khi UUID bắt đầu bằng "/" hoặc chứa "//"
    if meeting_uuid.startswith('/') or '//' in meeting_uuid:
        encoded_uuid = requests.utils.quote(requests.utils.quote(meeting_uuid, safe=''), safe='')
    else:
        encoded_uuid = requests.utils.quote(meeting_uuid, safe='')

    for attempt in range(retries):
        r = requests.get(
            f"https://api.zoom.us/v2/meetings/{encoded_uuid}/recordings",
            headers={'Authorization': f'Bearer {token}'},
            timeout=15
        )
        if r.status_code == 404:
            print(f"  ⏳ Recordings not ready (attempt {attempt+1}/{retries}), waiting {wait}s...")
            time.sleep(wait)
            token = get_access_token()
            continue
        r.raise_for_status()
        data = r.json()

        files = data.get('recording_files', [])
        # Ưu tiên M4A (audio only) để dùng với Whisper
        has_audio = any(f.get('file_type') in ('M4A', 'MP4') for f in files)
        if not has_audio and attempt < retries - 1:
            print(f"  ⏳ Audio not ready yet (attempt {attempt+1}/{retries}), waiting {wait}s...")
            time.sleep(wait)
            token = get_access_token()
            continue

        return data

    return {}


def download_audio_file(download_url: str, output_path: str) -> str:
    """Download Zoom audio file (M4A/MP4) về local temp path."""
    token = get_access_token()
    r = requests.get(
        f"{download_url}?access_token={token}",
        timeout=120,
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
        '-ac', '1',       # mono
        '-b:a', '32k',    # 32kbps → ~14MB/giờ
        '-y', output_path
    ], check=True, capture_output=True)
    new_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✓ Nén xong: {new_size:.1f}MB")
    return output_path
