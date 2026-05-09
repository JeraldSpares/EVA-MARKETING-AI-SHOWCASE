# -*- coding: utf-8 -*-
"""
Enderun Extension - Daily Facebook Auto-Poster
Picks a random image from the EXTENSION Google Drive folder,
generates a caption using Claude AI (based on the image content),
then posts to the Enderun Extension Facebook page via Zapier webhook.

Run daily: python post_to_facebook.py
Auto mode: set AUTO_POST=true environment variable
"""

import os
import sys
import io
import json
import random
import base64
import shutil
import time
import requests
from pathlib import Path
from datetime import date
import anthropic
from notifications_helper import push_notification
from drive_helper import is_cloud, download_by_name, upload_or_update
from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = None  # Remove decompression bomb limit

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Source images — only picks from FB_Post_Today folder (your curated images)
EXTENSION_FOLDER  = r"G:\My Drive\FB_Post_Today"
STAGING_FOLDER    = r"G:\My Drive\FB_Post_Today"
ZAPIER_WEBHOOK    = "https://hooks.zapier.com/hooks/catch/27410726/uv5xa1b/"
ENDERUN_EXT_LINK  = "https://enderunextension.com/"
USED_LOG_FILE     = Path(__file__).parent / "used_images_log.json"

HASHTAGS = (
    "#EnderunExtension #EnderunColleges #BGC #McKinleyHill "
    "#ProfessionalDevelopment #LifelongLearning #UpskillPH "
    "#CulinaryArts #HospitalityPH #LearnWithEnderun"
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------

def get_all_images(folder: str) -> list:
    """Get all JPG/PNG images from FB_Post_Today folder (skip todays_post.jpg)."""
    extensions = {".jpg", ".jpeg", ".png"}
    images = []
    for path in Path(folder).iterdir():
        if path.suffix.lower() in extensions and path.is_file():
            if path.name.lower() != "todays_post.jpg":
                images.append(path)
    return images


def load_used_log() -> dict:
    if USED_LOG_FILE.exists():
        with open(USED_LOG_FILE, "r") as f:
            return json.load(f)
    return {"used": []}


def save_used_log(log: dict):
    with open(USED_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def pick_random_image(images: list, used_log: dict) -> Path:
    """Pick a random synced image, avoiding recently used ones."""
    used = set(used_log.get("used", []))
    available = [img for img in images if str(img) not in used]

    if not available:
        print("All images used - resetting the list and starting over.")
        used_log["used"] = []
        available = images

    # Shuffle and find the first one that is locally synced and readable
    random.shuffle(available)
    for candidate in available:
        if is_file_synced(candidate):
            try:
                Image.MAX_IMAGE_PIXELS = None
                img = Image.open(candidate)
                img.verify()
                return candidate
            except Exception:
                continue

    raise RuntimeError("No usable synced images found.")


def is_file_synced(image_path: Path) -> bool:
    """Check if the Google Drive file is fully synced locally (not cloud-only)."""
    try:
        size = image_path.stat().st_size
        if size < 1000:  # Skip suspiciously small images
            return False
        # Read the entire file to confirm it's fully available locally
        with open(image_path, "rb") as f:
            data = f.read()
        return len(data) > 1000
    except (OSError, IOError, PermissionError):
        return False


def image_to_base64(image_path: Path) -> str:
    """Convert image to base64, resizing if it exceeds Claude's 5MB limit."""
    MAX_BYTES = 4 * 1024 * 1024  # 4MB to be safe

    with open(image_path, "rb") as f:
        raw = f.read()

    if len(raw) <= MAX_BYTES:
        return base64.standard_b64encode(raw).decode("utf-8")

    # Resize image to fit under the limit
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= MAX_BYTES or quality < 30:
            break
        # Also scale down dimensions if quality alone doesn't help
        if quality <= 50:
            w, h = img.size
            img = img.resize((int(w * 0.75), int(h * 0.75)), Image.LANCZOS)
        quality -= 10

    return base64.standard_b64encode(data).decode("utf-8")


def get_media_type(image_path: Path) -> str:
    return "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"


def generate_caption(image_path: Path) -> str:
    """Use Claude Vision to analyze the image and write a Facebook caption."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today  = date.today().strftime("%B %d, %Y")

    prompt = (
        f"You are the Social Media Manager of Enderun Extension - the professional "
        f"and continuing education arm of Enderun Colleges, located in McKinley Hill, "
        f"BGC, Taguig, Philippines.\n\n"
        f"Today is {today}. Write a Facebook post caption for this image.\n\n"
        f"BRAND VOICE:\n"
        f"- Aspirational but warm - world-class yet approachable\n"
        f"- Proud of Filipino talent and excellence\n"
        f"- Professional development focus - upskilling, career growth\n"
        f"- Write in pure English only — no Tagalog or Taglish\n"
        f"- Never corporate or stiff\n\n"
        f"CAPTION RULES:\n"
        f"- 3 to 5 short paragraphs maximum\n"
        f"- Start with a compelling hook (question, bold statement, or relatable moment)\n"
        f"- Connect the image to a learning opportunity or career benefit at Enderun Extension\n"
        f"- End with a clear call to action (visit our website, enroll now, etc.)\n"
        f"- Do NOT include hashtags (added separately)\n"
        f"- Do NOT include the website URL (added separately)\n"
        f"- Do NOT say 'Image shows...' - write naturally\n\n"
        f"Write ONLY the caption text. Nothing else."
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
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

    return response.content[0].text.strip()


def stage_image_to_my_drive(image_path: Path) -> str:
    """Copy chosen image to todays_post.jpg so Zapier always finds the same filename."""
    dest = Path(STAGING_FOLDER) / "todays_post.jpg"
    shutil.copy2(image_path, dest)
    print(f"Staged image to: {dest}")
    # Wait for Google Drive to sync the file before sending webhook
    time.sleep(5)
    return dest.name


def post_to_facebook(image_path: Path, caption: str, image_url: str = None) -> bool:
    """Send post to Zapier webhook -> Facebook."""
    full_message = f"{caption}\n\n{ENDERUN_EXT_LINK}\n\n{HASHTAGS}"

    payload = {
        "caption":         caption,
        "full_message":    full_message,
        "hashtags":        HASHTAGS,
        "link_url":        ENDERUN_EXT_LINK,
        "image_url":       image_url or "",   # public Drive URL for 2-step Zap
        "image_filename":  "todays_post.jpg",
        "image_folder":    "FB_Post_Today",
        "image_full_path": str(image_path),
    }

    print("\nSending to Zapier webhook...")
    response = requests.post(ZAPIER_WEBHOOK, json=payload, timeout=15)

    if response.status_code == 200:
        resp_json = response.json()
        if resp_json.get("status") == "success":
            print("Posted successfully to Facebook!")
        else:
            print(f"Zapier response: {resp_json}")
        return True  # Zapier returns 200 even with "queued" or other status keys
    else:
        print(f"Webhook error: {response.status_code} - {response.text}")
        return False


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv
    print("=" * 60)
    print("  Enderun Extension - Daily Facebook Auto-Poster")
    if dry_run:
        print("  *** DRY RUN MODE — will NOT post to Facebook or update used_images_log ***")
    print("=" * 60)

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        print('Run: setx ANTHROPIC_API_KEY "sk-ant-..."')
        return

    # Check for dashboard override (set by composer or AI chat tool)
    override_image   = os.environ.get("OVERRIDE_IMAGE", "").strip()
    override_caption = os.environ.get("OVERRIDE_CAPTION", "").strip()

    # 1. Check posting schedule first (skipped when override image is set)
    today_str = date.today().isoformat()
    schedule_file = Path(__file__).parent / "posting_schedule.json"
    chosen_image = None

    if override_image:
        chosen_image = override_image
        print(f"\nUsing override image from dashboard: {override_image}")
    else:
        if schedule_file.exists():
            with open(schedule_file, "r") as f:
                schedule = json.load(f).get("schedule", {})
            if today_str in schedule:
                scheduled_filename = schedule[today_str]
                if is_cloud():
                    chosen_image = scheduled_filename
                    print(f"\nUsing scheduled image for {today_str}: {scheduled_filename}")
                else:
                    scheduled_path = Path(EXTENSION_FOLDER) / scheduled_filename
                    if scheduled_path.exists() and is_file_synced(scheduled_path):
                        chosen_image = scheduled_path
                        print(f"\nUsing scheduled image for {today_str}: {scheduled_filename}")

    # 2. Fall back to random unused image if no schedule match
    used_log = load_used_log()
    if not chosen_image:
        if is_cloud():
            # Cloud: use first available image in schedule
            if schedule_file.exists():
                with open(schedule_file) as f:
                    sched = json.load(f).get("schedule", {})
                for k in sorted(sched.keys()):
                    chosen_image = sched[k]
                    print(f"\nNo scheduled image today — using: {chosen_image}")
                    break
            if not chosen_image:
                print("No images in schedule. Exiting.")
                return
        else:
            print(f"\nScanning folder for random image...")
            images = get_all_images(EXTENSION_FOLDER)
            print(f"Found {len(images)} usable images.")
            if not images:
                print("No images found. Check the folder path.")
                return
            chosen_image = pick_random_image(images, used_log)

    if is_cloud():
        img_filename = chosen_image if isinstance(chosen_image, str) else chosen_image.name
        print(f"\nSelected image : {img_filename}")
        print(f"Downloading from Google Drive...")
        cloud_img_bytes = download_by_name(img_filename)
        cloud_img_path  = Path("/tmp") / img_filename
        cloud_img_path.write_bytes(cloud_img_bytes)
        chosen_image = cloud_img_path
    else:
        print(f"\nSelected image : {chosen_image.name}")
        print(f"From folder    : {chosen_image.parent.name}")

    # 3. Generate caption (use override if provided, else Claude Vision)
    if override_caption:
        caption = override_caption
        print("\nUsing override caption from environment.")
    else:
        print("\nGenerating caption with Claude AI (analyzing image)...")
        caption = generate_caption(chosen_image)
    override_hashtags = os.environ.get("OVERRIDE_HASHTAGS", "").strip()
    if override_hashtags:
        global HASHTAGS
        HASHTAGS = override_hashtags

    print("\n" + "=" * 60)
    print("CAPTION PREVIEW")
    print("=" * 60)
    print(caption)
    print(f"\nLINK: {ENDERUN_EXT_LINK}")
    print(f"\nHASHTAGS: {HASHTAGS}")
    print("=" * 60)

    # 4. Confirm before posting (skip if AUTO_POST=true or dry_run)
    auto_post = os.environ.get("AUTO_POST", "false").lower() == "true"
    if not auto_post and not dry_run:
        confirm = input("\nPost this to Facebook? (y/n): ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    if dry_run:
        print("\n[DRY RUN] Skipping Google Drive upload and Facebook webhook.")
        print(f"[DRY RUN] Would have posted: {chosen_image.name}")
        print(f"[DRY RUN] Caption preview:\n{caption}")
        print("\n[DRY RUN] Done — no changes made.")
        return

    # 5. Upload image to Drive and get public URL for Zapier
    image_url = None
    if is_cloud():
        print("Uploading todays_post.jpg to Google Drive...")
        from drive_helper import make_public_and_get_url
        file_id   = upload_or_update("todays_post.jpg", chosen_image.read_bytes())
        image_url = make_public_and_get_url(file_id)
    else:
        stage_image_to_my_drive(chosen_image)

    # 6. Post via Zapier webhook
    success = post_to_facebook(chosen_image, caption, image_url=image_url)

    # 7. Log the used image
    if success:
        used_log["used"].append(str(chosen_image))
        used_log["last_posted"] = {
            "date":     date.today().isoformat(),
            "filename": chosen_image.name,
            "folder":   chosen_image.parent.name,
        }
        save_used_log(used_log)
        print("Saved to used_images_log.json")
        push_notification(
            agent_id="facebook-post",
            level="success",
            title=f"Facebook post published",
            message=f"Posted \"{chosen_image.name}\" to Enderun Extension Facebook page.",
        )
    else:
        push_notification(
            agent_id="facebook-post",
            level="critical",
            title="Facebook post failed",
            message="Zapier webhook did not return success. Check your webhook URL and image staging folder.",
        )
        print("\nERROR: Facebook post failed — webhook did not return success.")
        sys.exit(1)

    print("\nDone!")


if __name__ == "__main__":
    main()
