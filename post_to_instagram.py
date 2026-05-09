# -*- coding: utf-8 -*-
"""
Enderun Extension - Daily Instagram Auto-Poster
Uses the same image staged for Facebook (todays_post.jpg on Google Drive),
generates an Instagram-optimized caption with Claude AI,
then posts via Zapier → Instagram for Business.

Run daily: python post_to_instagram.py
Auto mode: set AUTO_POST=true environment variable
"""

import os
import sys
import io
import json
import base64
import time
import requests
from pathlib import Path
from datetime import date
import anthropic
from notifications_helper import push_notification
from drive_helper import is_cloud, download_by_name
from PIL import Image

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

STAGING_FOLDER       = r"G:\My Drive\FB_Post_Today"
INSTAGRAM_WEBHOOK    = os.environ.get("INSTAGRAM_ZAPIER_WEBHOOK", "")
ENDERUN_EXT_LINK     = "https://enderunextension.com/"
POSTING_SCHEDULE     = Path(__file__).parent / "posting_schedule.json"

HASHTAGS = (
    "#EnderunExtension #EnderunColleges #BGC #McKinleyHill "
    "#ProfessionalDevelopment #LifelongLearning #UpskillPH "
    "#CulinaryArts #HospitalityPH #LearnWithEnderun "
    "#ContinuingEducation #CareerGrowth #ManilaPH "
    "#FoodEducation #HospitalityEducation #WineEducation "
    "#ServSafe #WSET #TESDA #ProfessionalCertification "
    "#CulinarySchoolPH #HospitalitySchool #BGCManila "
    "#SkillsForLife #CareerShift #UpgradeYourself "
    "#PhilippinesEducation #LearnMoreEarnMore"
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def get_media_type(image_path: Path) -> str:
    return "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"


def image_to_base64(image_path: Path) -> str:
    """Convert image to base64, resizing if over Claude's 4MB safe limit."""
    MAX_BYTES = 4 * 1024 * 1024
    with open(image_path, "rb") as f:
        raw = f.read()
    if len(raw) <= MAX_BYTES:
        return base64.standard_b64encode(raw).decode("utf-8")

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= MAX_BYTES or quality < 30:
            break
        if quality <= 50:
            w, h = img.size
            img = img.resize((int(w * 0.75), int(h * 0.75)), Image.LANCZOS)
        quality -= 10
    return base64.standard_b64encode(data).decode("utf-8")


def generate_instagram_caption(image_path: Path) -> str:
    """Generate an Instagram caption using Claude Vision with text-only fallback."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today  = date.today().strftime("%B %d, %Y")
    img_name = image_path.stem.replace("_", " ").replace("-", " ")

    prompt = (
        f"You are the Instagram Manager of Enderun Extension — the professional and "
        f"continuing education arm of Enderun Colleges, located in McKinley Hill, BGC, "
        f"Taguig, Philippines.\n\n"
        f"Today is {today}. Write an Instagram caption for a post about: {img_name}.\n\n"
        f"BRAND VOICE:\n"
        f"- Aspirational, lifestyle-forward, visually evocative\n"
        f"- Warm and proud of Filipino excellence\n"
        f"- Speaks to career growth, upskilling, and living well\n"
        f"- Pure English only — no Tagalog or Taglish\n"
        f"- Never stiff or corporate\n\n"
        f"INSTAGRAM CAPTION RULES:\n"
        f"- 2 to 3 short punchy paragraphs (shorter than Facebook)\n"
        f"- Start with a bold hook or lifestyle statement (not a question every time)\n"
        f"- Connect the topic to growth, skill, or aspiration\n"
        f"- End with a soft CTA (link in bio, visit our website, DM us, enroll now)\n"
        f"- Do NOT include hashtags (added separately)\n"
        f"- Do NOT include the URL (added separately)\n"
        f"- Use 1-2 relevant emojis naturally in the text (not at the end in a cluster)\n\n"
        f"Write ONLY the caption text. Nothing else."
    )

    # Try vision first (image + text), fall back to text-only if vision fails
    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": get_media_type(image_path),
                                "data": image_to_base64(image_path),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        print("  Caption generated with vision.")
    except Exception as vision_err:
        print(f"  Vision API failed ({vision_err}), falling back to text-only caption...")
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        print("  Caption generated (text-only fallback).")
    return response.content[0].text.strip()


def post_to_instagram(image_path: Path, caption: str, image_url: str = None) -> bool:
    """Send post to Zapier webhook → Instagram for Business."""
    full_caption = f"{caption}\n\n{ENDERUN_EXT_LINK}\n\n{HASHTAGS}"

    payload = {
        "caption":         caption,
        "full_caption":    full_caption,
        "hashtags":        HASHTAGS,
        "link_url":        ENDERUN_EXT_LINK,
        "image_url":       image_url or "",   # public Drive URL for 2-step Zap
        "image_filename":  "todays_post.jpg",
        "image_folder":    "FB_Post_Today",
        "image_full_path": str(image_path),
    }

    print("\nSending to Instagram Zapier webhook...")
    response = requests.post(INSTAGRAM_WEBHOOK, json=payload, timeout=15)

    if response.status_code == 200:
        resp_json = response.json()
        if resp_json.get("status") == "success":
            print("Posted successfully to Instagram!")
            return True
        else:
            print(f"Zapier response: {resp_json}")
            return True  # Zapier often returns 200 with different status keys
    else:
        print(f"Webhook error: {response.status_code} - {response.text}")
        return False


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv
    print("=" * 60)
    print("  Enderun Extension - Daily Instagram Auto-Poster")
    if dry_run:
        print("  *** DRY RUN MODE — will NOT post to Instagram ***")
    print("=" * 60)

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        return

    if not INSTAGRAM_WEBHOOK and not dry_run:
        print("ERROR: INSTAGRAM_ZAPIER_WEBHOOK is not set.")
        print("Add it as a GitHub Secret or environment variable.")
        return

    # Check for dashboard overrides
    override_image   = os.environ.get("OVERRIDE_IMAGE", "").strip()
    override_caption = os.environ.get("OVERRIDE_CAPTION", "").strip()
    override_hashtags = os.environ.get("OVERRIDE_HASHTAGS", "").strip()

    # 1. Get today's image (same one already staged for Facebook)
    today_str = date.today().isoformat()
    chosen_image = override_image if override_image else None

    if override_image:
        print(f"\nUsing override image: {override_image}")
    else:
        if POSTING_SCHEDULE.exists():
            with open(POSTING_SCHEDULE, "r") as f:
                schedule = json.load(f).get("schedule", {})
            if today_str in schedule:
                chosen_image = schedule[today_str]
                print(f"\nUsing scheduled image for {today_str}: {chosen_image}")

        if not chosen_image:
            # Fall back to most recent schedule entry
            if POSTING_SCHEDULE.exists():
                with open(POSTING_SCHEDULE) as f:
                    sched = json.load(f).get("schedule", {})
                for k in sorted(sched.keys()):
                    chosen_image = sched[k]
                    print(f"\nNo image scheduled today — using: {chosen_image}")
                    break
            if not chosen_image:
                print("No images in schedule. Exiting.")
                return

    # 2. Load image (cloud: download from Drive / local: read from staging folder)
    image_url = None
    if is_cloud():
        img_filename = chosen_image if isinstance(chosen_image, str) else Path(chosen_image).name
        print(f"\nDownloading {img_filename} from Google Drive...")
        img_bytes = download_by_name(img_filename)
        img_path  = Path("/tmp") / img_filename
        img_path.write_bytes(img_bytes)
        if not dry_run:
            from drive_helper import upload_to_imgbb
            image_url = upload_to_imgbb(img_bytes, img_filename)
    else:
        img_filename = chosen_image if isinstance(chosen_image, str) else Path(chosen_image).name
        img_path = Path(STAGING_FOLDER) / img_filename
        if not img_path.exists():
            img_path = Path(STAGING_FOLDER) / "todays_post.jpg"
        if not img_path.exists():
            print(f"Image not found: {img_path}")
            return
        print(f"\nUsing local image: {img_path}")
        if not dry_run:
            from drive_helper import upload_to_imgbb
            image_url = upload_to_imgbb(img_path.read_bytes(), img_path.name)

    # 3. Generate Instagram caption (use override if provided)
    if override_caption:
        caption = override_caption
        print(f"\nUsing override caption from dashboard.")
    else:
        print("\nGenerating Instagram caption with Claude AI...")
        caption = generate_instagram_caption(img_path)

    # Apply hashtag override
    global HASHTAGS
    if override_hashtags:
        HASHTAGS = override_hashtags
        print("Using override hashtags from dashboard.")

    print("\n" + "=" * 60)
    print("INSTAGRAM CAPTION PREVIEW")
    print("=" * 60)
    print(caption)
    print(f"\nLINK: {ENDERUN_EXT_LINK}")
    print(f"\nHASHTAGS:\n{HASHTAGS}")
    print("=" * 60)

    # 4. Confirm before posting (skip if AUTO_POST=true or dry_run)
    auto_post = os.environ.get("AUTO_POST", "false").lower() == "true"
    if not auto_post and not dry_run:
        confirm = input("\nPost this to Instagram? (y/n): ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    if dry_run:
        print("\n[DRY RUN] Skipping Instagram webhook.")
        print(f"[DRY RUN] Would have posted: {img_filename}")
        print(f"[DRY RUN] Caption preview:\n{caption}")
        print("\n[DRY RUN] Done — no changes made.")
        return

    # 5. Post via Zapier → Instagram
    success = post_to_instagram(img_path, caption, image_url=image_url)

    if success:
        push_notification(
            agent_id="instagram-post",
            level="success",
            title="Instagram post published",
            message=f"Posted \"{img_filename}\" to Enderun Extension Instagram.",
        )
        print("\nDone!")
    else:
        push_notification(
            agent_id="instagram-post",
            level="critical",
            title="Instagram post failed",
            message="Zapier webhook did not return success. Check your Instagram webhook URL.",
        )
        print("\nERROR: Instagram post failed — webhook did not return success.")
        sys.exit(1)


if __name__ == "__main__":
    main()
