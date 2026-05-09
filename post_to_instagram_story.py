# -*- coding: utf-8 -*-
"""
post_to_instagram_story.py
==========================
Posts today's scheduled image as an Instagram Story via Graph API.
Runs daily at 8:00 AM PHT via GitHub Actions.

Instagram Story publishing is a 2-step process:
  1. Create a media container (POST /{ig-user-id}/media with media_type=STORIES)
  2. Publish the container (POST /{ig-user-id}/media_publish)

Required GitHub Secrets:
  IG_ACCESS_TOKEN       — Facebook Page Access Token (same account linked to IG)
  IG_USER_ID            — Numeric Instagram Business User ID
  GOOGLE_DRIVE_CREDENTIALS / GOOGLE_DRIVE_FOLDER_ID — for image download
  IMGBB_API_KEY         — for public CDN URL (Instagram API requires public URL)
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

from drive_helper import download_by_name, upload_to_imgbb

sys.stdout.reconfigure(encoding="utf-8")

PHT = timezone(timedelta(hours=8))

IG_ACCESS_TOKEN   = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID        = os.environ.get("IG_USER_ID", "")
IMGBB_API_KEY     = os.environ.get("IMGBB_API_KEY", "")
GRAPH_API_VERSION = "v19.0"

BASE_DIR      = Path(__file__).parent
SCHEDULE_FILE = BASE_DIR / "posting_schedule.json"


# ─────────────────────────────────────────────────────────────
# IMAGE
# ─────────────────────────────────────────────────────────────

def get_todays_image_name() -> str:
    if not SCHEDULE_FILE.exists():
        raise FileNotFoundError("posting_schedule.json not found.")
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f).get("schedule", {})
    today    = datetime.now(PHT).strftime("%Y-%m-%d")
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
# INSTAGRAM STORY — 2-step publish
# ─────────────────────────────────────────────────────────────

def create_story_container(image_url: str) -> str:
    """Step 1: Create a media container for the Story. Returns container ID."""
    endpoint = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{IG_USER_ID}/media"
    payload  = {
        "image_url":    image_url,
        "media_type":   "STORIES",
        "access_token": IG_ACCESS_TOKEN,
    }
    print("  Step 1: Creating Story container...")
    resp = requests.post(endpoint, data=payload, timeout=30)
    data = resp.json()

    if resp.status_code != 200 or "id" not in data:
        raise RuntimeError(f"Container creation failed: {resp.status_code} — {data}")

    container_id = data["id"]
    print(f"  Container created: {container_id}")
    return container_id


def publish_story_container(container_id: str) -> bool:
    """Step 2: Publish the Story container. Returns True on success."""
    endpoint = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{IG_USER_ID}/media_publish"
    payload  = {
        "creation_id":  container_id,
        "access_token": IG_ACCESS_TOKEN,
    }
    print("  Step 2: Publishing Story...")
    resp = requests.post(endpoint, data=payload, timeout=30)
    data = resp.json()

    if resp.status_code == 200 and "id" in data:
        print(f"  Instagram Story published! media_id: {data['id']}")
        return True
    else:
        print(f"  ERROR publishing Story: {resp.status_code} — {data}")
        return False


def post_instagram_story(image_url: str) -> bool:
    """Full 2-step Instagram Story publish flow."""
    try:
        container_id = create_story_container(image_url)
        # Brief wait — Instagram recommends a short pause before publishing
        time.sleep(3)
        return publish_story_container(container_id)
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  Enderun Marketing — Instagram Story")
    print(f"  {datetime.now(PHT).strftime('%B %d, %Y %H:%M')} PHT")
    if dry_run:
        print("  [DRY RUN] Preview only — no actual post.")
    print("=" * 60)

    if not IG_ACCESS_TOKEN:
        print("  ERROR: IG_ACCESS_TOKEN not set.")
        sys.exit(1)
    if not IG_USER_ID:
        print("  ERROR: IG_USER_ID not set.")
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
        print("  [DRY RUN] Would post to Instagram Story. Exiting.")
        return

    ok = post_instagram_story(image_url)
    if not ok:
        sys.exit(1)

    print("\n  Instagram Story posted successfully.")


if __name__ == "__main__":
    main()
