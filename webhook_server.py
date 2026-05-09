# -*- coding: utf-8 -*-
"""
Enderun Extension - Webhook Server
Handles:
  POST /lead          — New lead from web form → appends to leads.csv → sends welcome drip email
  POST /fb-comment    — Facebook comment from Zapier → AI reply → posts reply back → adds commenter as lead

Run:  python webhook_server.py
Expose publicly via ngrok:  ngrok http 5000
Then set your Zapier webhook URL to:  https://<your-ngrok-url>/fb-comment
"""

import os
import csv
import json
import smtplib
import time
from pathlib import Path
from datetime import date
from flask import Flask, request, jsonify
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic
import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GMAIL_ADDRESS    = os.environ.get("GMAIL_ADDRESS", "eva@enderuncolleges.com")
GMAIL_APP_PASS   = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
FB_PAGE_TOKEN    = os.environ.get("FB_PAGE_TOKEN", "")   # Facebook Page Access Token
ZAPIER_REPLY_HOOK = os.environ.get("ZAPIER_REPLY_HOOK", "")  # Optional: Zapier hook to post reply

LEADS_FILE       = Path(__file__).parent / "leads.csv"
ENDERUN_EXT_LINK = "https://enderunextension.com/"
WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "")  # Simple auth token (set in .env)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def append_lead(first_name: str, last_name: str, email: str, program_interest: str) -> bool:
    """Append a new lead to leads.csv if email doesn't already exist."""
    # Check for duplicate
    if LEADS_FILE.exists():
        with open(LEADS_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("email", "").strip().lower() == email.strip().lower():
                    print(f"Lead already exists: {email}")
                    return False

    # Append new lead
    file_exists = LEADS_FILE.exists()
    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["first_name", "last_name", "email", "program_interest", "status"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "first_name":       first_name.strip(),
            "last_name":        last_name.strip(),
            "email":            email.strip().lower(),
            "program_interest": program_interest.strip(),
            "status":           "active"
        })
    print(f"New lead added: {first_name} {last_name} <{email}>")
    return True


def build_welcome_email_html(first_name: str, program_interest: str) -> tuple:
    """Build welcome email HTML for a new lead."""
    subject  = f"Welcome to Enderun Extension, {first_name}!"
    headline = "Your Journey to World-Class Learning Starts Here"
    body = (
        f"Hi {first_name},\n\n"
        f"Thank you for your interest in {program_interest} at Enderun Extension! "
        f"We are thrilled to have you on board.\n\n"
        f"Enderun Extension is the professional and continuing education arm of Enderun Colleges — "
        f"the only Philippine school with a direct partnership with Les Roches, ranked Top 3 globally "
        f"in hospitality education.\n\n"
        f"Our team will be in touch soon to share more about our upcoming programs, open houses, and how "
        f"you can take the next step toward a world-class education. In the meantime, explore our programs "
        f"and see what Enderun Extension has to offer."
    )
    cta_text = "Explore Programs"

    paragraphs = "".join(
        f"<p style='margin:0 0 16px;'>{p.strip()}</p>"
        for p in body.split("\n\n") if p.strip()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#F4F4F4;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#F4F4F4;padding:30px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:#1A2B4A;padding:28px 40px;text-align:center;">
              <p style="margin:0;font-size:11px;letter-spacing:3px;color:#C9A84C;text-transform:uppercase;font-weight:600;">Enderun Extension</p>
              <p style="margin:6px 0 0;font-size:22px;color:#ffffff;font-weight:700;letter-spacing:0.5px;">World-Class Learning. Filipino Heart.</p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#C9A84C;height:4px;font-size:0;line-height:0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:40px 40px 20px;">
              <h1 style="margin:0 0 20px;font-size:26px;font-weight:700;color:#1A2B4A;line-height:1.3;">{headline}</h1>
              <div style="font-size:16px;line-height:1.8;color:#444444;">{paragraphs}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:10px 40px 40px;text-align:center;">
              <a href="{ENDERUN_EXT_LINK}"
                 style="display:inline-block;background-color:#C9A84C;color:#1A2B4A;text-decoration:none;
                        font-size:15px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                        padding:16px 40px;border-radius:4px;">
                {cta_text}
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 40px;">
              <hr style="border:none;border-top:1px solid #EEEEEE;margin:0;">
            </td>
          </tr>
          <tr>
            <td style="padding:28px 40px;text-align:center;">
              <p style="margin:0 0 8px;font-size:13px;color:#888888;">Enderun Extension | McKinley Hill, BGC, Taguig, Metro Manila</p>
              <p style="margin:0 0 8px;font-size:13px;color:#888888;">
                <a href="{ENDERUN_EXT_LINK}" style="color:#C9A84C;text-decoration:none;">enderunextension.com</a>
              </p>
              <p style="margin:12px 0 0;font-size:11px;color:#BBBBBB;">
                You are receiving this email because you inquired about our programs.<br>
                &copy; {date.today().year} Enderun Extension. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return subject, html


def send_welcome_email(to_email: str, first_name: str, program_interest: str):
    """Send welcome email to a new lead."""
    subject, html = build_welcome_email_html(first_name, program_interest)
    msg = MIMEMultipart("alternative")
    msg["From"]    = f"Enderun Extension <{GMAIL_ADDRESS}>"
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
        print(f"Welcome email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send welcome email to {to_email}: {e}")


def generate_fb_comment_reply(commenter_name: str, comment_text: str, post_caption: str = "") -> str:
    """Use Claude to generate a warm, on-brand reply to a Facebook comment."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    first_name = commenter_name.split()[0] if commenter_name else "there"

    prompt = (
        f"You are the Social Media Manager of Enderun Extension — the professional and continuing "
        f"education arm of Enderun Colleges in BGC, Taguig, Philippines.\n\n"
        f"Someone named {commenter_name} commented on your Facebook post:\n"
        f'Comment: "{comment_text}"\n'
        + (f'Post context: "{post_caption}"\n' if post_caption else "") +
        f"\nWrite a short, warm, personalized reply (2-4 sentences max). Rules:\n"
        f"- Address them by first name ({first_name})\n"
        f"- Be friendly and enthusiastic, never corporate\n"
        f"- If they are asking about a program, briefly mention it and invite them to learn more or DM you\n"
        f"- If it is a compliment, thank them warmly and invite them to explore\n"
        f"- Always end with a soft CTA (e.g., 'Feel free to DM us!' or 'Check the link in our bio!')\n"
        f"- Pure English only\n"
        f"- Max 60 words\n"
        f"- Do NOT use hashtags\n"
        f"- Do NOT start with 'Hi' alone — be more creative\n\n"
        f"Reply only with the comment text, no quotes, no labels."
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def post_fb_reply(comment_id: str, reply_text: str) -> bool:
    """Post a reply to a Facebook comment using the Graph API."""
    if not FB_PAGE_TOKEN:
        print("FB_PAGE_TOKEN not set — cannot post reply via Graph API.")
        return False
    url = f"https://graph.facebook.com/v19.0/{comment_id}/comments"
    resp = requests.post(url, data={"message": reply_text, "access_token": FB_PAGE_TOKEN})
    if resp.status_code == 200:
        print(f"Reply posted to comment {comment_id}")
        return True
    else:
        print(f"Failed to post FB reply: {resp.text}")
        return False


def post_reply_via_zapier(comment_id: str, reply_text: str) -> bool:
    """Alternative: send reply back to Zapier which posts it to Facebook."""
    if not ZAPIER_REPLY_HOOK:
        return False
    resp = requests.post(ZAPIER_REPLY_HOOK, json={
        "comment_id": comment_id,
        "reply_text": reply_text
    })
    return resp.status_code == 200

# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Enderun Extension Webhook Server"})


@app.route("/lead", methods=["POST"])
def new_lead():
    """
    Receive a new lead from a web form or any external source.
    Expected JSON body:
      {
        "secret": "<your WEBHOOK_SECRET>",
        "first_name": "Maria",
        "last_name": "Santos",
        "email": "maria@example.com",
        "program_interest": "Culinary Arts"
      }
    """
    data = request.get_json(silent=True) or {}

    # Auth check
    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    first_name       = data.get("first_name", "").strip()
    last_name        = data.get("last_name", "").strip()
    email            = data.get("email", "").strip()
    program_interest = data.get("program_interest", "our programs").strip()

    if not first_name or not email:
        return jsonify({"error": "first_name and email are required"}), 400

    # Add to CSV
    is_new = append_lead(first_name, last_name, email, program_interest)

    # Send welcome email only for new leads
    if is_new and GMAIL_ADDRESS and GMAIL_APP_PASS:
        send_welcome_email(email, first_name, program_interest)

    return jsonify({
        "status": "ok",
        "new_lead": is_new,
        "message": f"Lead {'added and welcome email sent' if is_new else 'already exists'}."
    })


@app.route("/fb-comment", methods=["POST"])
def fb_comment():
    """
    Receive a Facebook comment from Zapier.
    Zapier sends this when a new comment appears on the Enderun Extension Facebook page.
    Expected JSON body (Zapier maps these fields):
      {
        "secret": "<your WEBHOOK_SECRET>",
        "comment_id": "123456789_987654321",
        "commenter_name": "Juan dela Cruz",
        "commenter_email": "",           (usually empty from FB)
        "comment_text": "How do I enroll?",
        "post_caption": "Join our open house..."
      }
    """
    data = request.get_json(silent=True) or {}

    # Auth check
    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    comment_id      = data.get("comment_id", "")
    commenter_name  = data.get("commenter_name", "there")
    commenter_email = data.get("commenter_email", "").strip()
    comment_text    = data.get("comment_text", "")
    post_caption    = data.get("post_caption", "")

    if not comment_text:
        return jsonify({"error": "comment_text is required"}), 400

    # 1. Generate AI reply
    reply_text = ""
    if ANTHROPIC_KEY:
        try:
            reply_text = generate_fb_comment_reply(commenter_name, comment_text, post_caption)
            print(f"Generated reply for {commenter_name}: {reply_text[:60]}...")
        except Exception as e:
            print(f"Failed to generate reply: {e}")
            reply_text = (
                f"Thank you for your comment! We would love to tell you more about "
                f"our programs at Enderun Extension. Feel free to DM us or visit "
                f"{ENDERUN_EXT_LINK} to learn more!"
            )

    # 2. Post reply to Facebook
    reply_posted = False
    if comment_id and reply_text:
        # Try Graph API first, fall back to Zapier hook
        if FB_PAGE_TOKEN:
            reply_posted = post_fb_reply(comment_id, reply_text)
        elif ZAPIER_REPLY_HOOK:
            reply_posted = post_reply_via_zapier(comment_id, reply_text)

    # 3. Add commenter as lead (if email is available)
    lead_added = False
    if commenter_email:
        first_name = commenter_name.split()[0] if commenter_name else "Friend"
        last_name  = " ".join(commenter_name.split()[1:]) if len(commenter_name.split()) > 1 else ""
        lead_added = append_lead(first_name, last_name, commenter_email, "Inquired via Facebook")
        if lead_added and GMAIL_ADDRESS and GMAIL_APP_PASS:
            send_welcome_email(commenter_email, first_name, "Inquired via Facebook")

    return jsonify({
        "status":       "ok",
        "reply_text":   reply_text,
        "reply_posted": reply_posted,
        "lead_added":   lead_added
    })


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Enderun Extension - Webhook Server")
    print("=" * 60)
    print(f"  Leads file : {LEADS_FILE}")
    print(f"  Gmail      : {GMAIL_ADDRESS}")
    print(f"  Claude     : {'connected' if ANTHROPIC_KEY else 'NOT SET'}")
    print(f"  FB Token   : {'set' if FB_PAGE_TOKEN else 'not set (will use Zapier hook)'}")
    print()
    print("  Endpoints:")
    print("    GET  /health       — health check")
    print("    POST /lead         — new lead from form")
    print("    POST /fb-comment   — Facebook comment from Zapier")
    print()
    print("  To expose publicly: ngrok http 5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
