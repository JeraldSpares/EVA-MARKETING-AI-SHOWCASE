# -*- coding: utf-8 -*-
"""
Cold Lead Re-engagement Mailer
Runs weekly (Monday 6AM PHT via GitHub Actions).
Finds active leads with email_count < 5 (Cold score) and sends a
fresh-angle re-engagement email — different subject, different tone, no image.
Does NOT increment email_count so it doesn't interfere with the main drip sequence.
"""

import os, csv, json, smtplib, io, base64
from pathlib import Path
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import anthropic
from drive_helper import is_cloud
from notifications_helper import push_notification

GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
LEADS_FILE     = Path(__file__).parent / "leads.csv"
LOGO_PATH      = Path(__file__).parent / "assets" / "logos" / "enderun_extension_logo.png"
ENDERUN_LINK   = "https://enderunextension.com/"
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID", "")
BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")

def telegram_notify(msg: str):
    if not BOT_TOKEN:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass

def load_leads() -> list:
    if is_cloud():
        import requests as req
        pat  = os.environ.get("GITHUB_PAT", "")
        repo = os.environ.get("GITHUB_REPO", "")
        r = req.get(
            f"https://api.github.com/repos/{repo}/contents/leads.csv",
            headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"]).decode("utf-8", errors="replace")
            return list(csv.DictReader(io.StringIO(content)))
        return []
    if LEADS_FILE.exists():
        with open(LEADS_FILE, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    return []

def generate_reengagement_copy(first_name: str, program: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today  = date.today().strftime("%B %d, %Y")
    prompt = (
        f"You are the Senior Email Marketing Manager of Enderun Extension — the professional "
        f"and continuing education arm of Enderun Colleges in McKinley Hill, BGC, Philippines.\n\n"
        f"Today is {today}. Write a re-engagement email for {first_name}, who showed interest in "
        f"{program} but hasn't responded to our recent emails.\n\n"
        f"TONE: Warm, human, no pressure. Acknowledge we haven't talked in a while. "
        f"Ask a genuine question. Make it feel personal, not automated.\n"
        f"Do NOT use a promotional image. This should feel like a personal note from the team.\n\n"
        f"OUTPUT FORMAT (valid JSON only, no markdown):\n"
        f'{{"subject":"Subject line (max 50 chars, feel personal not promotional)",'
        f'"preview":"Preview text (max 90 chars)",'
        f'"headline":"Short warm headline (max 10 words)",'
        f'"body":"2 short paragraphs. Para 1: Acknowledge the silence warmly, check in on {first_name}. '
        f'Para 2: Share one specific, genuinely useful thing about {program} at Enderun — a fact, an outcome, a story. '
        f'End with a soft open question, not a hard CTA.",'
        f'"cta_text":"Soft CTA (e.g. See the schedule, Chat with us)",'
        f'"signature_line":"Warm closing (1 sentence)"}}'
    )
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    text  = resp.content[0].text.strip()
    start = text.find("{"); end = text.rfind("}") + 1
    return json.loads(text[start:end])

def build_reengagement_html(copy: dict, first_name: str) -> str:
    body_html = "".join(
        f"<p style='margin:0 0 16px;font-size:15px;line-height:1.8;color:#444444;'>{p.strip()}</p>"
        for p in copy.get("body", "").split("\n\n") if p.strip()
    )
    today_year = date.today().year
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#EFEFEF;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#EFEFEF;padding:36px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:4px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.09);">
      <tr><td style="background:#C9A84C;height:5px;font-size:0;">&nbsp;</td></tr>
      <tr><td style="padding:28px 48px 20px;border-bottom:2px solid #C9A84C;">
        <img src="cid:logo_image" height="46" alt="Enderun Extension" style="display:block;height:46px;"/>
      </td></tr>
      <tr><td style="padding:36px 48px 12px;">
        <h2 style="margin:0 0 8px;font-size:22px;color:#2C2C2C;font-weight:700;">{copy.get("headline","")}</h2>
        <p style="margin:0 0 24px;font-size:13px;color:#888;">Hi {first_name} —</p>
        {body_html}
        <table cellpadding="0" cellspacing="0" style="margin:28px 0;">
          <tr><td style="background:#C9A84C;border-radius:3px;padding:12px 28px;">
            <a href="{ENDERUN_LINK}" style="color:#fff;font-size:14px;font-weight:600;text-decoration:none;">{copy.get("cta_text","See What's Coming Up")}</a>
          </td></tr>
        </table>
        <p style="font-size:14px;color:#555;line-height:1.7;">{copy.get("signature_line","")}</p>
        <p style="font-size:14px;color:#555;margin-top:8px;">The Enderun Extension Team</p>
      </td></tr>
      <tr><td style="background:#F9F6EF;padding:20px 48px;border-top:1px solid #E8E0D0;">
        <p style="margin:0;font-size:11px;color:#999;line-height:1.6;text-align:center;">
          Enderun Extension · McKinley Hill, BGC, Taguig · {ENDERUN_LINK}<br>
          &copy; {today_year} Enderun Colleges. All rights reserved.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

def send_reengagement_email(lead: dict, copy: dict, html: str) -> bool:
    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = copy["subject"]
        msg["From"]    = f"Enderun Extension <{GMAIL_ADDRESS}>"
        msg["To"]      = lead["email"]

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(copy.get("body",""), "plain"))
        alt.attach(MIMEText(html, "html"))
        msg.attach(alt)

        if LOGO_PATH.exists():
            with open(LOGO_PATH, "rb") as f:
                img = MIMEImage(f.read())
                img.add_header("Content-ID", "<logo_image>")
                img.add_header("Content-Disposition", "inline")
                msg.attach(img)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.sendmail(GMAIL_ADDRESS, lead["email"], msg.as_string())
        return True
    except Exception as e:
        print(f"  ✗ Failed {lead.get('email')}: {e}")
        return False

def main():
    print("=== Cold Lead Re-engagement ===")
    leads = load_leads()
    cold  = [
        l for l in leads
        if l.get("status","").lower() == "active"
        and int(l.get("email_count", 0) or 0) < 5
    ]
    print(f"Found {len(cold)} cold leads")
    if not cold:
        telegram_notify("🧊 Cold Lead Re-engagement: No cold leads found — all good!")
        return

    sent = 0
    for lead in cold:
        first_name = (lead.get("name","") or "").split()[0] or "there"
        program    = lead.get("program","General Inquiry") or "General Inquiry"
        email      = lead.get("email","").strip()
        if not email:
            continue
        print(f"  Sending to {first_name} ({email}) — {program}...")
        try:
            copy = generate_reengagement_copy(first_name, program)
            html = build_reengagement_html(copy, first_name)
            if send_reengagement_email(lead, copy, html):
                print(f"  ✓ Sent to {email}")
                sent += 1
        except Exception as e:
            print(f"  ✗ Error for {email}: {e}")

    summary = f"🧊 <b>Cold Lead Re-engagement Done</b>\n{sent}/{len(cold)} re-engagement emails sent to cold leads."
    telegram_notify(summary)
    push_notification("Cold Re-engagement", f"{sent}/{len(cold)} emails sent", "info")
    print(f"\nDone: {sent}/{len(cold)} emails sent.")

if __name__ == "__main__":
    main()
