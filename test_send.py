# -*- coding: utf-8 -*-
"""
Enderun Marketing AI — Test / Demo Posting Script
==================================================
For live demos only. Posts to REAL Facebook, Instagram, and/or Email
WITHOUT touching the daily schedule, used_images_log, or leads.csv.

Uses the EXACT same caption generators, email builder, and posting
functions as the daily scripts — output is identical to real posts.

Usage:
  python test_send.py facebook
  python test_send.py instagram
  python test_send.py email --to demo@email.com --name "Maria Santos" --program "Culinary Arts"
  python test_send.py all   --to demo@email.com --name "Maria Santos" --program "BS Hospitality Management"
"""

import os
import sys
import io
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

PHT = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Import EXACT functions from daily scripts (same output as real posts)
# ---------------------------------------------------------------------------

# Facebook: caption generator + webhook poster + image helper
from post_to_facebook import (
    generate_caption      as _fb_generate_caption,
    post_to_facebook      as _fb_post,
    image_to_base64,
    ZAPIER_WEBHOOK        as FB_WEBHOOK,
    ENDERUN_EXT_LINK,
    HASHTAGS              as FB_HASHTAGS,
)

# Instagram: caption generator + webhook poster
from post_to_instagram import (
    generate_instagram_caption as _ig_generate_caption,
    post_to_instagram          as _ig_post,
    INSTAGRAM_WEBHOOK          as IG_WEBHOOK,
    HASHTAGS                   as IG_HASHTAGS,
)

# Drip email: copy generator + HTML builder + SMTP sender
from send_drip_email import (
    generate_email_copy as _email_generate_copy,
    build_html_email    as _email_build_html,
    send_email          as _email_send,
    GMAIL_ADDRESS,
    LOGO_PATH,
)

from drive_helper import is_cloud, download_by_name, upload_or_update, make_public_and_get_url, upload_to_imgbb
from PIL import Image

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

STAGING_FOLDER   = Path(r"G:\My Drive\FB_Post_Today")
SCHEDULE_FILE    = Path(__file__).parent / "posting_schedule.json"
CAPTION_OVERRIDE = os.environ.get("CAPTION_OVERRIDE", "").strip()
IMAGE_OVERRIDE   = os.environ.get("IMAGE_OVERRIDE",   "").strip()

# ---------------------------------------------------------------------------
# IMAGE PICKER — no schedule tracking, no used_images_log update
# ---------------------------------------------------------------------------

def get_test_image() -> tuple:
    """
    Get any available image for testing.
    Returns (image_path, img_bytes_or_None).
    Does NOT check/update schedule or used_images_log.
    Respects IMAGE_OVERRIDE env var to use the exact image chosen in Telegram.
    """
    if is_cloud():
        # Use the specific image the user selected in Telegram, if provided
        if IMAGE_OVERRIDE:
            try:
                img_bytes = download_by_name(IMAGE_OVERRIDE)
                tmp_path  = Path("/tmp") / IMAGE_OVERRIDE
                tmp_path.write_bytes(img_bytes)
                print(f"  Using selected image: {IMAGE_OVERRIDE}")
                return tmp_path, img_bytes
            except Exception as e:
                print(f"  Warning: could not load IMAGE_OVERRIDE '{IMAGE_OVERRIDE}': {e}. Falling back.")
        # Auto-pick: first available from schedule
        if SCHEDULE_FILE.exists():
            with open(SCHEDULE_FILE) as f:
                sched = json.load(f).get("schedule", {})
            for filename in sorted(sched.values()):
                try:
                    img_bytes = download_by_name(filename)
                    tmp_path  = Path("/tmp") / filename
                    tmp_path.write_bytes(img_bytes)
                    return tmp_path, img_bytes
                except Exception:
                    continue
        raise FileNotFoundError("No images available for cloud run.")
    else:
        # Prefer todays_post.jpg (already staged from morning post)
        preferred = STAGING_FOLDER / "todays_post.jpg"
        if preferred.exists() and preferred.stat().st_size > 1000:
            return preferred, None
        # Otherwise grab first image in folder
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            for p in STAGING_FOLDER.glob(ext):
                if p.name.lower() == "todays_post.jpg":
                    continue
                try:
                    if p.stat().st_size > 1000:
                        return p, None
                except Exception:
                    continue
        raise FileNotFoundError(f"No images found in {STAGING_FOLDER}")


# ---------------------------------------------------------------------------
# FACEBOOK TEST
# ---------------------------------------------------------------------------

def run_facebook_test() -> bool:
    print("\n[FACEBOOK TEST]")
    image_path, img_bytes = get_test_image()
    print(f"  Image: {image_path.name}")

    if CAPTION_OVERRIDE:
        caption = CAPTION_OVERRIDE
        print("  Using approved caption from Telegram.")
    else:
        print("  Generating caption with Claude AI (same as daily post)...")
        caption = _fb_generate_caption(image_path)

    print(f"\n  CAPTION PREVIEW:")
    print(f"  {caption[:300]}...")

    raw = img_bytes if img_bytes else image_path.read_bytes()
    if is_cloud():
        print("  Uploading to Google Drive...")
        file_id   = upload_or_update("todays_post.jpg", raw)
        image_url = make_public_and_get_url(file_id)
    else:
        print("  Uploading to imgBB for public URL...")
        image_url = upload_to_imgbb(raw, image_path.name)

    if CAPTION_OVERRIDE:
        # Post approved caption directly — skip _fb_post() to avoid adding duplicate URL/hashtags
        payload = {"caption": caption, "full_message": caption, "image_url": image_url}
        resp = requests.post(FB_WEBHOOK, json=payload, timeout=15)
        ok = resp.status_code == 200
        print(f"  Zapier response: {resp.status_code}")
        return ok

    return _fb_post(image_path, caption, image_url=image_url)


# ---------------------------------------------------------------------------
# INSTAGRAM TEST
# ---------------------------------------------------------------------------

def run_instagram_test() -> bool:
    print("\n[INSTAGRAM TEST]")
    if not IG_WEBHOOK:
        print("  ERROR: INSTAGRAM_ZAPIER_WEBHOOK not set.")
        return False

    image_path, img_bytes = get_test_image()
    print(f"  Image: {image_path.name}")

    if CAPTION_OVERRIDE:
        caption = CAPTION_OVERRIDE
        print("  Using approved caption from Telegram.")
    else:
        print("  Generating caption with Claude AI (same as daily post)...")
        caption = _ig_generate_caption(image_path)

    print(f"\n  CAPTION PREVIEW:")
    print(f"  {caption[:300]}...")

    raw = img_bytes if img_bytes else image_path.read_bytes()
    print("  Uploading to imgBB for CDN URL...")
    image_url = upload_to_imgbb(raw, image_path.name)

    if CAPTION_OVERRIDE:
        # Post approved caption directly — skip _ig_post() to avoid adding duplicate URL/hashtags
        payload = {"caption": caption, "full_caption": caption, "image_url": image_url}
        resp = requests.post(IG_WEBHOOK, json=payload, timeout=15)
        ok = resp.status_code == 200
        print(f"  Zapier response: {resp.status_code}")
        return ok

    return _ig_post(image_path, caption, image_url=image_url)


# ---------------------------------------------------------------------------
# DRIP EMAIL TEST
# ---------------------------------------------------------------------------

def run_email_test(to_email: str, first_name: str, program_interest: str) -> bool:
    print("\n[DRIP EMAIL TEST]")
    print(f"  To     : {to_email}")
    print(f"  Name   : {first_name}")
    print(f"  Program: {program_interest}")

    gmail = GMAIL_ADDRESS
    app_pass = os.environ.get("GMAIL_APP_PASS", "")
    if not gmail or not app_pass:
        print("  ERROR: GMAIL_ADDRESS or GMAIL_APP_PASS not set.")
        return False

    image_path, img_bytes = get_test_image()
    print(f"  Image  : {image_path.name}")

    # Load logo
    logo_bytes = None
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            logo_bytes = f.read()

    # Generate email copy — exact same function as daily drip
    print("  Generating email copy with Claude AI (same as daily drip)...")
    copy = _email_generate_copy(image_path, first_name, program_interest)
    print(f"  Subject  : {copy['subject']}")
    print(f"  Headline : {copy['headline']}")

    # Resize hero image for email
    raw = img_bytes if img_bytes else image_path.read_bytes()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if img.width > 600:
        ratio = 600 / img.width
        img = img.resize((600, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    image_bytes = buf.getvalue()

    # Build and send — exact same HTML template as daily drip
    html    = _email_build_html(copy, first_name)
    success = _email_send(to_email, copy["subject"], html, image_bytes, logo_bytes)

    if success:
        print(f"  Email sent to {to_email}!")
    return success


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enderun Marketing AI — Live Demo Posting")
    parser.add_argument("platform", choices=["facebook", "instagram", "email", "all"],
                        help="Platform to demo")
    parser.add_argument("--to",      default="",
                        help="Email recipient address (for email/all)")
    parser.add_argument("--name",    default="Demo Guest",
                        help="Recipient first name for email personalization")
    parser.add_argument("--program", default="BS Hospitality Management",
                        help="Program interest for email personalization")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    print("=" * 60)
    print("  Enderun Marketing AI — Live Demo")
    print(f"  {datetime.now(PHT).strftime('%B %d, %Y %H:%M')} PHT")
    print("  Real posts | Does NOT affect daily schedule or leads.")
    print("=" * 60)

    results = {}

    if args.platform in ("facebook", "all"):
        results["Facebook"] = run_facebook_test()

    if args.platform in ("instagram", "all"):
        results["Instagram"] = run_instagram_test()

    if args.platform in ("email", "all"):
        to_email = args.to or GMAIL_ADDRESS
        if not to_email:
            print("\n[EMAIL] ERROR: Provide --to email@address.com")
            results["Email"] = False
        else:
            results["Email"] = run_email_test(to_email, args.name, args.program)

    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    for platform, ok in results.items():
        print(f"  {platform:<12} {'SUCCESS' if ok else 'FAILED'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
