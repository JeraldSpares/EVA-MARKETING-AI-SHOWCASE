# -*- coding: utf-8 -*-
"""
post_to_facebook_story.py
=========================
Posts today's scheduled image as a Facebook Story via Graph API.
Runs daily at 8:00 AM PHT via GitHub Actions.

Required GitHub Secrets:
  FB_PAGE_ACCESS_TOKEN  — Long-lived Facebook Page Access Token
  FB_PAGE_ID            — Numeric Facebook Page ID
  GOOGLE_DRIVE_CREDENTIALS / GOOGLE_DRIVE_FOLDER_ID — for image download
  IMGBB_API_KEY         — for public CDN URL (Stories require public URL)
"""

import os
import sys
import json
import time
import requests
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from drive_helper import is_cloud, download_by_name, upload_to_imgbb

sys.stdout.reconfigure(encoding="utf-8")

PHT = timezone(timedelta(hours=8))

FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
FB_PAGE_ID           = os.environ.get("FB_PAGE_ID", "")
IMGBB_API_KEY        = os.environ.get("IMGBB_API_KEY", "")
GRAPH_API_VERSION    = "v19.0"

BASE_DIR      = Path(__file__).parent
SCHEDULE_FILE = BASE_DIR / "posting_schedule.json"


# ─────────────────────────────────────────────────────────────
# IMAGE
# ─────────────────────────────────────────────────────────────

def get_todays_image_name() -> str:
    """Return the scheduled image filename for today (PHT)."""
    if not SCHEDULE_FILE.exists():
        raise FileNotFoundError("posting_schedule.json not found.")
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f).get("schedule", {})
    today = datetime.now(PHT).strftime("%Y-%m-%d")
    filename = schedule.get(today)
    if not filename:
        raise ValueError(f"No image scheduled for {today}.")
    return filename


def get_public_image_url() -> tuple:
    """Download today's image and return (public_url, filename)."""
    filename  = get_todays_image_name()
    img_bytes = download_by_name(filename)
    print(f"  Image: {filename}")
    print("  Uploading to imgBB for public URL...")
    url = upload_to_imgbb(img_bytes, filename)
    return url, filename


# ─────────────────────────────────────────────────────────────
# FACEBOOK STORY
# ─────────────────────────────────────────────────────────────

def post_facebook_story(image_url: str) -> bool:
    """
    Post an image as a Facebook Page Story via Graph API.
    Endpoint: POST /{page-id}/photo_stories
    """
    if not FB_PAGE_ACCESS_TOKEN:
        print("  ERROR: FB_PAGE_ACCESS_TOKEN not set.")
        return False
    if not FB_PAGE_ID:
        print("  ERROR: FB_PAGE_ID not set.")
        return False

    endpoint = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{FB_PAGE_ID}/photo_stories"
    payload  = {
        "url":          image_url,
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }

    print(f"  Posting to Facebook Story API...")
    resp = requests.post(endpoint, data=payload, timeout=30)
    data = resp.json()

    if resp.status_code == 200 and "post_id" in data:
        print(f"  Facebook Story posted! post_id: {data['post_id']}")
        return True
    else:
        print(f"  ERROR: {resp.status_code} — {data}")
        return False


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  Enderun Marketing — Facebook Story")
    print(f"  {datetime.now(PHT).strftime('%B %d, %Y %H:%M')} PHT")
    if dry_run:
        print("  [DRY RUN] Preview only — no actual post.")
    print("=" * 60)

    if not FB_PAGE_ACCESS_TOKEN:
        print("  ERROR: FB_PAGE_ACCESS_TOKEN not set.")
        sys.exit(1)
    if not FB_PAGE_ID:
        print("  ERROR: FB_PAGE_ID not set.")
        sys.exit(1)
    if not IMGBB_API_KEY:
        print("  ERROR: IMGBB_API_KEY not set.")
        sys.exit(1)

    try:
        image_url, filename = get_public_image_url()
    except Exception as e:
        print(f"  ERROR getting image: {e}")
        sys.exit(1)

    print(f"  Image URL: {image_url}")

    if dry_run:
        print("  [DRY RUN] Would post to Facebook Story. Exiting.")
        return

    ok = post_facebook_story(image_url)
    if not ok:
        sys.exit(1)

    print("\n  Facebook Story posted successfully.")


if __name__ == "__main__":
    main()
