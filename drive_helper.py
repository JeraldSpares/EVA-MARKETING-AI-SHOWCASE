# -*- coding: utf-8 -*-
"""
Google Drive Helper — used by automation scripts in GitHub Actions.
Detects cloud mode automatically (GITHUB_ACTIONS env var).
Falls back to local file system when running on local machine.
"""

import io
import json
import os
from pathlib import Path

FOLDER_ID_ENV = "GOOGLE_DRIVE_FOLDER_ID"   # Set this in GitHub Secrets
CREDS_ENV     = "GOOGLE_DRIVE_CREDENTIALS"  # Service account JSON string

_service     = None
_file_cache  = {}   # {folder_id: {filename: file_id}}


def is_cloud() -> bool:
    """True when running in GitHub Actions."""
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get(CREDS_ENV))


def _get_service():
    global _service
    if _service:
        return _service
    from googleapiclient.discovery import build
    from google.oauth2 import service_account

    creds_json = os.environ.get(CREDS_ENV)
    if creds_json:
        info = json.loads(creds_json)
    else:
        # Local fallback — put your service account JSON here
        creds_file = Path(__file__).parent / "google_credentials.json"
        with open(creds_file) as f:
            info = json.load(f)

    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _build_file_cache(folder_id: str) -> dict:
    """List all files in a Drive folder and cache name→id mapping."""
    service = _get_service()
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name)",
        pageSize=200,
    ).execute()
    mapping = {f["name"]: f["id"] for f in results.get("files", [])}
    _file_cache[folder_id] = mapping
    return mapping


def list_images(folder_id: str = None) -> list:
    """Return sorted list of all image filenames in the Google Drive folder."""
    fid = folder_id or os.environ.get(FOLDER_ID_ENV)
    if not fid:
        return []
    cache = _file_cache.get(fid) or _build_file_cache(fid)
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    return sorted(name for name in cache if Path(name).suffix.lower() in image_exts)


def download_by_name(filename: str, folder_id: str = None) -> bytes:
    """Download a file from Google Drive by filename. Returns raw bytes."""
    from googleapiclient.http import MediaIoBaseDownload

    fid = folder_id or os.environ.get(FOLDER_ID_ENV)
    if not fid:
        raise ValueError(f"Set {FOLDER_ID_ENV} environment variable or pass folder_id.")

    cache = _file_cache.get(fid) or _build_file_cache(fid)
    file_id = cache.get(filename)

    if not file_id:
        # Refresh cache and retry once
        cache = _build_file_cache(fid)
        file_id = cache.get(filename)

    if not file_id:
        raise FileNotFoundError(f"'{filename}' not found in Drive folder {fid}")

    service  = _get_service()
    request  = service.files().get_media(fileId=file_id)
    buf      = io.BytesIO()
    dl       = MediaIoBaseDownload(buf, request)
    done     = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def upload_or_update(filename: str, file_bytes: bytes, folder_id: str = None,
                     mime_type: str = "image/jpeg") -> str:
    """Upload file to Drive. Updates existing file if name already exists.
    Returns the file_id of the uploaded/updated file."""
    from googleapiclient.http import MediaIoBaseUpload

    fid     = folder_id or os.environ.get(FOLDER_ID_ENV)
    service = _get_service()
    cache   = _file_cache.get(fid) or _build_file_cache(fid)
    media   = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)

    existing_id = cache.get(filename)
    if existing_id:
        service.files().update(
            fileId=existing_id,
            media_body=media,
        ).execute()
        print(f"  Drive: updated '{filename}'")
        return existing_id
    else:
        meta = {"name": filename, "parents": [fid]}
        result = service.files().create(
            body=meta,
            media_body=media,
            fields="id",
        ).execute()
        file_id = result["id"]
        _file_cache[fid][filename] = file_id
        print(f"  Drive: uploaded '{filename}' (id={file_id})")
        return file_id


def make_public_and_get_url(file_id: str) -> str:
    """Make a Drive file publicly readable and return its direct image URL."""
    service = _get_service()
    # Set permission to anyone with link can view
    service.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
    ).execute()
    # Return direct download URL usable by Zapier/Facebook/Instagram
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print(f"  Drive: public URL → {url}")
    return url


def upload_to_imgbb(image_bytes: bytes, filename: str = "image.jpg") -> str:
    """Upload image to imgBB and return a direct public CDN URL.

    imgBB gives clean https://i.ibb.co/... URLs that Instagram/Facebook
    can access directly — unlike Google Drive redirect URLs.

    Requires IMGBB_API_KEY environment variable (free at imgbb.com/api).
    """
    import requests as _requests
    import base64 as _base64

    api_key = os.environ.get("IMGBB_API_KEY", "")
    if not api_key:
        raise ValueError("IMGBB_API_KEY is not set. Get a free key at https://api.imgbb.com/")

    b64 = _base64.b64encode(image_bytes).decode("utf-8")
    resp = _requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": api_key, "image": b64, "name": filename},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    url = data["data"]["url"]
    print(f"  imgBB: uploaded '{filename}' → {url}")
    return url
