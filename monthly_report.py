# -*- coding: utf-8 -*-
"""
Monthly Marketing Report
Runs on the last day of each month via GitHub Actions.
Generates a comprehensive branded PDF report and emails it to the team.
"""

import os, csv, json, smtplib, io, base64
from pathlib import Path
from datetime import date, timedelta
from calendar import monthrange
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import anthropic
from report_helper import ReportBuilder
from drive_helper import is_cloud
from notifications_helper import push_notification

GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
LEADS_FILE     = Path(__file__).parent / "leads.csv"
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

def load_schedule() -> dict:
    if is_cloud():
        import requests as req
        pat  = os.environ.get("GITHUB_PAT","")
        repo = os.environ.get("GITHUB_REPO","")
        r = req.get(
            f"https://api.github.com/repos/{repo}/contents/posting_schedule.json",
            headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if r.status_code == 200:
            return json.loads(base64.b64decode(r.json()["content"]).decode()).get("schedule", {})
        return {}
    sched_file = Path(__file__).parent / "posting_schedule.json"
    if sched_file.exists():
        with open(sched_file) as f:
            return json.load(f).get("schedule", {})
    return {}

def generate_ai_insights(stats: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = (
        f"You are Eva, the Enderun Marketing AI. Write a concise monthly performance commentary "
        f"(3-4 sentences max) based on these stats:\n\n"
        f"Month: {stats['month_label']}\n"
        f"Total leads: {stats['total']}, Active: {stats['active']}, "
        f"Hot: {stats['hot']}, Warm: {stats['warm']}, Cold: {stats['cold']}\n"
        f"New leads this month: {stats['new_this_month']}\n"
        f"Posts published: {stats['posts_published']}\n"
        f"Top program: {stats['top_program']}\n\n"
        f"Be specific, honest, and actionable. What worked? What needs attention next month? "
        f"Write as Eva — warm, direct, no filler."
    )
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()

def send_report_email(pdf_path: str, month_label: str) -> bool:
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"Enderun Marketing — Monthly Report {month_label}"
        msg["From"]    = f"Eva — Enderun Marketing AI <{GMAIL_ADDRESS}>"
        msg["To"]      = GMAIL_ADDRESS
        msg.attach(MIMEText(
            f"Hi,\n\nAttached is the Monthly Marketing Report for {month_label}.\n\n"
            f"Generated automatically by Eva — Enderun Marketing AI.\n\n"
            f"— Eva",
            "plain"
        ))
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="Enderun_Monthly_Report_{month_label}.pdf"')
        msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False

def main():
    today      = date.today()
    month_label = today.strftime("%B %Y")
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end   = today.strftime("%Y-%m-%d")

    print(f"=== Monthly Report: {month_label} ===")

    leads    = load_leads()
    schedule = load_schedule()
    total    = len(leads)
    active   = [l for l in leads if l.get("status","").lower() == "active"]

    def score(l):
        try:
            c = int(l.get("email_count",0) or 0)
        except Exception:
            c = 0
        if c >= 10: return 3
        if c >= 5:  return 2
        return 1

    hot   = sum(1 for l in active if score(l) == 3)
    warm  = sum(1 for l in active if score(l) == 2)
    cold  = sum(1 for l in active if score(l) == 1)

    # New leads = leads with 0–1 emails sent (recently added, no date_added field in CSV)
    new_this_month = [l for l in leads if int(l.get("email_count",0) or 0) <= 1]

    # Program breakdown
    prog_counts: dict = {}
    for l in active:
        p = l.get("program_interest","Unknown") or "Unknown"
        prog_counts[p] = prog_counts.get(p, 0) + 1
    prog_sorted = sorted(prog_counts.items(), key=lambda x: -x[1])
    top_program = prog_sorted[0][0] if prog_sorted else "N/A"

    # Posts published this month
    posts_this_month = [d for d in schedule if month_start <= d <= month_end]

    stats = {
        "month_label": month_label, "total": total, "active": len(active),
        "hot": hot, "warm": warm, "cold": cold,
        "new_this_month": len(new_this_month),
        "posts_published": len(posts_this_month),
        "top_program": top_program,
    }

    insights = generate_ai_insights(stats)

    # Build PDF
    rb = ReportBuilder(
        agent_id="data-analysis",
        report_title=f"Monthly Marketing Report",
        subtitle=f"{month_label}  |  Enderun Colleges Marketing Department"
    )

    rb.add_section("Month at a Glance")
    rb.add_kpi_row([
        ("Total Leads",     str(total),              False),
        ("Active Leads",    str(len(active)),         True),
        ("New This Month",  str(len(new_this_month)), False),
        ("Posts Published", str(len(posts_this_month)), False),
    ])
    rb.add_kpi_row([
        ("Hot Leads",  str(hot),  False),
        ("Warm Leads", str(warm), False),
        ("Cold Leads", str(cold), False),
    ])

    rb.add_section("Eva's Monthly Commentary")
    rb.add_paragraph(insights)

    rb.add_section("Active Leads by Program")
    if prog_sorted:
        rb.add_table(
            headers=["Program", "Active Leads", "% of Total"],
            rows=[[p, str(c), f"{int(c/len(active)*100)}%" if active else "0%"]
                  for p, c in prog_sorted]
        )

    rb.add_section("Drip Sequence Progress")
    steps: dict = {}
    for l in active:
        k = str(l.get("email_count","0") or "0")
        steps[k] = steps.get(k, 0) + 1
    step_rows = [[f"Step {k}", str(v), f"{int(v/len(active)*100)}%" if active else "0%"]
                 for k, v in sorted(steps.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)]
    if step_rows:
        rb.add_table(headers=["Drip Step", "Leads", "% of Active"], rows=step_rows)

    rb.add_section("New Leads This Month")
    if new_this_month:
        rb.add_table(
            headers=["Name", "Program", "Email"],
            rows=[[l.get("first_name","?") + " " + l.get("last_name","?"),
                   l.get("program_interest","?"),
                   l.get("email","?")]
                  for l in new_this_month[:20]]
        )
        if len(new_this_month) > 20:
            rb.add_paragraph(f"... and {len(new_this_month)-20} more new leads this month.")
    else:
        rb.add_paragraph("No new leads recorded this month.")

    rb.add_section("Content Published This Month")
    if posts_this_month:
        post_rows = [[d, schedule.get(d,"?")[:50]] for d in sorted(posts_this_month)]
        rb.add_table(headers=["Date", "Content"], rows=post_rows)
    else:
        rb.add_alert_box("No posts found in the schedule for this month.", level="warning")

    if cold > 0:
        rb.add_alert_box(
            f"{cold} cold leads still active. Weekly re-engagement emails are running automatically.",
            level="warning"
        )
    if hot >= 5:
        rb.add_alert_box(
            f"{hot} hot leads this month — strong engagement. Prioritize admissions follow-up.",
            level="success"
        )

    rb.add_source("leads.csv — internal data")
    rb.add_source("posting_schedule.json — internal schedule")
    rb.add_source("Claude AI (Eva) — monthly commentary")

    pdf_path = rb.save()
    print(f"PDF saved: {pdf_path}")

    emailed = send_report_email(pdf_path, month_label)
    status  = "✅" if emailed else "⚠️ (email failed)"
    telegram_notify(
        f"📊 <b>Monthly Report — {month_label}</b>\n\n"
        f"Total: {total} leads | Active: {len(active)} | Hot: {hot} | New: {len(new_this_month)}\n"
        f"Posts: {len(posts_this_month)} published\n\n"
        f"Full PDF report sent to your email. {status}"
    )
    push_notification(
        agent_id="weekly-analytics",
        level="success",
        title=f"Monthly Report — {month_label}",
        message=f"PDF generated. {total} leads total, {len(active)} active, {hot} hot. Report emailed.",
        report_path=str(pdf_path),
    )
    print("Done.")

if __name__ == "__main__":
    main()
