# -*- coding: utf-8 -*-
"""
Enderun Extension - Daily Drip Email Sender
Reads leads from leads.csv, picks today's scheduled image,
generates personalized email copy via Claude AI,
and sends a beautifully designed HTML email to all active leads.

Run daily: python send_drip_email.py
Auto mode: set AUTO_SEND=true environment variable
"""

import os
import sys
import io
import csv
import json
import base64
import smtplib
import time
from pathlib import Path
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import anthropic
from PIL import Image
from notifications_helper import push_notification
from drive_helper import is_cloud, download_by_name

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# CONFIG — update these with your Gmail credentials
# ---------------------------------------------------------------------------

GMAIL_ADDRESS    = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS   = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")

STAGING_FOLDER   = Path(r"G:\My Drive\FB_Post_Today")
SCHEDULE_FILE    = Path(__file__).parent / "posting_schedule.json"
LEADS_FILE       = Path(__file__).parent / "leads.csv"
ENDERUN_EXT_LINK = "https://enderunextension.com/"
LOGO_PATH        = Path(__file__).parent / "assets" / "logos" / "enderun_extension_logo.png"

# ---------------------------------------------------------------------------
# EMAIL UTILITIES
# ---------------------------------------------------------------------------

def get_all_scheduled_images() -> list:
    """Return all scheduled images as an ordered list (by date).
    In cloud mode: skip exists() check — files live on Google Drive, not local disk.
    """
    images = []
    if SCHEDULE_FILE.exists():
        with open(SCHEDULE_FILE, "r") as f:
            schedule = json.load(f).get("schedule", {})
        for date_key in sorted(schedule.keys()):
            img_path = STAGING_FOLDER / schedule[date_key]
            if is_cloud():
                images.append(img_path)  # trust the schedule; file will be downloaded on demand
            elif img_path.exists():
                images.append(img_path)
    return images

def get_image_for_lead(email_count: int) -> Path:
    """Pick image for lead based on their position in the drip sequence."""
    images = get_all_scheduled_images()
    if not images:
        fallback = STAGING_FOLDER / "todays_post.jpg"
        if fallback.exists():
            return fallback
        raise FileNotFoundError("No images found in schedule. Check posting_schedule.json.")
    index = email_count % len(images)
    return images[index]


def get_image_bytes_for_lead(email_count: int) -> tuple:
    """
    Cloud-aware image loader. Returns (image_bytes, image_path_or_name).
    In cloud mode: downloads from Google Drive by filename.
    In local mode: reads from local path as before.
    """
    images = get_all_scheduled_images()
    if not images:
        raise FileNotFoundError("No images found in schedule.")
    index    = email_count % len(images)
    img_path = images[index]

    if is_cloud():
        img_bytes = download_by_name(img_path.name)
        # Write to /tmp so Claude Vision can read it
        tmp_path = Path("/tmp") / img_path.name
        tmp_path.write_bytes(img_bytes)
        return img_bytes, tmp_path
    else:
        return None, img_path  # local: caller reads from path normally


def resize_image_for_email(image_path: Path) -> bytes:
    """Resize image to max 600px wide for email, return bytes."""
    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(image_path).convert("RGB")
    max_width = 600
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def image_to_base64_for_claude(image_path: Path) -> str:
    """Prepare image for Claude Vision (max 4MB)."""
    MAX = 4 * 1024 * 1024
    Image.MAX_IMAGE_PIXELS = None
    with open(image_path, "rb") as f:
        raw = f.read()
    if len(raw) <= MAX:
        return base64.standard_b64encode(raw).decode()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    q = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q)
        raw = buf.getvalue()
        if len(raw) <= MAX or q < 30:
            break
        if q <= 50:
            w, h = img.size
            img = img.resize((int(w * 0.75), int(h * 0.75)), Image.LANCZOS)
        q -= 10
    return base64.standard_b64encode(raw).decode()


def generate_email_copy(image_path: Path, first_name: str, program_interest: str) -> dict:
    """Generate personalized email subject + body using Claude Vision."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today  = date.today().strftime("%B %d, %Y")

    prompt = (
        f"You are the Senior Email Marketing Manager of Enderun Extension — the professional "
        f"and continuing education arm of Enderun Colleges in McKinley Hill, BGC, Taguig, Philippines.\n\n"
        f"Enderun Colleges is the Philippines' premier private institution with international affiliations "
        f"with Les Roches (Top 3 globally in hospitality) and École Ducasse (founded by Alain Ducasse, France). "
        f"Enderun Extension offers TESDA-accredited short courses, WSET wine certifications, ServSafe, "
        f"culinary arts, pastry arts, hotel operations, project management, and digital marketing programs.\n\n"
        f"Today is {today}. Write a formal yet warm, highly personalized drip email for a lead named {first_name} "
        f"who is interested in {program_interest}.\n\n"
        f"The email must be inspired by the image shown — describe what the image depicts and connect it "
        f"meaningfully to a professional learning opportunity at Enderun Extension.\n\n"
        f"TONE & STYLE:\n"
        f"- Formal, professional, and credentialed — this is a world-class institution\n"
        f"- Warm and personal — never stiff or corporate\n"
        f"- Detailed and informative — give the reader real substance, not fluff\n"
        f"- Pure English only\n"
        f"- Address {first_name} by name in the first sentence\n\n"
        f"OUTPUT FORMAT (respond with valid JSON only, no markdown):\n"
        f"{{\n"
        f'  "subject": "Compelling email subject line (max 55 chars)",\n'
        f'  "preview": "Preview text shown in inbox (max 100 chars, expands on subject)",\n'
        f'  "headline": "Bold headline inside email — aspirational, max 12 words",\n'
        f'  "subheadline": "Supporting subheadline — one sentence that adds context to the headline",\n'
        f'  "body": "3 full paragraphs separated by double newlines. Para 1: Greet {first_name} personally and connect the image to a relevant insight or moment in {program_interest}. Para 2: Explain how Enderun Extension addresses this through its programs — be specific about the training, credentials, or outcomes. Mention Les Roches or École Ducasse affiliation where relevant. Para 3: Create a sense of urgency or opportunity — limited slots, upcoming enrollment, career benefit — and end with a warm invitation to take the next step.",\n'
        f'  "highlight_title": "Short title for the program highlight box (e.g. Why {program_interest} at Enderun?)",\n'
        f'  "highlight_points": ["Benefit or fact 1 (one sentence, specific)", "Benefit or fact 2 (one sentence, specific)", "Benefit or fact 3 (one sentence, specific)"],\n'
        f'  "cta_text": "Primary CTA button text (max 5 words, action-oriented)",\n'
        f'  "cta_secondary": "Secondary link text below the button (e.g. View Full Program Schedule)",\n'
        f'  "signature_line": "Closing warm line before signature (1 sentence, e.g. Looking forward to seeing you in BGC.)"\n'
        f"}}"
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_to_base64_for_claude(image_path),
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    text = response.content[0].text.strip()
    # Extract JSON from response
    start = text.find("{")
    end   = text.rfind("}") + 1
    return json.loads(text[start:end])


def build_html_email(copy: dict, first_name: str) -> str:
    """Build beautifully designed, informative, and formal branded HTML email."""

    # Build highlight points list
    highlight_points = copy.get("highlight_points", [])
    highlight_items_html = "".join(
        f"""<tr>
              <td style="padding:6px 0;vertical-align:top;width:24px;">
                <span style="display:inline-block;width:8px;height:8px;background-color:#C9A84C;
                             border-radius:50%;margin-top:6px;"></span>
              </td>
              <td style="padding:6px 0 6px 8px;font-size:14px;line-height:1.7;color:#333333;">
                {point}
              </td>
            </tr>"""
        for point in highlight_points
    )

    # Build body paragraphs
    body_paragraphs = "".join(
        f"<p style='margin:0 0 18px;font-size:16px;line-height:1.9;color:#333333;text-align:justify;'>{p.strip()}</p>"
        for p in copy.get("body", "").split("\n\n") if p.strip()
    )

    subheadline  = copy.get("subheadline", "")
    highlight_title = copy.get("highlight_title", "Why Enderun Extension?")
    cta_secondary   = copy.get("cta_secondary", "View Full Program Schedule")
    signature_line  = copy.get("signature_line", "We look forward to welcoming you to Enderun Extension.")
    today_year      = date.today().year
    today_str       = date.today().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{copy['subject']}</title>
</head>
<body style="margin:0;padding:0;background-color:#EFEFEF;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#EFEFEF;padding:36px 0;">
    <tr>
      <td align="center">
        <table width="620" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:4px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.10);">

          <!-- Top Bar -->
          <tr>
            <td style="background-color:#C9A84C;height:5px;font-size:0;line-height:0;">&nbsp;</td>
          </tr>

          <!-- Header -->
          <tr>
            <td style="background-color:#FFFFFF;padding:22px 48px 20px;border-bottom:3px solid #C9A84C;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="vertical-align:middle;">
                    <img src="cid:logo_image" height="52" alt="Enderun Extension"
                         style="display:block;height:52px;width:auto;border:0;" />
                  </td>
                  <td align="right" style="vertical-align:middle;">
                    <p style="margin:0 0 3px;font-size:10px;color:#1A2B4A;letter-spacing:0.5px;">{today_str}</p>
                    <p style="margin:0;font-size:9px;letter-spacing:1.5px;color:#8A9BB0;text-transform:uppercase;">Professional &amp; Continuing Education</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Hero Image (clickable → enderunextension.com) -->
          <tr>
            <td style="padding:0;line-height:0;">
              <a href="https://enderunextension.com" target="_blank" style="display:block;line-height:0;border:0;">
                <img src="cid:hero_image" alt="Enderun Extension Program" width="620"
                     style="display:block;width:100%;max-width:620px;height:auto;border:0;" />
              </a>
            </td>
          </tr>

          <!-- Gold Accent Bar -->
          <tr>
            <td style="background-color:#C9A84C;height:4px;font-size:0;line-height:0;">&nbsp;</td>
          </tr>

          <!-- Headline Section -->
          <tr>
            <td style="padding:40px 48px 24px;background-color:#ffffff;">
              <h1 style="margin:0 0 10px;font-size:28px;font-weight:700;color:#1A2B4A;line-height:1.3;letter-spacing:-0.3px;">
                {copy['headline']}
              </h1>
              {f'<p style="margin:0;font-size:16px;color:#C9A84C;font-weight:600;line-height:1.5;">{subheadline}</p>' if subheadline else ''}
            </td>
          </tr>

          <!-- Thin divider -->
          <tr>
            <td style="padding:0 48px;">
              <hr style="border:none;border-top:2px solid #F0EDE4;margin:0;">
            </td>
          </tr>

          <!-- Body Copy -->
          <tr>
            <td style="padding:28px 48px 8px;">
              {body_paragraphs}
            </td>
          </tr>

          <!-- Program Highlight Box -->
          <tr>
            <td style="padding:8px 48px 28px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#F8F6F0;border-left:4px solid #C9A84C;border-radius:0 4px 4px 0;padding:20px 24px;">
                <tr>
                  <td>
                    <p style="margin:0 0 14px;font-size:12px;font-weight:700;color:#1A2B4A;text-transform:uppercase;letter-spacing:2px;">
                      {highlight_title}
                    </p>
                    <table width="100%" cellpadding="0" cellspacing="0">
                      {highlight_items_html}
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Signature Line -->
          <tr>
            <td style="padding:0 48px 28px;">
              <p style="margin:0 0 20px;font-size:15px;line-height:1.7;color:#555555;font-style:italic;">
                {signature_line}
              </p>
              <p style="margin:0;font-size:15px;color:#333333;font-weight:600;">Warmly,</p>
              <p style="margin:4px 0 0;font-size:14px;color:#555555;">The Enderun Extension Team</p>
              <p style="margin:2px 0 0;font-size:13px;color:#8A9BB0;">McKinley Hill, BGC, Taguig, Metro Manila</p>
            </td>
          </tr>

          <!-- CTA Section -->
          <tr>
            <td style="padding:4px 48px 40px;text-align:center;">
              <a href="{ENDERUN_EXT_LINK}"
                 style="display:inline-block;background-color:#1A2B4A;color:#C9A84C;text-decoration:none;
                        font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
                        padding:18px 48px;border-radius:2px;">
                {copy['cta_text']}
              </a>
              <br>
              <a href="{ENDERUN_EXT_LINK}"
                 style="display:inline-block;margin-top:14px;font-size:13px;color:#C9A84C;
                        text-decoration:none;border-bottom:1px solid #C9A84C;padding-bottom:1px;">
                {cta_secondary}
              </a>
            </td>
          </tr>

          <!-- Accreditations Bar -->
          <tr>
            <td style="background-color:#F8F6F0;padding:18px 48px;border-top:1px solid #EEEEEE;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="text-align:center;">
                    <p style="margin:0;font-size:10px;letter-spacing:2px;color:#8A9BB0;text-transform:uppercase;font-weight:600;">
                      Affiliated with &nbsp;|&nbsp; Les Roches &nbsp;&bull;&nbsp; École Ducasse &nbsp;&bull;&nbsp; TESDA-Accredited &nbsp;&bull;&nbsp; WSET &nbsp;&bull;&nbsp; ServSafe
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#1A2B4A;padding:24px 48px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <p style="margin:0 0 4px;font-size:12px;color:#C9A84C;font-weight:700;letter-spacing:1px;text-transform:uppercase;">Enderun Extension</p>
                    <p style="margin:0 0 4px;font-size:11px;color:#8A9BB0;">1100 Campus Ave, McKinley Hill, BGC, Taguig, Metro Manila</p>
                    <p style="margin:0;font-size:11px;">
                      <a href="{ENDERUN_EXT_LINK}" style="color:#C9A84C;text-decoration:none;">enderunextension.com</a>
                    </p>
                  </td>
                  <td align="right" style="vertical-align:top;">
                    <p style="margin:0;font-size:10px;color:#4A5A72;line-height:1.7;">
                      You received this email because<br>you inquired about our programs.<br>
                      &copy; {today_year} Enderun Extension.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Bottom Gold Bar -->
          <tr>
            <td style="background-color:#C9A84C;height:4px;font-size:0;line-height:0;">&nbsp;</td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""


FIELDNAMES = ["first_name", "last_name", "email", "program_interest", "status", "email_count"]

def read_leads() -> list:
    """Read active leads from CSV file. Adds email_count=0 if missing."""
    leads = []
    with open(LEADS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status", "").strip().lower() == "active":
                if "email_count" not in row or row["email_count"] == "":
                    row["email_count"] = "0"
                leads.append(row)
    return leads

def increment_email_count(email: str):
    """Increment email_count for the given lead in leads.csv."""
    rows = []
    with open(LEADS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        for row in reader:
            if "email_count" not in row or row["email_count"] == "":
                row["email_count"] = "0"
            if row.get("email") == email:
                row["email_count"] = str(int(row["email_count"]) + 1)
            rows.append(row)
    # Write back with email_count column
    fields = list(existing_fields)
    if "email_count" not in fields:
        fields.append("email_count")
    with open(LEADS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def send_email(to_email: str, subject: str, html_body: str, image_bytes: bytes, logo_bytes: bytes = None) -> bool:
    """Send HTML email with embedded hero image and logo via Gmail SMTP."""
    msg = MIMEMultipart("related")
    msg["From"]    = f"Enderun Extension <{GMAIL_ADDRESS}>"
    msg["To"]      = to_email
    msg["Subject"] = subject

    # Attach HTML
    msg.attach(MIMEText(html_body, "html"))

    # Attach logo (must come before hero so CID resolves in order)
    if logo_bytes:
        logo_part = MIMEImage(logo_bytes, _subtype="png")
        logo_part.add_header("Content-ID", "<logo_image>")
        logo_part.add_header("Content-Disposition", "inline", filename="enderun_extension_logo.png")
        msg.attach(logo_part)

    # Attach embedded hero image
    img_part = MIMEImage(image_bytes, _subtype="jpeg")
    img_part.add_header("Content-ID", "<hero_image>")
    img_part.add_header("Content-Disposition", "inline", filename="hero.jpg")
    msg.attach(img_part)

    try:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
                server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
        except Exception:
            # Fallback to port 587 (STARTTLS) if 465 is blocked
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.ehlo()
                server.starttls()
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
                server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"  ERROR sending to {to_email}: {e}")
        return False


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv
    print("=" * 60)
    print("  Enderun Extension - Daily Drip Email Sender")
    if dry_run:
        print("  *** DRY RUN MODE — email_count will NOT be incremented ***")
        print(f"  *** Emails sent to {GMAIL_ADDRESS} only (not real leads) ***")
    print("=" * 60)

    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        return
    if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
        print("ERROR: GMAIL_ADDRESS or GMAIL_APP_PASS not set.")
        print("Set these in your environment variables.")
        return

    # 1. Load logo
    logo_bytes = None
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            logo_bytes = f.read()
        print(f"Logo loaded: {LOGO_PATH.name}")
    else:
        print(f"WARNING: Logo not found at {LOGO_PATH} — header will show without logo")

    # 2. Load all available images for sequence
    print(f"\nLoading image sequence from schedule...")
    all_images = get_all_scheduled_images()
    print(f"Available images in sequence: {len(all_images)}")

    # 2. Read leads
    leads = read_leads()
    print(f"Leads to email: {len(leads)}")

    if not leads:
        print("No active leads found in leads.csv")
        return

    # 3. Confirm
    auto_send = os.environ.get("AUTO_SEND", "false").lower() == "true"
    if not auto_send and not dry_run:
        confirm = input(f"\nSend email to {len(leads)} leads? (y/n): ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    # 4. Send personalized email to each lead using their unique position in the sequence
    print("\nSending emails...")
    sent_count = 0
    for lead in leads:
        first_name       = lead["first_name"]
        email            = lead["email"] if not dry_run else GMAIL_ADDRESS
        program_interest = lead.get("program_interest", "our programs")
        email_count      = int(lead.get("email_count", "0"))
        email_num        = email_count + 1  # Human-readable sequence number

        # Pick image based on this lead's position in the drip sequence
        cloud_bytes, image_path = get_image_bytes_for_lead(email_count)

        print(f"\n  [{first_name}] Email #{email_num} in sequence — Image: {image_path.name}")
        try:
            if is_cloud() and cloud_bytes:
                # Already downloaded — resize from bytes directly
                from io import BytesIO
                img = Image.open(BytesIO(cloud_bytes)).convert("RGB")
                if img.width > 600:
                    ratio = 600 / img.width
                    img = img.resize((600, int(img.height * ratio)), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=85)
                image_bytes = buf.getvalue()
            else:
                image_bytes = resize_image_for_email(image_path)
            copy = generate_email_copy(image_path, first_name, program_interest)
            html = build_html_email(copy, first_name)

            print(f"  Subject : {copy['subject']}")
            print(f"  Headline: {copy['headline']}")
            print(f"  CTA     : {copy['cta_text']}")

            success = send_email(email, copy["subject"], html, image_bytes, logo_bytes)
            if success:
                sent_count += 1
                print(f"  Sent to {email}")
                if not dry_run:
                    increment_email_count(lead["email"])  # Track that this lead got another email
                else:
                    print(f"  [DRY RUN] email_count NOT incremented for {lead['email']}")
            time.sleep(2)

        except Exception as e:
            print(f"  FAILED for {email}: {e}")

    print("\n" + "=" * 60)
    if sent_count == 0 and leads:
        push_notification(
            agent_id="drip-email",
            level="critical",
            title="Drip email failed — 0 sent",
            message="All emails failed to send. Check Claude API credits or SMTP connection.",
        )
        print("  ERROR: No emails were sent. Check logs above for details.")
        print("=" * 60)
        sys.exit(1)
    else:
        push_notification(
            agent_id="drip-email",
            level="success",
            title=f"{sent_count} drip email{'s' if sent_count != 1 else ''} sent",
            message=f"Personalized emails delivered to {', '.join(l['first_name'] for l in leads)}.",
        )
        print(f"  Done! {sent_count}/{len(leads)} emails sent.")
        print("=" * 60)


if __name__ == "__main__":
    main()
