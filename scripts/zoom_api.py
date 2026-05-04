"""Zoom Server-to-Server OAuth API wrapper."""

import os
import base64
import time
import requests

ZOOM_ACCOUNT_ID    = os.environ['ZOOM_ACCOUNT_ID']
ZOOM_CLIENT_ID     = os.environ['ZOOM_CLIENT_ID']
ZOOM_CLIENT_SECRET = os.environ['ZOOM_CLIENT_SECRET']

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
    r.raise_for_status()
    data = r.json()
    _token_cache['token']      = data['access_token']
    _token_cache['expires_at'] = now + data.get('expires_in', 3600)
    return _token_cache['token']


def get_recordings(meeting_uuid: str, retries: int = 5, wait: int = 30) -> dict:
    """Get recording files for a meeting. Retries while transcript is being processed."""
    token = get_access_token()
    # URL-encode double-encoded UUID
    encoded_uuid = requests.utils.quote(requests.utils.quote(meeting_uuid, safe=''), safe='')

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

        # Check if transcript file exists
        files = data.get('recording_files', [])
        has_transcript = any(f.get('file_type') == 'TRANSCRIPT' for f in files)

        if not has_transcript and attempt < retries - 1:
            print(f"  ⏳ Transcript not ready yet (attempt {attempt+1}/{retries}), waiting {wait}s...")
            time.sleep(wait)
            token = get_access_token()
            continue

        return data

    return {}


def download_transcript(download_url: str) -> str:
    """Download and return VTT transcript content."""
    token = get_access_token()
    r = requests.get(
        f"{download_url}?access_token={token}",
        timeout=30
    )
    r.raise_for_status()
    return r.text


def parse_vtt(vtt_content: str) -> str:
    """Convert VTT transcript to clean plain text."""
    lines = vtt_content.splitlines()
    result = []
    prev   = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue
        if '-->' in line:
            continue
        # Skip cue identifiers (pure numbers)
        if line.isdigit():
            continue
        # Deduplicate consecutive identical lines (VTT overlap)
        if line != prev:
            result.append(line)
            prev = line

    return '\n'.join(result)
