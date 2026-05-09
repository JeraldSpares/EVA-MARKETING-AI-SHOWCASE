# -*- coding: utf-8 -*-
"""
check_preview_reply.py
======================
Checks Gmail for replies to the weekly campaign preview email.
- Reply says "approved"     → sends confirmation, marks state as approved
- Reply has change requests → re-generates PDF, sends updated preview
- Reply is unclear          → sends clarification request

Runs via GitHub Actions: Monday 9:00 AM PHT (1:00 AM UTC)
"""

import email
import imaplib
import json
import os
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from pathlib import Path

import anthropic
import requests

sys.stdout.reconfigure(encoding="utf-8")

PHT            = timezone(timedelta(hours=8))
GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

BASE_DIR   = Path(__file__).parent
STATE_FILE = BASE_DIR / "preview_state.json"
RECIPIENTS = ["eva@enderuncolleges.com"]

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def notify_telegram(text: str):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": text},
                timeout=10,
            )
        except Exception:
            pass


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ─────────────────────────────────────────────────────────────
# IMAP — find unread reply to preview email
# ─────────────────────────────────────────────────────────────

def find_reply(subject: str, already_processed: list = None) -> tuple:
    """
    Search Gmail INBOX for a reply to the preview email sent in the last 10 days.
    Does NOT require the email to be unread — searches all mail so read replies
    are still caught. Skips UIDs already processed (passed in already_processed).
    Returns (sender, body_text, uid_str) or (None, None, None).
    """
    already_processed = already_processed or []
    since_date = (datetime.now(PHT) - timedelta(days=10)).strftime("%d-%b-%Y")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        mail.select("INBOX")

        _, uids = mail.search(None, f'SINCE "{since_date}" SUBJECT "Weekly Campaign Preview"')
        if not uids or not uids[0]:
            mail.close()
            mail.logout()
            return None, None, None

        for uid in reversed(uids[0].split()):  # most recent first
            uid_str = uid.decode()
            if uid_str in already_processed:
                continue

            _, data = mail.fetch(uid, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            msg_subject = msg.get("Subject", "")
            sender      = msg.get("From", "")

            # Must be a reply (has "Re:") and from one of our recipients
            if "Re:" not in msg_subject:
                continue
            if not any(r.lower() in sender.lower() for r in RECIPIENTS):
                continue

            # Extract plain-text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                        except Exception:
                            pass
            else:
                try:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    pass

            # Strip quoted text (lines starting with ">")
            clean = "\n".join(l for l in body.splitlines() if not l.startswith(">")).strip()

            mail.close()
            mail.logout()
            return sender, clean, uid_str

        mail.close()
        mail.logout()
        return None, None, None

    except Exception as e:
        print(f"  IMAP error: {e}")
        return None, None, None


def mark_as_read(uid: str):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        mail.select("INBOX")
        mail.store(uid, "+FLAGS", "\\Seen")
        mail.close()
        mail.logout()
    except Exception as e:
        print(f"  Could not mark as read: {e}")


# ─────────────────────────────────────────────────────────────
# CLAUDE — classify reply
# ─────────────────────────────────────────────────────────────

def classify_reply(body: str) -> dict:
    """Returns {"decision": "approved"|"changes"|"unclear", "summary": str, "changes": str}"""
    if not ANTHROPIC_KEY:
        low = body.lower()
        if any(w in low for w in ["approved", "approve", "looks good", "good to go", "ok", "okay", "lgtm", "go ahead"]):
            return {"decision": "approved", "summary": "Approved by keyword match.", "changes": ""}
        return {"decision": "unclear", "summary": "No ANTHROPIC_API_KEY set.", "changes": ""}

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = f"""You are reading an email reply from the Enderun Colleges marketing manager regarding a weekly campaign preview PDF.

Reply text:
\"\"\"
{body[:2000]}
\"\"\"

Classify the reply into exactly ONE of:
- "approved" — the manager is happy with the preview as-is (e.g. "approved", "ok", "looks good", "go ahead", "no changes", etc.)
- "changes" — the manager wants specific changes to captions, scheduling, tone, or content
- "unclear" — the reply is ambiguous or not related to approving/changing the preview

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "decision": "approved" | "changes" | "unclear",
  "summary": "One sentence summary of what they said.",
  "changes": "If decision is changes: a concise bullet list of the exact changes requested. Otherwise empty string."
}}"""

    try:
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(resp.content[0].text.strip())
    except Exception as e:
        print(f"  Claude classify error: {e}")
        return {"decision": "unclear", "summary": str(e), "changes": ""}


# ─────────────────────────────────────────────────────────────
# EMAIL REPLY SENDER
# ─────────────────────────────────────────────────────────────

def send_reply(to: str, subject: str, in_reply_to: str,
               body_html: str, pdf_bytes: bytes = None, pdf_filename: str = None) -> str:
    """Send a reply in the same email thread. Returns new Message-ID."""
    new_msg_id = make_msgid(domain="enderun.ai")
    reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"

    msg = MIMEMultipart("mixed")
    msg["From"]        = f"Enderun Marketing AI <{GMAIL_ADDRESS}>"
    msg["To"]          = to
    msg["Subject"]     = reply_subject
    msg["Message-ID"]  = new_msg_id
    msg["In-Reply-To"] = in_reply_to
    msg["References"]  = in_reply_to

    msg.attach(MIMEText(body_html, "html"))

    if pdf_bytes and pdf_filename:
        pdf_part = MIMEBase("application", "pdf")
        pdf_part.set_payload(pdf_bytes)
        encoders.encode_base64(pdf_part)
        pdf_part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(pdf_part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        server.sendmail(GMAIL_ADDRESS, to, msg.as_string())

    return new_msg_id


# ─────────────────────────────────────────────────────────────
# EMAIL BODY TEMPLATES
# ─────────────────────────────────────────────────────────────

def _email_wrapper(header_title: str, body_inner: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F4F0EB;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F0EB;padding:24px 0;">
  <tr><td align="center">
    <table width="620" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>
      <tr><td style="background:#5C3D2E;padding:20px 36px;">
        <p style="margin:0;font-size:10px;letter-spacing:3px;color:#C9A84C;text-transform:uppercase;font-weight:700;">
          Enderun Marketing AI</p>
        <p style="margin:4px 0 0;font-size:17px;color:#fff;font-weight:700;">{header_title}</p>
      </td></tr>
      <tr><td style="background:#C9A84C;height:3px;font-size:0;">&nbsp;</td></tr>
      <tr><td style="padding:28px 36px;">{body_inner}</td></tr>
      <tr><td style="background:#FAF7F2;padding:14px 36px;border-top:1px solid #E8DDD0;text-align:center;">
        <p style="margin:0;font-size:11px;color:#8B6349;">
          Enderun Marketing AI &bull; enderunextension.com</p>
      </td></tr>
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def send_approval_notification(week_label: str):
    """Send a standalone notification email when the preview is approved."""
    msg = MIMEMultipart("mixed")
    msg["From"]    = f"Enderun Marketing AI <{GMAIL_ADDRESS}>"
    msg["To"]      = GMAIL_ADDRESS
    msg["Subject"] = f"✅ Weekly Preview Approved — {week_label}"
    body = _email_wrapper(
        "Campaign Preview Approved ✅",
        f"""<p style="margin:0 0 16px;font-size:15px;color:#2C1810;line-height:1.7;">
          Your weekly campaign preview for <strong>{week_label}</strong> has been
          <strong>approved</strong> and is locked in.
        </p>
        <p style="margin:0 0 12px;font-size:13px;color:#5C3D2E;line-height:1.6;">
          All daily automations will run at <strong>8:00 AM PHT</strong> as scheduled:
        </p>
        <ul style="margin:0;padding-left:20px;font-size:13px;color:#5C3D2E;line-height:2.2;">
          <li>📘 Facebook post — auto-published via Zapier</li>
          <li>📸 Instagram post — auto-published via Zapier</li>
          <li>📧 Drip emails — sent to all active leads</li>
        </ul>
        <p style="margin:16px 0 0;font-size:12px;color:#8B6349;">
          No further action needed. Have a great week! 🎉
        </p>"""
    )
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())


def html_approved(week_label: str) -> str:
    return _email_wrapper(
        "Campaign Preview — Approved ✓",
        f"""<p style="margin:0 0 16px;font-size:15px;color:#2C1810;line-height:1.7;">
          ✅ Got it! The weekly campaign preview for <strong>{week_label}</strong> is <strong>approved</strong>.
        </p>
        <p style="margin:0;font-size:13px;color:#8B6349;line-height:1.6;">
          All automations run at <strong>8:00 AM PHT</strong> each day via GitHub Actions — no further action needed.
        </p>"""
    )


def html_updated(week_label: str, changes_summary: str, version: int) -> str:
    changes_escaped = changes_summary.replace("<", "&lt;").replace(">", "&gt;")
    return _email_wrapper(
        f"Updated Campaign Preview (v{version})",
        f"""<p style="margin:0 0 12px;font-size:14px;color:#2C1810;line-height:1.7;">
          I've updated the preview for <strong>{week_label}</strong> based on your feedback.
          The revised PDF is attached.
        </p>
        <div style="background:#FAF7F2;border-left:4px solid #C9A84C;padding:12px 16px;
                    margin:16px 0;border-radius:0 6px 6px 0;">
          <p style="margin:0 0 6px;font-size:11px;font-weight:700;color:#5C3D2E;
                    text-transform:uppercase;letter-spacing:1px;">Changes Applied</p>
          <p style="margin:0;font-size:13px;color:#5C3D2E;line-height:1.6;
                    white-space:pre-wrap;">{changes_escaped}</p>
        </div>
        <p style="margin:16px 0 0;font-size:13px;color:#8B6349;line-height:1.6;">
          Reply <strong>"approved"</strong> to confirm, or describe any remaining changes.
        </p>"""
    )


def html_unclear(week_label: str) -> str:
    return _email_wrapper(
        "Weekly Campaign Preview — Clarification Needed",
        f"""<p style="margin:0 0 12px;font-size:14px;color:#2C1810;line-height:1.7;">
          Thanks for your reply about the preview for <strong>{week_label}</strong>.
        </p>
        <p style="margin:0 0 12px;font-size:13px;color:#5C3D2E;line-height:1.6;">
          I wasn't sure how to act on your message. Could you reply with one of the following?
        </p>
        <ul style="margin:0;padding-left:20px;font-size:13px;color:#5C3D2E;line-height:2.2;">
          <li>Reply <strong>"approved"</strong> to confirm the preview as-is</li>
          <li>Describe specific changes — I'll regenerate the PDF immediately</li>
        </ul>"""
    )


# ─────────────────────────────────────────────────────────────
# PDF REGENERATION
# ─────────────────────────────────────────────────────────────

def regenerate_pdf(changes_text: str) -> bytes:
    """Re-build the preview PDF, injecting change context into caption generation."""
    os.environ["CAPTION_CONTEXT"] = changes_text
    try:
        # Import fresh to pick up env var
        import importlib
        import weekly_campaign_preview as wcp
        importlib.reload(wcp)

        week_dates = wcp.get_upcoming_week()
        schedule   = wcp.load_schedule()
        leads      = wcp.load_leads()
        return wcp.build_pdf(week_dates, schedule, leads)
    finally:
        os.environ.pop("CAPTION_CONTEXT", None)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Check Preview Reply")
    print(f"  {datetime.now(PHT).strftime('%B %d, %Y %H:%M PHT')}")
    print("=" * 60)

    if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
        print("  ERROR: GMAIL_ADDRESS or GMAIL_APP_PASS not set.")
        sys.exit(1)

    state = load_state()
    if not state:
        print("  No preview_state.json found. Nothing to check.")
        return

    status     = state.get("status", "")
    message_id = state.get("message_id", "")
    subject    = state.get("subject", "")
    week_label = state.get("week_label", "")
    week_start = state.get("week_start", "")
    version    = state.get("version", 1)

    print(f"  Preview status : {status}")
    print(f"  Week           : {week_label}")
    print(f"  Version        : v{version}")

    if status == "approved":
        print("  Already approved. Nothing to do.")
        return
    if not message_id or not subject:
        print("  Invalid state (missing message_id or subject). Exiting.")
        return

    # Detect if this is the final check (Monday 7AM PHT or later)
    now_pht  = datetime.now(PHT)
    is_final = now_pht.weekday() == 0 and now_pht.hour >= 7  # Monday ≥ 7AM

    processed_uids = state.get("processed_uids", [])

    print("\n  Checking Gmail for replies...")
    sender, body, uid = find_reply(subject, already_processed=processed_uids)

    if not body:
        if is_final:
            print("  No reply by Monday 7AM — automations will run as scheduled.")
            notify_telegram(
                f"📅 Weekly preview ({week_label}) — no approval received.\n"
                f"Automations will run as scheduled at 8:00 AM PHT."
            )
        else:
            print("  No unread reply yet — will check again in 2 hours.")
        return

    print(f"  Reply from : {sender}")
    print(f"  Body       :\n{body[:400]}")

    print("\n  Classifying with Claude...")
    result   = classify_reply(body)
    decision = result.get("decision", "unclear")
    summary  = result.get("summary", "")
    changes  = result.get("changes", "")

    print(f"  Decision   : {decision}")
    print(f"  Summary    : {summary}")

    recipient = RECIPIENTS[0]

    if decision == "approved":
        print("\n  Sending approval confirmation...")
        send_reply(recipient, subject, message_id, html_approved(week_label))
        send_approval_notification(week_label)
        processed_uids.append(uid)
        state["status"]         = "approved"
        state["processed_uids"] = processed_uids
        save_state(state)
        mark_as_read(uid)
        notify_telegram(
            f"✅ Weekly campaign preview APPROVED!\n"
            f"Week: {week_label}\n"
            f"All automations will run as scheduled at 8AM PHT."
        )
        print("  Done — approval confirmed.")

    elif decision == "changes":
        print(f"\n  Changes requested:\n{changes}")
        print("  Regenerating PDF...")
        new_version  = version + 1
        pdf_bytes    = regenerate_pdf(changes)
        pdf_filename = f"weekly_preview_{week_start}_v{new_version}.pdf"

        print(f"  Sending updated preview (v{new_version})...")
        new_msg_id = send_reply(
            recipient, subject, message_id,
            html_updated(week_label, changes, new_version),
            pdf_bytes=pdf_bytes, pdf_filename=pdf_filename,
        )
        processed_uids.append(uid)
        state["status"]         = "pending"
        state["message_id"]     = new_msg_id
        state["version"]        = new_version
        state["processed_uids"] = processed_uids
        save_state(state)
        mark_as_read(uid)
        notify_telegram(
            f"📝 Weekly preview updated to v{new_version} based on feedback.\n"
            f"Changes: {changes[:200]}\n"
            f"Waiting for approval..."
        )
        print(f"  Done — updated preview sent, awaiting re-approval.")

    else:  # unclear
        print("\n  Reply unclear — sending clarification request...")
        send_reply(recipient, subject, message_id, html_unclear(week_label))
        processed_uids.append(uid)
        state["processed_uids"] = processed_uids
        save_state(state)
        mark_as_read(uid)
        notify_telegram(
            f"❓ Weekly preview reply was unclear.\n"
            f"Sent clarification request to {recipient}."
        )
        print("  Done — clarification request sent.")


if __name__ == "__main__":
    main()
