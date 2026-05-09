# -*- coding: utf-8 -*-
"""
Enderun Extension - Daily Social Listening & Competitor Monitor
Runs every day at 7:50 AM (before the 8:00 AM drip email and FB post).

What it does:
  1. Checks competitor websites for content changes (hash-based detection)
  2. Searches Google News for recent mentions of each competitor
  3. Uses Claude AI to analyze findings and write an intelligence briefing
  4. Emails the briefing to the Marketing Manager
  5. Saves the report to output/reports/social_listening/

Run: python social_listening.py
Schedule: Daily 7:50 AM via Task Scheduler ("Enderun - Social Listening")
"""

import os
import sys
import json
import hashlib
import smtplib
import requests
import time
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

PHT = timezone(timedelta(hours=8))   # UTC+8 Philippine Time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import anthropic
from notifications_helper import push_notification

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

REPORT_RECIPIENTS = [
    "eva@enderuncolleges.com",
]

BASE_DIR       = Path(__file__).parent
REPORT_DIR     = BASE_DIR / "output" / "reports" / "social_listening"
HASH_FILE      = BASE_DIR / "output" / "reports" / "social_listening" / "competitor_hashes.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# COMPETITORS TO MONITOR
# ---------------------------------------------------------------------------

COMPETITORS = [
    # Enderun Colleges competitors
    {
        "name": "De La Salle University",
        "short": "DLSU",
        "url": "https://www.dlsu.edu.ph/colleges/cthm/",
        "priority": "high",
        "news_query": "De La Salle University hospitality tourism culinary Philippines",
    },
    {
        "name": "Center for Culinary Arts (CCA)",
        "short": "CCA",
        "url": "https://www.cca.edu.ph/",
        "priority": "high",
        "news_query": "Center for Culinary Arts CCA Philippines",
    },
    {
        "name": "ISCAHM",
        "short": "ISCAHM",
        "url": "https://www.iscahm.com/",
        "priority": "high",
        "news_query": "ISCAHM Philippines culinary hospitality",
    },
    {
        "name": "Lyceum of the Philippines University",
        "short": "LPU",
        "url": "https://www.lpu.edu.ph/",
        "priority": "medium",
        "news_query": "Lyceum Philippines University hospitality management",
    },
    {
        "name": "University of Asia and the Pacific",
        "short": "UA&P",
        "url": "https://www.uap.asia/",
        "priority": "medium",
        "news_query": "University Asia Pacific UA&P Philippines tourism",
    },
    {
        "name": "Ateneo de Manila University",
        "short": "Ateneo",
        "url": "https://www.ateneo.edu/",
        "priority": "high",
        "news_query": "Ateneo de Manila business management Philippines",
    },
]

BRAND_QUERIES = [
    "Enderun Colleges Philippines",
    "best hospitality school Philippines 2026",
    "culinary school BGC Philippines",
    "WSET Philippines certification",
    "hospitality management school BGC Manila",
]

# ---------------------------------------------------------------------------
# WEBSITE CHANGE DETECTION
# ---------------------------------------------------------------------------

def fetch_page_text(url: str) -> str:
    """Fetch a webpage and return its visible text content."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:8000]
    except Exception as e:
        return f"FETCH_ERROR: {e}"


def hash_content(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def load_hashes() -> dict:
    if HASH_FILE.exists():
        with open(HASH_FILE, "r") as f:
            return json.load(f)
    return {}


def save_hashes(hashes: dict):
    HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HASH_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


def summarize_change(competitor_name: str, old_text: str, new_text: str) -> str:
    """Use Claude to summarize what specifically changed on the competitor's page."""
    if not ANTHROPIC_KEY:
        return "Change detected — AI summary not available (no API key)."

    prompt = (
        f"A competitor website ({competitor_name}) has changed. "
        f"Compare the old and new page content and write a 2-3 sentence summary of "
        f"what specifically changed. Focus on: new programs, tuition changes, enrollment "
        f"promos, new partnerships, events, or any marketing-relevant updates. "
        f"Be specific and direct. If the change seems minor (navigation, footer, etc.), say so.\n\n"
        f"OLD CONTENT (excerpt):\n{old_text[:1500]}\n\n"
        f"NEW CONTENT (excerpt):\n{new_text[:1500]}"
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Change detected — could not summarize: {e}"


def check_website_changes(competitors: list) -> list:
    """
    Check each competitor website for content changes.
    Returns list of change dicts with AI summary of what changed.
    """
    hashes = load_hashes()
    changes = []
    today   = datetime.now(PHT).date().isoformat()

    print("\n[1/3] Checking competitor websites for changes...")

    for comp in competitors:
        url  = comp["url"]
        name = comp["short"]
        print(f"  Checking {name}... ", end="", flush=True)

        text = fetch_page_text(url)
        if text.startswith("FETCH_ERROR"):
            print(f"could not reach ({text})")
            continue

        current_hash = hash_content(text)
        previous     = hashes.get(url, {})
        prev_hash    = previous.get("hash", "")
        prev_text    = previous.get("text", "")
        prev_date    = previous.get("date", "never")

        if prev_hash and current_hash != prev_hash:
            print(f"⚠️  CHANGED (was: {prev_date}) — summarizing...")
            change_summary = summarize_change(comp["name"], prev_text, text)
            changes.append({
                "competitor":     comp["name"],
                "short":          name,
                "url":            url,
                "priority":       comp["priority"],
                "last_seen":      prev_date,
                "change_summary": change_summary,
                "preview":        text[:400],
            })
        else:
            print("no change")

        # Update hash + store current text for future diffing
        hashes[url] = {"hash": current_hash, "date": today, "text": text[:3000]}
        time.sleep(1.5)  # Be polite to servers

    save_hashes(hashes)
    return changes


# ---------------------------------------------------------------------------
# GOOGLE NEWS SEARCH
# ---------------------------------------------------------------------------

def search_google_news(query: str) -> list:
    """
    Search Google News for recent articles matching the query.
    Returns list of article dicts with title, url, source, snippet.
    Only returns articles from the last 7 days.
    """
    results  = []
    base_url = "https://news.google.com/rss/search"
    # Append when:7d to restrict results to the last 7 days
    params   = {"q": f"{query} when:7d", "hl": "en-PH", "gl": "PH", "ceid": "PH:en"}

    try:
        resp = requests.get(base_url, params=params, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "lxml-xml")
        items = soup.find_all("item")[:5]  # Fetch 5, filter to 3 recent
        for item in items:
            title   = item.find("title").text if item.find("title") else ""
            link    = item.find("link").text if item.find("link") else ""
            source  = item.find("source").text if item.find("source") else ""
            pub     = item.find("pubDate").text if item.find("pubDate") else ""
            snippet = item.find("description").text if item.find("description") else ""
            # Clean HTML from snippet
            snippet = BeautifulSoup(snippet, "lxml").get_text()[:200]
            # Skip articles from 2024 or earlier
            if pub and any(f" {yr} " in pub or pub.endswith(str(yr)) for yr in [2024, 2023, 2022]):
                continue
            if title:
                results.append({
                    "title":   title,
                    "url":     link,
                    "source":  source,
                    "date":    pub[:16],
                    "snippet": snippet,
                })
            if len(results) >= 3:
                break
    except Exception as e:
        results.append({"title": f"Search error: {e}", "url": "", "source": "", "date": "", "snippet": ""})

    return results


def gather_news_intelligence(competitors: list) -> dict:
    """
    Search Google News for all competitors and brand queries.
    Returns dict of {query: [articles]}.
    """
    intel = {}

    print("\n[2/3] Searching Google News for competitor mentions...")

    # Competitor news
    for comp in competitors:
        query = comp["news_query"]
        print(f"  Searching: {comp['short']}... ", end="", flush=True)
        articles = search_google_news(query)
        if articles:
            intel[comp["name"]] = articles
            print(f"{len(articles)} articles")
        else:
            print("none")
        time.sleep(1.5)

    # Brand + industry queries
    print("  Searching brand/industry queries...")
    brand_articles = []
    for query in BRAND_QUERIES:
        articles = search_google_news(query)
        brand_articles.extend(articles)
        time.sleep(1)

    # Deduplicate brand articles by title
    seen   = set()
    unique = []
    for a in brand_articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    if unique:
        intel["__brand__"] = unique[:6]

    return intel


# ---------------------------------------------------------------------------
# AI ANALYSIS
# ---------------------------------------------------------------------------

def generate_intelligence_briefing(changes: list, news: dict, today: date) -> str:
    """Use Claude to analyze all findings and write the morning briefing."""

    if not ANTHROPIC_KEY:
        return "Claude AI analysis not available — API key not set."

    # Build data summary for Claude
    summary_parts = []

    if changes:
        summary_parts.append("=== WEBSITE CHANGES DETECTED ===")
        for c in changes:
            summary_parts.append(
                f"- {c['competitor']} ({c['priority'].upper()} priority): "
                f"Page changed at {c['url']} — last seen: {c['last_seen']}\n"
                f"  What changed: {c.get('change_summary', 'N/A')}"
            )
    else:
        summary_parts.append("=== WEBSITE CHANGES: None detected today ===")

    if news:
        summary_parts.append("\n=== GOOGLE NEWS RESULTS ===")
        for entity, articles in news.items():
            if entity == "__brand__":
                summary_parts.append("\n-- Enderun / Industry News --")
            else:
                summary_parts.append(f"\n-- {entity} --")
            for a in articles:
                summary_parts.append(
                    f"  [{a['date']}] {a['title']} ({a['source']})\n"
                    f"  {a['snippet']}"
                )

    data_text = "\n".join(summary_parts)

    prompt = f"""You are the Social Listening & Competitor Intelligence Specialist for Enderun Colleges and Enderun Extension — a premium private college in McKinley Hill, BGC, Philippines with Les Roches (Top 3 globally in hospitality) and École Ducasse affiliations.

Today is {today.strftime('%B %d, %Y')}.

Here is today's competitor intelligence data:

{data_text}

---

Write a concise, actionable Morning Intelligence Briefing for the Marketing Manager. Use this exact structure:

**🚨 ALERTS REQUIRING ACTION**
List any CRITICAL or MEDIUM alerts that need a marketing response today. If none, say "No critical alerts today — continue normal operations."
For each alert: what happened, why it matters for Enderun, what to do.

**📰 NEWS & MEDIA SUMMARY**
Summarize the most relevant news findings. Flag anything that could affect Enderun's enrollment, reputation, or competitive position.

**🌐 WEBSITE CHANGES**
Report any competitor website changes. Speculate on what the change might mean (new program? tuition update? enrollment push?).

**💡 TODAY'S RECOMMENDED ACTION**
One specific, concrete action for the marketing team to take today based on this intelligence. Name which agent should act.

**📊 THREAT LEVEL TODAY**
Overall: 🔴 High / 🟡 Medium / 🟢 Low — with one sentence explanation.

IMPORTANT FORMATTING RULES:
- Do NOT use #, ##, ###, ----, or → anywhere in your response
- Do NOT use bullet points starting with -
- Use only **bold text** for section headers and key terms
- Write in clean prose paragraphs only
- Max 550 words total."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# REPORT & EMAIL
# ---------------------------------------------------------------------------

def save_report(briefing: str, changes: list, news: dict, today: date) -> Path:
    """Save full report to output/reports/social_listening/."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{today.isoformat()}_intelligence_briefing.txt"

    lines = [
        f"ENDERUN INTELLIGENCE BRIEFING — {today.strftime('%B %d, %Y')}",
        f"Generated: {datetime.now(PHT).strftime('%Y-%m-%d %H:%M')} PHT",
        "=" * 60,
        "",
        "AI ANALYSIS",
        "-" * 60,
        briefing,
        "",
        "RAW DATA",
        "-" * 60,
        f"Website changes detected: {len(changes)}",
    ]
    for c in changes:
        lines.append(f"  - {c['competitor']}: {c['url']}")

    lines.append(f"\nNews searches completed: {len(news)}")
    for entity, articles in news.items():
        label = "Brand/Industry" if entity == "__brand__" else entity
        lines.append(f"\n  [{label}]")
        for a in articles:
            lines.append(f"    • {a['date']} — {a['title']} ({a['source']})")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_email_html(briefing: str, changes: list, today: date) -> str:
    """Build branded HTML email for the intelligence briefing."""
    change_notice = ""
    if changes:
        change_items = "".join(
            f"<li style='margin-bottom:14px;'>"
            f"<strong style='color:#E8603C;'>{c['competitor']}</strong> "
            f"<span style='font-size:11px;color:#999;'>(Priority: {c['priority'].upper()}) — last checked: {c['last_seen']}</span><br>"
            f"<a href='{c['url']}' style='color:#C9A84C;font-size:12px;'>{c['url']}</a><br>"
            f"<span style='font-size:13px;color:#333;line-height:1.6;text-align:justify;display:block;'>{c.get('change_summary', 'Change detected — no summary available.')}</span>"
            f"</li>"
            for c in changes
        )
        change_notice = f"""
        <div style="background:#FFF3CD;border-left:4px solid #E8603C;padding:16px 20px;margin:16px 0;border-radius:0 6px 6px 0;">
          <p style="margin:0 0 12px;font-weight:700;color:#E8603C;font-size:13px;text-transform:uppercase;letter-spacing:1px;">
            ⚠️ Website Changes Detected
          </p>
          <ul style="margin:0;padding-left:20px;font-size:13px;color:#333;">{change_items}</ul>
        </div>"""

    import re

    def md_to_html(text: str) -> str:
        """Convert **bold** markdown to <strong> HTML tags."""
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    def clean_line(text: str) -> str:
        """Remove markdown symbols: #, ##, →, -, --- from the start/anywhere in line."""
        # Remove leading #, ##, ### headings
        text = re.sub(r'^#{1,6}\s*', '', text)
        # Remove horizontal rules ---
        if re.match(r'^-{2,}$', text.strip()):
            return ""
        # Remove leading - bullet or → arrow
        text = re.sub(r'^[-→]\s*', '', text)
        # Remove → anywhere
        text = text.replace('→', '')
        return text.strip()

    # Format briefing text as HTML paragraphs
    briefing_html = ""
    for line in briefing.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Skip pure horizontal rules
        if re.match(r'^-{2,}$', line):
            continue
        # Section headers: entire line is **...**
        if re.match(r'^\*\*.+\*\*$', line):
            section = line.strip("*")
            briefing_html += f'<p style="margin:20px 0 8px;font-size:13px;font-weight:700;color:#1A2B4A;text-transform:uppercase;letter-spacing:1px;">{section}</p>'
        else:
            cleaned = clean_line(line)
            if not cleaned:
                continue
            briefing_html += f'<p style="margin:0 0 10px;font-size:14px;line-height:1.7;color:#333;text-align:justify;">{md_to_html(cleaned)}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#F4F4F4;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F4F4;padding:24px 0;">
  <tr><td align="center">
    <table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

      <!-- Gold top bar -->
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>

      <!-- Header -->
      <tr>
        <td style="background:#1A2B4A;padding:20px 36px;">
          <table width="100%"><tr>
            <td>
              <p style="margin:0;font-size:10px;letter-spacing:3px;color:#C9A84C;text-transform:uppercase;font-weight:700;">Enderun Marketing Intelligence</p>
              <p style="margin:4px 0 0;font-size:17px;color:#fff;font-weight:700;">Daily Competitor Briefing</p>
            </td>
            <td align="right" style="vertical-align:middle;">
              <p style="margin:0;font-size:11px;color:#8A9BB0;">{today.strftime('%A, %B %d, %Y')}</p>
              <p style="margin:2px 0 0;font-size:10px;color:#4A5A72;">7:50 AM Auto-Report</p>
            </td>
          </tr></table>
        </td>
      </tr>
      <tr><td style="background:#C9A84C;height:3px;font-size:0;">&nbsp;</td></tr>

      <!-- Change alert (if any) -->
      {"<tr><td style='padding:16px 36px 0;'>" + change_notice + "</td></tr>" if changes else ""}

      <!-- AI Briefing -->
      <tr>
        <td style="padding:24px 36px;">
          <p style="margin:0 0 16px;font-size:12px;letter-spacing:2px;color:#C9A84C;text-transform:uppercase;font-weight:700;">AI Intelligence Analysis</p>
          <div style="background:#F8F6F0;border-left:4px solid #C9A84C;padding:20px 24px;border-radius:0 6px 6px 0;">
            {briefing_html}
          </div>
        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="background:#F8F6F0;padding:14px 36px;border-top:1px solid #EEE;text-align:center;">
          <p style="margin:0;font-size:11px;color:#AAA;">
            Auto-generated by Enderun Social Listening System &bull;
            <a href="https://enderunextension.com" style="color:#C9A84C;text-decoration:none;">enderunextension.com</a>
          </p>
        </td>
      </tr>
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def send_briefing_email(html: str, today: date, changes: list):
    """Email the intelligence briefing."""
    alert_tag  = " 🚨 ALERT" if changes else ""
    subject    = f"[Intelligence Briefing{alert_tag}] Competitor Monitor — {today.strftime('%B %d, %Y')}"

    failed = 0
    for recipient in REPORT_RECIPIENTS:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"Enderun Intelligence <{GMAIL_ADDRESS}>"
        msg["To"]      = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))
        try:
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                    server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
                    server.sendmail(GMAIL_ADDRESS, recipient, msg.as_string())
            except Exception:
                # Fallback to port 587 STARTTLS
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
                    server.sendmail(GMAIL_ADDRESS, recipient, msg.as_string())
            print(f"  Briefing sent to {recipient}")
        except Exception as e:
            print(f"  Failed to send to {recipient}: {e}")
            failed += 1
    if failed == len(REPORT_RECIPIENTS):
        print("  ERROR: Could not send briefing to any recipient.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Enderun - Social Listening & Competitor Monitor")
    print(f"  {datetime.now(PHT).strftime('%Y-%m-%d %H:%M')} PHT")
    print("=" * 60)

    today = datetime.now(PHT).date()

    # 1. Check websites for changes
    changes = check_website_changes(COMPETITORS)

    # 2. Search Google News
    news = gather_news_intelligence(COMPETITORS)

    # 3. Generate AI briefing
    print("\n[3/3] Generating AI intelligence briefing...")
    briefing = generate_intelligence_briefing(changes, news, today)
    print("  Briefing generated.")

    # 4. Save report
    report_path = save_report(briefing, changes, news, today)
    print(f"  Report saved: {report_path.name}")

    # 5. Send email
    html = build_email_html(briefing, changes, today)
    send_briefing_email(html, today, changes)

    # Notifications
    if changes:
        changed_names = ", ".join(c["competitor"] for c in changes[:3])
        push_notification(
            agent_id="social-listening",
            level="critical",
            title=f"{len(changes)} competitor website change{'s' if len(changes)>1 else ''} detected",
            message=f"{changed_names} — check your intelligence briefing email for details.",
            report_path=str(report_path.relative_to(Path(__file__).parent)),
        )
    else:
        push_notification(
            agent_id="social-listening",
            level="success",
            title="Daily intelligence briefing sent",
            message=f"No website changes detected. {len(news)} competitor news searches completed.",
            report_path=str(report_path.relative_to(Path(__file__).parent)),
        )

    # Summary
    print("\n" + "=" * 60)
    if changes:
        print(f"  ⚠️  {len(changes)} website change(s) detected — check email!")
    else:
        print("  ✅ No website changes detected.")
    print(f"  📰 News searches: {len(news)} entities covered")
    print("  ✅ Intelligence briefing sent.")
    print("=" * 60)


if __name__ == "__main__":
    main()
