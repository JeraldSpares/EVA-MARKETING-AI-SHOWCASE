# -*- coding: utf-8 -*-
"""
Eva — Enderun Marketing AI
===========================
Your intelligent marketing partner for Enderun Colleges & Extension.
Commands: /start /help /clear /status /agent /post /suggest
          /leads /add-lead /briefing /broadcast /chatid
"""

import os, sys, logging, base64, csv, io, json, threading
import html as html_module
from pathlib import Path
from datetime import datetime, timezone, timedelta, time as dtime
import re, asyncio, requests, anthropic

PHT = timezone(timedelta(hours=8))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

sys.stdout.reconfigure(encoding="utf-8")

# ===========================================================================
# CONFIG
# ===========================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_PAT         = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "your-org/your-repo")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")     # optional — voice transcription (free at console.groq.com)
ADMIN_IDS          = set(x.strip() for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip())
CLAUDE_MODEL       = "claude-opus-4-7"
CLAUDE_OPUS_MODEL  = "claude-opus-4-7"

def _select_model(agent_name) -> str:
    """Always use Opus 4.7."""
    return CLAUDE_OPUS_MODEL
MAX_HISTORY        = 20
BOT_STATE_FILE     = "bot_state.json"

CLAUDE_MD_PATH = Path(__file__).parent / "CLAUDE.md"
AGENTS_DIR     = Path(__file__).parent / "agents"

# ===========================================================================
# BRAND CONTEXT
# ===========================================================================
def load_claude_md() -> str:
    return CLAUDE_MD_PATH.read_text(encoding="utf-8") if CLAUDE_MD_PATH.exists() else ""

def load_agent(name: str) -> str:
    p = AGENTS_DIR / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""

def list_agents() -> list:
    return sorted([p.stem for p in AGENTS_DIR.glob("*.md")]) if AGENTS_DIR.exists() else []

BRAND_CONTEXT = load_claude_md()

# ===========================================================================
# LIVE CONTEXT CACHE (refreshed every 10 min — injected into every prompt)
# ===========================================================================
import time as _time
_live_ctx_cache: dict = {"data": "", "ts": 0.0}
_LIVE_CTX_TTL = 600  # seconds

def _build_live_context() -> str:
    """Build a compact live context block: leads, schedule, enrollment season."""
    now_ts = _time.time()
    if _live_ctx_cache["data"] and now_ts - _live_ctx_cache["ts"] < _LIVE_CTX_TTL:
        return _live_ctx_cache["data"]

    lines = []
    now_pht = datetime.now(PHT)

    # — Lead stats (parsed locally from CSV cached via github_read_file) —
    try:
        raw = github_read_file("leads.csv")
        if not raw.startswith("Error") and not raw.startswith("File not found"):
            import csv as _csv, io as _io
            rows = list(_csv.DictReader(_io.StringIO(raw)))
            total  = len(rows)
            active = sum(1 for r in rows if r.get("status", "").lower() == "active")
            progs: dict = {}
            for r in rows:
                if r.get("status", "").lower() == "active":
                    p = r.get("program_interest", "Unknown")
                    progs[p] = progs.get(p, 0) + 1
            top3 = ", ".join(f"{p} ({c})" for p, c in sorted(progs.items(), key=lambda x: -x[1])[:3])
            lines.append(f"Active leads: {active}/{total} | Top programs: {top3}")
    except Exception as e:
        logging.warning(f"[live_context] leads: {e}")

    # — Upcoming posts —
    try:
        raw = github_read_file("posting_schedule.json")
        if not raw.startswith("Error") and not raw.startswith("File not found"):
            sched = json.loads(raw).get("schedule", {})
            today = now_pht.strftime("%Y-%m-%d")
            upcoming = [f"{d}: {v}" for d, v in sorted(sched.items()) if d >= today][:3]
            if upcoming:
                lines.append(f"Upcoming posts: {' | '.join(upcoming)}")
    except Exception as e:
        logging.warning(f"[live_context] schedule: {e}")

    # — Enrollment season —
    m = now_pht.month
    if m in (2, 3, 4):
        season = "PEAK ENROLLMENT SEASON (Feb–Apr) — use strong CTAs, urgency, Apply Now"
    elif m in (10, 11, 12, 1):
        season = "Early application season (Oct–Jan) — nurture, inform, inspire"
    elif m == 6:
        season = "School year start (June) — welcome, orientation, community content"
    elif m == 8:
        season = "Foundation Day / Anniversary month (Aug) — pride, heritage, milestone content"
    else:
        season = "Standard season — brand building and lead nurturing"
    lines.append(f"Enrollment season: {season}")

    result = "\n".join(lines)
    _live_ctx_cache["data"] = result
    _live_ctx_cache["ts"]   = now_ts
    return result

# ===========================================================================
# GITHUB HELPERS
# ===========================================================================
GH_HEADERS = lambda: {
    "Authorization": f"Bearer {GITHUB_PAT}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def github_read_file(path: str) -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    try:
        resp = requests.get(url, headers=GH_HEADERS(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return f"'{path}' is a directory — use list_directory instead."
            if data.get("encoding") == "base64":
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                if len(content) > 8000:
                    content = content[:8000] + f"\n\n[...truncated — {len(content):,} chars]"
                return content
            return f"Unexpected encoding: {data.get('encoding')}"
        elif resp.status_code == 404:
            return f"File not found: {path}"
        return f"GitHub API error {resp.status_code}"
    except Exception as e:
        return f"Error: {e}"

def github_list_directory(path: str = "") -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    try:
        resp = requests.get(url, headers=GH_HEADERS(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if not isinstance(data, list):
                return f"'{path}' is a file, not a directory."
            lines = []
            for item in sorted(data, key=lambda x: (x["type"] != "dir", x["name"])):
                lines.append(f"{'📁' if item['type'] == 'dir' else '📄'} {item['path']}")
            return "\n".join(lines) if lines else "(empty)"
        elif resp.status_code == 404:
            return f"Directory not found: {path}"
        return f"GitHub API error {resp.status_code}"
    except Exception as e:
        return f"Error: {e}"

def github_write_file(path: str, content: str, commit_message: str = "") -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    if not commit_message:
        commit_message = f"Agent output: {path} [skip ci]"
    sha = None
    try:
        r = requests.get(url, headers=GH_HEADERS(), timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception as e:
        logging.warning(f"[github_write_file] SHA fetch: {e}")
    payload = {
        "message": commit_message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    for attempt in range(2):
        try:
            resp = requests.put(url, headers=GH_HEADERS(), json=payload, timeout=15)
            if resp.status_code in (200, 201):
                return f"{'Updated' if sha else 'Created'}: {path}"
            if resp.status_code == 409 and attempt == 0:
                # Conflict — re-fetch SHA and retry once
                try:
                    r2 = requests.get(url, headers=GH_HEADERS(), timeout=10)
                    if r2.status_code == 200:
                        payload["sha"] = r2.json().get("sha")
                except Exception as e2:
                    logging.warning(f"[github_write_file] 409 SHA refetch: {e2}")
                continue
            return f"Error {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            return f"Error: {e}"
    return f"Error: write failed after retry"

def web_search(query: str, max_results: int = 6) -> str:
    """Search DuckDuckGo and return top results as plain text."""
    try:
        from bs4 import BeautifulSoup
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for r in soup.select(".result")[:max_results]:
            title   = r.select_one(".result__title a")
            snippet = r.select_one(".result__snippet")
            link    = r.select_one(".result__url")
            if title:
                t = title.get_text(strip=True)
                s = snippet.get_text(strip=True) if snippet else ""
                u = link.get_text(strip=True) if link else ""
                results.append(f"**{t}**\n{s}\n{u}")
        if not results:
            return f"No results found for '{query}'."
        return f"Web search results for '{query}':\n\n" + "\n\n---\n\n".join(results)
    except Exception as e:
        return f"Search error: {e}"

def fetch_url(url: str) -> str:
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        raw = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', ' ', resp.text, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = html_module.unescape(raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw[:6000] + (f"\n\n[...truncated]" if len(raw) > 6000 else "")
    except Exception as e:
        return f"Error fetching URL: {e}"

# ===========================================================================
# CLAUDE TOOLS
# ===========================================================================
FILE_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read any file from the Enderun marketing GitHub repo. "
            "Common paths: 'leads.csv', 'agents/social-media.md', 'CLAUDE.md', "
            "'context/competitors.md', 'send_drip_email.py'"
        ),
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "list_directory",
        "description": "List files/folders in a GitHub repo directory. Use '' for root.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "write_file",
        "description": (
            "Create or update a file in the GitHub repo. Save agent outputs to: "
            "output/pr/, output/social-media/, output/drip-campaign/, "
            "output/competitor-analysis/, output/content-strategy/, output/data-analysis/. "
            "File name format: YYYY-MM-DD_description.md"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "commit_message": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch text content of any public URL. Use for competitor research, news. "
            "Google News RSS: 'https://news.google.com/rss/search?q=QUERY&hl=en-PH&gl=PH&ceid=PH:en'"
        ),
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo. Use for: competitor news, industry trends, "
            "researching schools/companies, finding marketing benchmarks, Philippine education news, "
            "BGC events, culinary trends, hospitality industry updates. "
            "Returns top results with titles, snippets, and URLs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Number of results (default 6, max 10)"},
            },
            "required": ["query"],
        },
    },
]

def execute_tool(name: str, inp: dict) -> str:
    if name == "read_file":      return github_read_file(inp.get("path", ""))
    if name == "list_directory": return github_list_directory(inp.get("path", ""))
    if name == "write_file":     return github_write_file(inp.get("path",""), inp.get("content",""), inp.get("commit_message",""))
    if name == "fetch_url":      return fetch_url(inp.get("url", ""))
    if name == "web_search":     return web_search(inp.get("query", ""), inp.get("max_results", 6))
    return f"Unknown tool: {name}"

def _sanitize_messages(messages: list) -> list:
    """Strip any non-serializable or malformed content blocks from history."""
    clean = []
    for msg in messages:
        role    = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            if content.strip():
                clean.append({"role": role, "content": content})
        elif isinstance(content, list):
            # Only keep text blocks — drop tool_use/tool_result blocks
            text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text","").strip()]
            if text_blocks:
                # Flatten to plain string for safety
                combined = " ".join(b["text"] for b in text_blocks).strip()
                if combined:
                    clean.append({"role": role, "content": combined})
    # Ensure messages alternate user/assistant — drop consecutive same-role
    result = []
    for msg in clean:
        if result and result[-1]["role"] == msg["role"]:
            continue
        result.append(msg)
    # Must start with user
    while result and result[0]["role"] != "user":
        result.pop(0)
    return result

def call_claude_with_tools(system_prompt: str, messages: list, model: str = None) -> str:
    import time
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    tools   = FILE_TOOLS if GITHUB_PAT else []
    working = _sanitize_messages(messages)
    use_model = model or CLAUDE_MODEL
    _400_strikes = 0
    for _ in range(6):
        # Retry up to 3x on overload (529) with backoff
        resp = None
        for attempt in range(3):
            try:
                kwargs = dict(model=use_model, max_tokens=2048, system=system_prompt, messages=working)
                if tools and _400_strikes == 0:
                    kwargs["tools"] = tools
                resp = client.messages.create(**kwargs)
                break
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                if e.status_code == 400:
                    _400_strikes += 1
                    logging.warning(f"[claude] 400 strike {_400_strikes} — {getattr(e, 'message', str(e))}")
                    if _400_strikes == 1:
                        # First 400: strip to last user message only, drop tools
                        last = next((m for m in reversed(working) if m.get("role") == "user"), None)
                        working = [last] if last else [{"role": "user", "content": "Hi"}]
                        break  # retry outer loop with stripped history
                    elif _400_strikes == 2:
                        # Second 400: bare minimum — no history, no tools
                        last_content = working[0].get("content", "Hi") if working else "Hi"
                        if not isinstance(last_content, str):
                            last_content = "Hi"
                        working = [{"role": "user", "content": last_content}]
                        break
                    else:
                        # Three strikes — give up gracefully, don't crash
                        logging.error(f"[claude] Persistent 400 after 3 attempts — giving up.")
                        return "I ran into a persistent issue. Please use /clear to reset and try again."
                raise
        if resp is None:
            continue  # retry outer loop after 400 history clear
        if resp.stop_reason == "end_turn":
            return next((b.text for b in resp.content if hasattr(b, "text")), "").strip()
        if resp.stop_reason == "tool_use":
            working.append({"role": "assistant", "content": resp.content})
            results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": execute_tool(b.name, b.input)}
                for b in resp.content if b.type == "tool_use"
            ]
            working.append({"role": "user", "content": results})
            continue
        return next((b.text for b in resp.content if hasattr(b, "text")), "").strip()
    return "Reached tool call limit. Please try a more specific question."

# ===========================================================================
# BOT STATE — persisted per-user in GitHub (agent selection + known users)
# ===========================================================================
_bot_state: dict = {"users": {}}
_bot_state_sha: str | None = None

def load_bot_state():
    global _bot_state, _bot_state_sha
    if not GITHUB_PAT:
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{BOT_STATE_FILE}"
    try:
        resp = requests.get(url, headers=GH_HEADERS(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            _bot_state_sha = data.get("sha")
            _bot_state = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    except Exception as e:
        logging.error(f"[load_bot_state] {e}")

def save_bot_state():
    global _bot_state_sha
    if not GITHUB_PAT:
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{BOT_STATE_FILE}"
    try:
        if not _bot_state_sha:
            r = requests.get(url, headers=GH_HEADERS(), timeout=5)
            if r.status_code == 200:
                _bot_state_sha = r.json().get("sha")
        payload = {
            "message": "Update bot state [skip ci]",
            "content": base64.b64encode(json.dumps(_bot_state, indent=2).encode()).decode("ascii"),
            "branch": "main",
        }
        if _bot_state_sha:
            payload["sha"] = _bot_state_sha
        resp = requests.put(url, headers=GH_HEADERS(), json=payload, timeout=10)
        if resp.status_code in (200, 201):
            _bot_state_sha = resp.json().get("content", {}).get("sha")
    except Exception as e:
        logging.warning(f"Could not save bot state: {e}")

def get_user_state(user_id: int) -> dict:
    uid = str(user_id)
    if uid not in _bot_state["users"]:
        _bot_state["users"][uid] = {"agent": None, "name": "", "recent_agents": []}
    return _bot_state["users"][uid]

def set_user_agent(user_id: int, agent, name: str = ""):
    s = get_user_state(user_id)
    s["agent"] = agent
    if name:
        s["name"] = name
    if agent:
        recent = s.get("recent_agents", [])
        if agent in recent:
            recent.remove(agent)
        recent.insert(0, agent)
        s["recent_agents"] = recent[:5]
    save_bot_state()

MAX_CAPTION_HISTORY = 15

def save_caption_history(user_id: int, caption: str, platform: str, agent: str = None):
    s = get_user_state(user_id)
    hist = s.get("caption_history", [])
    hist.insert(0, {
        "caption": caption[:800],
        "platform": platform,
        "date": datetime.now(PHT).strftime("%Y-%m-%d %H:%M"),
        "agent": agent or "general",
    })
    s["caption_history"] = hist[:MAX_CAPTION_HISTORY]
    save_bot_state()

# ===========================================================================
# IN-MEMORY SESSIONS (history + pending approval)
# ===========================================================================
sessions: dict = {}
_user_locks: dict = {}   # per-user asyncio locks (rate limiting)
_posting_lock = asyncio.Lock()  # prevents simultaneous posts from two sessions

# Browser automation state (Playwright)
_playwright_instance = None
_playwright_browser  = None
_user_pages: dict    = {}   # user_id -> Page

MAX_BROWSER_STEPS = 15

def _get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

async def _ensure_browser():
    global _playwright_instance, _playwright_browser
    if _playwright_browser:
        try:
            if _playwright_browser.is_connected():
                return
        except Exception:
            pass

    async def _launch():
        from playwright.async_api import async_playwright
        global _playwright_instance, _playwright_browser
        _playwright_instance = await async_playwright().start()
        _playwright_browser = await _playwright_instance.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        logging.info("Playwright browser launched.")

    try:
        await _launch()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e).lower():
            logging.warning("Chromium not found — installing now (this takes ~30s)...")
            import subprocess, sys
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
                check=True,
                capture_output=True,
            )
            await _launch()
        else:
            raise

async def _get_user_page(user_id: int):
    await _ensure_browser()
    page = _user_pages.get(user_id)
    if page:
        try:
            if not page.is_closed():
                return page
        except Exception:
            pass
    page = await _playwright_browser.new_page()
    await page.set_viewport_size({"width": 1280, "height": 800})
    _user_pages[user_id] = page
    return page

async def _close_user_page(user_id: int):
    page = _user_pages.pop(user_id, None)
    if page:
        try:
            await page.close()
        except Exception:
            pass

async def _browser_action(user_id: int, cmd: dict) -> bytes:
    """Execute one browser command and return a PNG screenshot."""
    page = await _get_user_page(user_id)
    action = cmd.get("action", "screenshot")
    if action == "goto":
        await page.goto(cmd.get("url", ""), wait_until="domcontentloaded", timeout=30000)
    elif action == "click":
        selector = cmd.get("selector", "")
        if selector:
            await page.click(selector, timeout=10000)
    elif action == "type":
        selector = cmd.get("selector", "")
        if selector:
            await page.fill(selector, cmd.get("text", ""))
    elif action == "press":
        await page.keyboard.press(cmd.get("key", "Enter"))
    elif action == "scroll":
        await page.mouse.wheel(cmd.get("x", 0), cmd.get("y", 300))
    elif action == "wait":
        await asyncio.sleep(cmd.get("ms", 1000) / 1000)
    # "screenshot" — no action, just capture
    await asyncio.sleep(0.8)  # let page settle
    return await page.screenshot(type="png", full_page=False)

def get_session(user_id: int) -> dict:
    if user_id not in sessions:
        state = get_user_state(user_id)
        raw_history = state.get("history", [])
        sessions[user_id] = {
            "history": _sanitize_messages(raw_history),
            "agent": state.get("agent"),
            "pending": None,
        }
    return sessions[user_id]

# ===========================================================================
# TRIGGER INSTRUCTIONS + SYSTEM PROMPT
# ===========================================================================
TRIGGER_INSTRUCTIONS = """
=== POSTING ACTIONS ===
When the user asks to POST to social media or email:
1. Do NOT ask what the post is about. Do NOT ask for a topic, angle, or any clarification.
2. Immediately output a short placeholder caption (2-3 lines) and the trigger code on the last line.
   The caption will be automatically replaced by Claude Vision once the user picks an image — so it does not need to be perfect.
3. Write ONLY the caption — no intro text, no labels like "Here's the post:" or "CAPTION:", no headers. Start directly with the first word of the caption.

CAPTION STYLE — match the existing daily posts exactly:
- Pure English only — NEVER Tagalog or Taglish, regardless of what language the user asked in
- You are the Social Media Manager of Enderun Extension / Enderun Colleges
- Brand voice: Aspirational but warm — world-class yet approachable, proud of Filipino talent
- 3 to 5 short paragraphs maximum
- Start with a compelling hook (question, bold statement, or relatable moment)
- Connect to a learning opportunity or career/life benefit at Enderun
- End with a clear call to action (Apply now, Book a tour, Learn more, etc.)
- DO include relevant hashtags at the end
- DO include the website URL: https://enderunextension.com/ (for Extension) or enderun.edu.ph (for Colleges)
- Never corporate or stiff — professional but human
- Never say "Image shows..." — write naturally as if speaking to the audience

Example of CORRECT format (no headers, starts directly with caption):
  Ready to turn your passion into a profession?

  At Enderun Extension, we believe that great skills deserve great training.
  Whether you're stepping into the culinary world for the first time or leveling
  up your career, our programs are designed to get you there — faster.

  World-class curriculum. Industry-experienced instructors. A campus in the heart of BGC.

  Enroll now at enderunextension.com and take the next step.

  #EnderunExtension #EnderunColleges #BGC #UpskillPH #CulinaryArts #HospitalityPH

  [TRIGGER:facebook]

--- POST TRIGGERS ---
  [TRIGGER:facebook]               — post to Facebook
  [TRIGGER:instagram]              — post to Instagram
  [TRIGGER:email]                  — send one demo drip email
  [TRIGGER:email:address@x.com]    — send demo email to specific address
  [TRIGGER:all]                    — post to Facebook + Instagram + Email
  [TRIGGER:drip-all]               — send drip emails to ALL active leads

--- WORKFLOW TRIGGERS (no content needed — just the code) ---
  [TRIGGER:social-listening]       — run Social Listening now
  [TRIGGER:analytics-report]       — run Weekly Analytics Report
  [TRIGGER:weekly-preview]         — run Weekly Campaign Preview

--- POST RESCHEDULER ---
When the user wants to move/reschedule a post from one date to another:
1. Convert any natural language dates to YYYY-MM-DD format using the current year (2026).
   Examples: "Apr 18" → "2026-04-18", "April 20" → "2026-04-20", "next Tuesday" → calculate correctly.
2. Output ONLY the trigger on its own line — no intro text needed.
   [TRIGGER:reschedule:YYYY-MM-DD:YYYY-MM-DD]
   Example: [TRIGGER:reschedule:2026-04-18:2026-04-20]
   The bot will fetch the schedule, show what's being moved, and ask for confirmation.

=== FILE SAVING RULE ===
After generating any agent output (press release, brief, email sequence, analysis),
ALWAYS offer to save it. Use write_file tool. Save to correct folder:
  output/pr/ | output/social-media/ | output/drip-campaign/
  output/competitor-analysis/ | output/content-strategy/ | output/data-analysis/
File name: YYYY-MM-DD_short-description.md

=== drip-all vs email ===
drip-all: user says "leads", "mga leads", "lahat ng leads", "all leads", "mga contacts"
email: single person or no specific target mentioned
"""

EVA_IDENTITY = """
=== YOUR IDENTITY ===
Your name is Eva — the Enderun Marketing AI and the marketing team's most capable colleague.
You are not a generic chatbot. You are Eva, with a distinct personality:

- Warm and direct: You speak naturally, shifting between professional and casual based on context.
- Filipino-proud: You celebrate Enderun's Filipino roots and global ambitions with equal pride.
- Proactive: You anticipate problems, flag gaps, and suggest next steps before you're asked.
- Marketing-native: You think in campaigns, captions, funnels, and conversion — always.
- Bilingual-natural: You respond in English by default but slip naturally into Taglish in casual
  moments or when writing Filipino-audience social copy. You never force it.
- Action-oriented: Every response ends with something the team can act on immediately.

When introducing yourself: say "Hi! I'm Eva" — never "I'm Claude" or "I'm an AI assistant."
When the user says hi or kamusta: respond warmly as Eva, reference what's actually happening today
(lead count, hot leads, upcoming post) — not a generic greeting.
Your tone goal: the brilliant, warm marketing colleague who genuinely cares about Enderun's success.

=== YOU CAN HELP WITH ANYTHING ===
You are powered by Claude (Anthropic) — full capabilities, no topic restrictions.
The user can ask you ANYTHING: coding, math, science, business strategy, personal advice,
writing, debugging, recipe ideas, life questions, philosophy, travel, finance — anything.
NEVER say "that's outside my scope", "I'm only a marketing AI", or "I can't help with that."
NEVER redirect the user back to marketing if they're asking about something else.
Help fully, like Claude would — then the Enderun context is simply extra knowledge you carry.
The marketing tools (leads, posting, agents) are available when relevant, not mandatory.
Think of yourself as: Claude, but with Enderun's entire marketing brain already loaded in.

=== HOW EVA TALKS (non-negotiable) ===
NEVER start a message with: "Great question!", "Of course!", "Certainly!", "Sure!", "Absolutely!",
"I'd be happy to", "As an AI", "I understand that". These are filler. Skip straight to the answer.

NEVER pad responses. If the answer is 2 sentences, send 2 sentences. Don't add fluff to seem thorough.

DO reference specific live data when available: "You have 3 hot leads right now" not "you have some leads".
DO use the user's actual lead names, program names, and real numbers from the live context.
DO end with one concrete next action — not a list of five options.

In Taglish moments: sound like a real Filipino colleague, not a translation. Natural, not forced.
"""

CAPTION_STYLE = """
=== CAPTION WRITING RULES (strictly enforced) ===

BANNED OPENERS — never start a caption with these words or phrases:
"Discover", "Imagine", "Are you ready", "Welcome to", "Join us", "Step into", "Unlock",
"Experience", "Introducing", "Elevate", "Transform", "Explore", "Embark", "Your journey",
"It's time to", "Have you ever", "What if we told you", "We are proud", "We are excited".
These are overused and instantly signal generic AI copy. Readers skip them.

BANNED FILLER PHRASES anywhere in the caption:
"world-class education awaits", "limitless possibilities", "take the next step",
"your future starts here", "make your dreams a reality", "the sky's the limit".

REQUIRED — every caption must include at least ONE of:
- A specific Enderun fact (Les Roches #3 globally, École Ducasse / Alain Ducasse, 30+ countries internship, BGC campus, class size 20-25)
- A real number (slots, countries, ranking, years)
- A sensory or visual detail that matches what's in the image
- A Taglish line that sounds natural for the Filipino audience

TONE AND FORMAT:
- Short punchy sentences. Line breaks for breathing room. No walls of text.
- Facebook: conversational, warmer, Taglish welcome, 3-5 short paragraphs, 5-10 hashtags
- Instagram: lifestyle-first, one strong hook, cleaner format, 15-20 hashtags
- Hashtags on their own line at the bottom — never mid-caption
- Always end with a CTA: "Apply now.", "Book a tour.", "DM us.", "Link in bio."
- URL on its own line after CTA when relevant
"""

BROWSER_INSTRUCTIONS = """
=== BROWSER AUTOMATION ===
You have full control of a real Chromium browser. Use it whenever the user asks you to
open, visit, browse, check, or interact with any website or visual web content.

=== WHEN TO USE THE BROWSER (trigger it immediately, no need to ask) ===
- "buksan mo Google" / "open Google" → goto https://www.google.com
- "buksan mo YouTube" / "open YouTube" → goto https://www.youtube.com
- "anong weather ngayon" / "check the weather" / "weather in Manila" →
    goto https://www.google.com/search?q=weather+Manila+Philippines
- "i-open mo yung website ng [school/company]" → goto their website
- "buksan mo yung Facebook ng CCA" → goto https://www.facebook.com/ccamanila
- "i-check mo yung [any website].com" → goto that URL
- "search mo sa Google yung [topic]" → goto Google, type into search bar
- Any request to "open", "buksan", "i-open", "visit", "go to", "look at" a website
- Any visual/interactive task that requires seeing a webpage

=== HOW TO USE ===
1. Immediately output a browser trigger on the LAST LINE of your message:
   [BROWSER:{"action":"goto","url":"https://example.com"}]

2. The bot runs the action, takes a screenshot, sends it to the user, and sends it back to you.
   Describe what you see in 1-2 lines, then output the next trigger (or stop if done).

3. Keep chaining triggers until the task is complete.
   Stop chaining (no trigger) when done — give a plain summary of what was accomplished.

=== AVAILABLE ACTIONS ===
  {"action":"goto","url":"https://..."}                           — navigate to URL
  {"action":"click","selector":"CSS-selector"}                    — click element
  {"action":"type","selector":"CSS-selector","text":"your text"}  — type into input
  {"action":"press","key":"Enter"}                                — keyboard key
  {"action":"scroll","x":0,"y":400}                              — scroll page (y+ = down)
  {"action":"wait","ms":1000}                                     — pause in milliseconds
  {"action":"screenshot"}                                         — capture current state
  {"action":"close"}                                              — close browser tab

=== RULES ===
- ALWAYS place [BROWSER:...] alone on the very LAST line of your message.
- For Google Search: goto https://www.google.com/search?q=your+search+terms (skip typing).
- After goto, describe what you see in the screenshot before deciding the next action.
- Never ask the user to do something in the browser — Eva does it herself.
- Max 15 steps per task. If you hit the limit, summarize what was done.
- If a page fails to load or shows an error, try an alternative URL or explain the issue.
"""

def build_system_prompt(agent_name, user_id: int = None) -> str:
    now_pht = datetime.now(PHT)
    base = (
        "You are Eva — the Enderun Marketing AI for the Enderun Colleges marketing team.\n\n"
        f"Current date and time: {now_pht.strftime('%A, %B %d, %Y %I:%M %p')} PHT\n\n"
        f"{EVA_IDENTITY}\n"
        f"{CAPTION_STYLE}\n"
        f"=== BRAND CONTEXT ===\n{BRAND_CONTEXT}\n"
    )

    # Live business context — leads, schedule, enrollment season
    live_ctx = _build_live_context()
    if live_ctx:
        base += f"\n=== LIVE BUSINESS CONTEXT ===\n{live_ctx}\n"

    # Persistent user memories — facts Eva has asked the bot to remember
    if user_id:
        memories = get_user_state(user_id).get("memories", [])
        if memories:
            mem_lines = "\n".join(f"- {m['text']}" for m in memories)
            base += f"\n=== EVA'S NOTES (always keep in mind) ===\n{mem_lines}\n"

    # Recent caption history — avoid repeating the same hooks/angles
    if user_id:
        caption_hist = get_user_state(user_id).get("caption_history", [])
        if caption_hist:
            recent = "\n".join(
                f"- [{c['platform']} {c['date']}] {c['caption'][:120]}"
                for c in caption_hist[:3]
            )
            base += f"\n=== RECENT CAPTIONS (do NOT reuse the same opening hooks or angles) ===\n{recent}\n"

    if agent_name:
        content = load_agent(agent_name)
        if content:
            base += f"\n=== YOUR CURRENT ROLE ===\n{content}\n"
        base += f"\nYou are currently acting as Eva in the {agent_name} agent role."
    else:
        base += "\nYou are Eva — general Enderun Marketing AI, ready to help across all areas."

    # Always inject testing agent rules so demo post behavior is always correct
    testing_agent = load_agent("testing")
    if testing_agent:
        base += f"\n=== DEMO POSTING RULES (always apply when posting) ===\n{testing_agent}\n"
    base += TRIGGER_INSTRUCTIONS
    base += BROWSER_INSTRUCTIONS
    return base

# ===========================================================================
# KEYBOARD BUILDERS
# ===========================================================================
def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Leads Dashboard",   callback_data="leads"),
         InlineKeyboardButton("✨ Morning Briefing",   callback_data="briefing")],
        [InlineKeyboardButton("🔵 Post to Facebook",  callback_data="qpost:facebook"),
         InlineKeyboardButton("🟣 Post to Instagram", callback_data="qpost:instagram")],
        [InlineKeyboardButton("👁 Social Listening",  callback_data="workflow:social-listening"),
         InlineKeyboardButton("📈 Analytics Report",  callback_data="workflow:analytics-report")],
        [InlineKeyboardButton("🗓 Weekly Preview",    callback_data="workflow:weekly-preview"),
         InlineKeyboardButton("💌 Email All Leads",   callback_data="qpost:drip-all")],
        [InlineKeyboardButton("⚡ Quick Report",      callback_data="quick_report")],
    ])

def post_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve & Post",  callback_data="confirm"),
         InlineKeyboardButton("↺ Regenerate",      callback_data="regen")],
        [InlineKeyboardButton("✏ Edit Caption",    callback_data="edit_caption"),
         InlineKeyboardButton("✕ Cancel",           callback_data="cancel")],
    ])

def save_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬆ Save to GitHub", callback_data="save_output"),
    ]])

def drip_confirm_keyboard(active_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Send to {active_count} leads", callback_data="drip_confirm"),
         InlineKeyboardButton("❌ Cancel",                        callback_data="drip_cancel")],
    ])

def lead_action_keyboard(email: str) -> InlineKeyboardMarkup:
    safe = email.replace("@", "__at__").replace(".", "__dot__")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Mark Inactive", callback_data=f"lead_inactive:{safe}"),
         InlineKeyboardButton("🟢 Reactivate",    callback_data=f"lead_activate:{safe}")],
    ])

def ab_caption_keyboard(has_prev: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🅰 Use Version A",  callback_data="ab_use:a"),
         InlineKeyboardButton("🅱 Use Version B",  callback_data="ab_use:b")],
        [InlineKeyboardButton("↺ Regen Both",      callback_data="ab_regen"),
         InlineKeyboardButton("✕ Cancel",           callback_data="cancel")],
    ]
    if has_prev:
        rows.insert(1, [InlineKeyboardButton("📋 Compare All Versions", callback_data="compare_versions")])
    return InlineKeyboardMarkup(rows)

def split_caption_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Post Both",     callback_data="split_post"),
         InlineKeyboardButton("↺ Regen Both",    callback_data="split_regen")],
        [InlineKeyboardButton("✏ Edit FB",       callback_data="split_edit:fb"),
         InlineKeyboardButton("✏ Edit IG",       callback_data="split_edit:ig")],
        [InlineKeyboardButton("✕ Cancel",         callback_data="cancel")],
    ])

def reschedule_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Move", callback_data="reschedule_confirm"),
         InlineKeyboardButton("❌ Cancel",       callback_data="cancel")],
    ])

def retry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 Social Listening",  callback_data="retry:social-listening"),
         InlineKeyboardButton("📈 Analytics Report",  callback_data="retry:analytics-report")],
        [InlineKeyboardButton("🗓 Weekly Preview",    callback_data="retry:weekly-preview"),
         InlineKeyboardButton("💌 Daily Post",        callback_data="retry:daily-post")],
    ])

def persistent_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["✨ Briefing", "📊 Leads", "📅 Today"],
         ["🔵 Post FB",  "🟣 Post IG", "👁 Listen"]],
        resize_keyboard=True, is_persistent=True,
    )

def leads_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("＋ Add Lead",      callback_data="nav:addlead"),
         InlineKeyboardButton("💌 Drip All",      callback_data="qpost:drip-all")],
        [InlineKeyboardButton("🔎 Look Up Lead",  callback_data="nav:lead_prompt"),
         InlineKeyboardButton("🔥 Hot Leads",     callback_data="leads_hot")],
    ])

def today_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗓 View Schedule", callback_data="nav:schedule"),
         InlineKeyboardButton("🔵 Post to FB",    callback_data="qpost:facebook")],
        [InlineKeyboardButton("↔ Reschedule",     callback_data="nav:reschedule_prompt")],
    ])

def post_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 View Schedule", callback_data="nav:schedule"),
         InlineKeyboardButton("📘 Post Again",    callback_data="nav:post_again")],
        [InlineKeyboardButton("🔄 Reschedule",    callback_data="nav:reschedule_prompt")],
    ])

def briefing_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Post to Facebook", callback_data="qpost:facebook"),
         InlineKeyboardButton("🟣 Post to Instagram",callback_data="qpost:instagram")],
        [InlineKeyboardButton("📊 Lead Stats",       callback_data="leads"),
         InlineKeyboardButton("💌 Drip All",         callback_data="qpost:drip-all")],
        [InlineKeyboardButton("⚡ Quick Report",     callback_data="quick_report")],
    ])

def photo_post_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Post to Facebook",   callback_data="photo_post:facebook"),
         InlineKeyboardButton("🟣 Post to Instagram",  callback_data="photo_post:instagram")],
        [InlineKeyboardButton("📤 Post to Both",        callback_data="photo_post:all"),
         InlineKeyboardButton("💾 Save to Drive",       callback_data="photo_post:drive")],
        [InlineKeyboardButton("❌ Just Analysis",        callback_data="photo_post:dismiss")],
    ])

def undo_lead_keyboard(email: str, prev_status: str) -> InlineKeyboardMarkup:
    safe = email.replace("@", "__at__").replace(".", "__dot__")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Undo", callback_data=f"undo_lead:{safe}:{prev_status}"),
    ]])

def undo_memory_keyboard(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Undo", callback_data=f"undo_memory:{idx}"),
    ]])

def clear_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, clear", callback_data="clear_confirm"),
        InlineKeyboardButton("❌ Keep it",    callback_data="clear_cancel"),
    ]])

def workflow_confirm_keyboard(workflow: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Run Now",  callback_data=f"wf_run:{workflow}"),
         InlineKeyboardButton("❌ Cancel",   callback_data="cancel")],
    ])

def image_picker_keyboard(options: list) -> InlineKeyboardMarkup:
    """Build image picker buttons 2-per-row for a compact layout."""
    rows = []
    row = []
    for i, (_, filename) in enumerate(options):
        # Strip extension and truncate for button label
        name = filename.rsplit(".", 1)[0]
        short = name[:18] + "…" if len(name) > 18 else name
        row.append(InlineKeyboardButton(f"🖼 {short}", callback_data=f"imgpick:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📤 Use my own image", callback_data="imgpick:own")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def agents_keyboard(current_agent, user_id: int = None) -> InlineKeyboardMarkup:
    agents = list_agents()
    rows, row = [], []
    # Recent agents row at top (up to 3)
    if user_id:
        recent = get_user_state(user_id).get("recent_agents", [])[:3]
        if recent:
            rows.append([InlineKeyboardButton(f"⭐ {a}", callback_data=f"agent:{a}") for a in recent])
    for a in agents:
        label = f"→ {a}" if a == current_agent else a
        row.append(InlineKeyboardButton(label, callback_data=f"agent:{a}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 General Assistant", callback_data="agent:general")])
    return InlineKeyboardMarkup(rows)

# ===========================================================================
# WORKFLOW DISPATCHERS
# ===========================================================================
async def trigger_github_post(update: Update, platform: str, email_to: str = "", caption: str = "", image: str = ""):
    if not GITHUB_PAT:
        await update.effective_message.reply_text("GITHUB_PAT is not set in Railway.")
        return
    label = {"facebook": "Facebook", "instagram": "Instagram",
             "email": "Email", "all": "FB + IG + Email"}.get(platform, platform)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/demo_post.yml/dispatches"
    payload = {"ref": "main", "inputs": {
        "platform": platform, "email_to": email_to,
        "email_name": "Demo Guest", "email_program": "BS Hospitality Management",
        "caption": caption,
        "image_filename": image,
    }}
    try:
        resp = requests.post(url, headers=GH_HEADERS(), json=payload, timeout=10)
        if resp.status_code == 204:
            await update.effective_message.reply_text(
                f"🚀 <b>Publishing to {html_module.escape(label)}</b> — ETA ~2 min.\n"
                f"📬 You'll get a Telegram notification when done.\n"
                f"🔗 <a href=\"https://github.com/{GITHUB_REPO}/actions\">View on GitHub Actions</a>",
                parse_mode=ParseMode.HTML,
                reply_markup=post_done_keyboard(),
            )
        else:
            await update.effective_message.reply_text(
                f"❌ <b>GitHub returned {resp.status_code}</b>\n<code>{html_module.escape(resp.text[:200])}</code>",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Could not trigger post</b>\n<code>{html_module.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )

async def trigger_drip_all(update: Update):
    if not GITHUB_PAT:
        await update.effective_message.reply_text("GITHUB_PAT is not set in Railway.")
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/send_drip_emails.yml/dispatches"
    try:
        resp = requests.post(url, headers=GH_HEADERS(), json={"ref": "main"}, timeout=10)
        if resp.status_code == 204:
            await update.effective_message.reply_text(
                "📨 <b>Sending drip emails to all active leads</b>\n"
                "⚠️ Sequence counters will NOT be updated.\n"
                f"⏳ ETA ~3 min.\n"
                f"🔗 <a href=\"https://github.com/{GITHUB_REPO}/actions\">View on GitHub Actions</a>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.effective_message.reply_text(
                f"❌ <b>GitHub returned {resp.status_code}</b>",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Error triggering drip</b>: <code>{html_module.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )

async def trigger_named_workflow(update: Update, workflow_file: str, label: str):
    if not GITHUB_PAT:
        await update.effective_message.reply_text("GITHUB_PAT is not set in Railway.")
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
    try:
        resp = requests.post(url, headers=GH_HEADERS(), json={"ref": "main"}, timeout=10)
        if resp.status_code == 204:
            await update.effective_message.reply_text(
                f"🚀 {label} triggered.\n"
                f"⏳ Running on GitHub Actions — you'll get a notification when done.\n"
                f"🔗 https://github.com/{GITHUB_REPO}/actions"
            )
        else:
            await update.effective_message.reply_text(f"❌ GitHub returned {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {e}")

# ===========================================================================
# SHARED REPLY HELPERS
# ===========================================================================
TRIGGER_RE = re.compile(
    r'\[TRIGGER:(facebook|instagram|email|all|drip-all|social-listening|analytics-report|weekly-preview|reschedule)(?::([^\]]+))?\]',
    re.IGNORECASE,
)
BROWSER_RE = re.compile(r'\[BROWSER:(\{[^\]]*\})\]', re.DOTALL)

WORKFLOW_TRIGGERS = {"social-listening", "analytics-report", "weekly-preview", "drip-all", "reschedule"}
WORKFLOW_MAP = {
    "social-listening": ("social_listening.yml",  "Social Listening"),
    "analytics-report": ("weekly_analytics.yml",  "Analytics Report"),
    "weekly-preview":   ("weekly_preview.yml",    "Weekly Campaign Preview"),
}

def strip_md(text: str) -> str:
    """Remove markdown formatting chars so caption is clean plain text."""
    return re.sub(r'[*_~`]', '', text).strip()

def md_to_html(text: str) -> str:
    """Convert Claude markdown output to Telegram-safe HTML."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text, flags=re.DOTALL)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text, flags=re.DOTALL)
    text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    return text

def _greeting(first_name: str = "") -> str:
    """Return a time-aware greeting based on PHT hour."""
    hour = datetime.now(PHT).hour
    if 5 <= hour < 12:
        tod, icon = "Good morning", "☀️"
    elif 12 <= hour < 18:
        tod, icon = "Good afternoon", "🌤"
    elif 18 <= hour < 22:
        tod, icon = "Good evening", "🌙"
    else:
        tod, icon = "Hey", "✨"
    name_part = f", {first_name}" if first_name else ""
    return f"{tod}{name_part}! {icon}"

# ===========================================================================
# SESSION ACTION TRACKING — for /summary
# ===========================================================================
def _track_action(session: dict, action: str):
    """Append a timestamped action to the session log."""
    if "actions" not in session:
        session["actions"] = []
    ts = datetime.now(PHT).strftime("%I:%M %p")
    session["actions"].append(f"[{ts}] {action}")
    if len(session["actions"]) > 20:
        session["actions"] = session["actions"][-20:]

# ===========================================================================
# INLINE TIPS — shown at most once per tip per session
# ===========================================================================
import random as _random

_TIPS = [
    "💡 <b>Tip:</b> Send a photo to analyze it or use it as a post image.",
    "💡 <b>Tip:</b> Say <i>\"ilipat yung Apr 18 post to Apr 20\"</i> to reschedule naturally.",
    "💡 <b>Tip:</b> Use /remember to save notes the bot will always keep in mind.",
    "💡 <b>Tip:</b> Voice messages work! Press the mic and speak your request.",
    "💡 <b>Tip:</b> /lastposts shows your last 5 captions — great to review before posting.",
    "💡 <b>Tip:</b> Say <i>\"post to all\"</i> to get separate FB + IG captions in one go.",
    "💡 <b>Tip:</b> Switch agents with /agent — each has specialized marketing knowledge.",
    "💡 <b>Tip:</b> /retry lets you re-run any workflow that failed.",
]

def _maybe_send_tip(session: dict) -> str | None:
    """Return a tip string or None. Each tip shown at most once per session."""
    shown = session.setdefault("tips_shown", set())
    remaining = [i for i in range(len(_TIPS)) if i not in shown]
    if not remaining or _random.random() > 0.25:
        return None
    idx = _random.choice(remaining)
    shown.add(idx)
    return _TIPS[idx]

async def _do_dispatch(update: Update, action: str, email_to: str = "", caption: str = "", image: str = ""):
    if action == "drip-all":
        await trigger_drip_all(update)
    elif action in WORKFLOW_MAP:
        wf_file, wf_label = WORKFLOW_MAP[action]
        await trigger_named_workflow(update, wf_file, wf_label)
    else:
        await trigger_github_post(update, action, email_to, caption, image)

# ===========================================================================
# EVA VOICE OUTPUT (edge-tts — Microsoft Neural TTS, no API key needed)
# ===========================================================================
EVA_VOICE_EN  = "en-US-JennyNeural"       # warm, natural English
EVA_VOICE_FIL = "fil-PH-BlessicaNeural"   # Filipino / Tagalog

async def _generate_voice(text: str, lang: str = "en") -> bytes:
    """Generate MP3 audio from text via edge-tts. Returns empty bytes on failure."""
    try:
        import edge_tts
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'[*_`~#>|]', '', clean)
        clean = re.sub(r'https?://\S+', 'link', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()[:900]
        voice = EVA_VOICE_FIL if lang == "fil" else EVA_VOICE_EN
        communicate = edge_tts.Communicate(clean, voice)
        chunks = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks += chunk["data"]
        return chunks
    except Exception as e:
        logging.warning(f"TTS generate error: {e}")
        return b""

async def _maybe_send_voice(update: Update, text: str, user_id: int):
    """Send voice audio after a reply if voice mode is ON for this user."""
    session = get_session(user_id)
    if not session.get("voice_mode"):
        return
    lang = session.get("voice_lang", "en")
    audio = await _generate_voice(text, lang)
    if not audio:
        return
    buf = io.BytesIO(audio)
    buf.name = "eva.mp3"
    try:
        await update.effective_message.reply_voice(voice=buf)
    except Exception:
        buf.seek(0)
        try:
            await update.effective_message.reply_audio(
                audio=buf, filename="eva.mp3", title="Eva", performer="Enderun AI"
            )
        except Exception as e:
            logging.warning(f"Voice send failed: {e}")

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle Eva voice output. /voice | /voice english | /voice filipino | /voice off"""
    session = get_session(update.effective_user.id)
    args = [a.lower() for a in (context.args or [])]

    if args and args[0] in ("off", "stop", "mute"):
        session["voice_mode"] = False
        await update.message.reply_text("🔇 Voice mode OFF — Eva will reply in text only.")
        return

    if args and args[0] in ("english", "en"):
        session["voice_lang"] = "en"
        session["voice_mode"] = True
    elif args and args[0] in ("filipino", "fil", "tagalog", "ph"):
        session["voice_lang"] = "fil"
        session["voice_mode"] = True
    else:
        session["voice_mode"] = not session.get("voice_mode", False)

    if session["voice_mode"]:
        lang = session.get("voice_lang", "en")
        label = "Filipino (Blessica Neural)" if lang == "fil" else "English (Jenny Neural)"
        await update.message.reply_text(
            f"🔊 <b>Voice mode ON</b> — {label}\n\n"
            "Eva will now read her replies aloud as voice messages.\n\n"
            "<b>Options:</b>\n"
            "/voice english — Switch to English voice\n"
            "/voice filipino — Switch to Filipino voice\n"
            "/voice off — Turn off",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("🔇 Voice mode OFF.")

async def _send_reply(update: Update, text: str, reply_markup=None):
    html = md_to_html(text)
    chunks = [html[i:i+4000] for i in range(0, max(len(html), 1), 4000)]
    for i, chunk in enumerate(chunks):
        km = reply_markup if i == len(chunks) - 1 else None
        try:
            await update.effective_message.reply_text(
                chunk, reply_markup=km, parse_mode=ParseMode.HTML
            )
        except Exception:
            plain = re.sub(r'<[^>]+>', '', chunk)
            await update.effective_message.reply_text(plain, reply_markup=km)

async def _call_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict):
    user_id = update.effective_user.id
    lock = _get_user_lock(user_id)
    if lock.locked():
        await update.effective_message.reply_text("⏳ Still working on your last request… please wait.")
        return
    async with lock:
        await _call_and_reply_inner(update, context, session)

async def _call_and_reply_inner(update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict):
    user_id = update.effective_user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    # Show a progress message for first reply or when history is short (fresh context)
    progress_msg = None
    if len(session.get("history", [])) <= 2:
        try:
            progress_msg = await update.effective_message.reply_text("⏳ Thinking with Opus 4.7…")
        except Exception:
            pass
    try:
        model  = _select_model(session["agent"])
        reply  = call_claude_with_tools(
            build_system_prompt(session["agent"], user_id=user_id),
            session["history"],
            model=model,
        )
        if progress_msg:
            try:
                await progress_msg.delete()
            except Exception:
                pass
            progress_msg = None
        m = TRIGGER_RE.search(reply)
        if m:
            action   = m.group(1).lower()
            email_to = (m.group(2) or "").strip()
            content_before = reply[:m.start()].strip()
            # Save user's original prompt before removing it from history
            last_user = session["history"][-1]["content"] if session["history"] else ""
            if isinstance(last_user, list):
                last_user = next((b.get("text","") for b in last_user if b.get("type")=="text"), "")
            session["history"].pop()   # remove user msg — no trigger codes in history

            # Workflow triggers
            if action in WORKFLOW_TRIGGERS:
                if action == "reschedule":
                    # Parse "YYYY-MM-DD:YYYY-MM-DD" from email_to field (group 2)
                    parts = email_to.split(":") if email_to else []
                    if len(parts) < 2:
                        await update.effective_message.reply_text(
                            "Could not parse dates from reschedule trigger. "
                            "Please try again with a clearer date (e.g. \"ilipat Apr 18 to Apr 20\")."
                        )
                        return
                    from_date, to_date = parts[0].strip(), parts[1].strip()
                    today_str = datetime.now(PHT).strftime("%Y-%m-%d")
                    if to_date < today_str:
                        await update.effective_message.reply_text(
                            f"⚠️ {to_date} is in the past. Please choose a future date."
                        )
                        return
                    # Fetch what's on from_date to show in confirmation
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                    raw = github_read_file("posting_schedule.json")
                    filename = ""
                    conflict = ""
                    if not raw.startswith("Error"):
                        try:
                            sched    = json.loads(raw).get("schedule", {})
                            filename = sched.get(from_date, "")
                            conflict = sched.get(to_date, "")
                        except Exception as e:
                            logging.warning(f"[reschedule nlp] schedule parse: {e}")
                    if not filename:
                        await update.effective_message.reply_text(
                            f"No post scheduled for {from_date}."
                        )
                        return
                    session["pending"] = {
                        "action": "reschedule",
                        "from_date": from_date,
                        "to_date": to_date,
                        "filename": filename,
                    }
                    conflict_note = f"\n⚠️ {conflict} is already on {to_date} — it will be replaced." if conflict else ""
                    await update.effective_message.reply_text(
                        f"📅 Move this post?\n\n"
                        f"📸 {filename}\n"
                        f"From: {from_date}\n"
                        f"To:   {to_date}"
                        f"{conflict_note}",
                        reply_markup=reschedule_confirm_keyboard(),
                    )
                    return
                if action == "drip-all":
                    leads  = parse_leads_csv()
                    active = sum(1 for l in leads if l.get("status", "").lower() == "active")
                    await update.effective_message.reply_text(
                        f"📨 Send drip emails to all active leads?\n\n"
                        f"👥 Active leads: {active}\n"
                        f"⚠️ Sequence counters will NOT be updated.",
                        reply_markup=drip_confirm_keyboard(active),
                    )
                elif action == "weekly-preview":
                    # Show schedule summary + approval buttons
                    summary = _weekly_preview_summary()
                    await update.effective_message.reply_text(
                        summary, reply_markup=workflow_confirm_keyboard("weekly-preview")
                    )
                else:
                    await _do_dispatch(update, action, email_to)
                return

            # Post triggers → let user pick which image to use
            label = {"facebook": "Facebook", "instagram": "Instagram",
                     "email": "Email", "all": "FB + IG + Email"}.get(action, action)

            # Load all images from Google Drive folder
            img_options = []
            try:
                from drive_helper import list_images
                filenames = list_images()
                img_options = [("", fn) for fn in filenames]
            except Exception as e:
                logging.warning(f"Could not list Drive images: {e}")

            # Store intent while user picks image
            session["pending"] = {"action": action, "email_to": email_to, "caption": "", "prompt": last_user}
            session["img_options"] = img_options

            if not img_options:
                await update.effective_message.reply_text(
                    "⚠️ Could not load images from Google Drive. Make sure GOOGLE_DRIVE_CREDENTIALS and GOOGLE_DRIVE_FOLDER_ID are set in Railway."
                )
                return

            await update.effective_message.reply_text(
                f"📸 Choose an image for the {label} post:",
                reply_markup=image_picker_keyboard(img_options),
            )
            return

        # -----------------------------------------------------------------------
        # BROWSER AUTOMATION LOOP
        # -----------------------------------------------------------------------
        bm = BROWSER_RE.search(reply)
        if bm:
            for step in range(MAX_BROWSER_STEPS):
                cmd_str = bm.group(1)
                try:
                    cmd = json.loads(cmd_str)
                except Exception:
                    await update.effective_message.reply_text(
                        f"⚠️ Could not parse browser command: <code>{html_module.escape(cmd_str)}</code>",
                        parse_mode=ParseMode.HTML,
                    )
                    session["history"].append({"role": "assistant", "content": reply})
                    break

                # Send any explanatory text before the trigger
                text_before = reply[:bm.start()].strip()
                if text_before:
                    await _send_reply(update, text_before)

                action_name = cmd.get("action", "screenshot")

                # "close" — close tab and exit loop
                if action_name == "close":
                    await _close_user_page(user_id)
                    session["history"].append({"role": "assistant", "content": reply})
                    await update.effective_message.reply_text("🌐 Browser tab closed.")
                    break

                # Execute action
                status_msg = await update.effective_message.reply_text(
                    f"🌐 Step {step + 1}: <i>{html_module.escape(action_name)}</i>…",
                    parse_mode=ParseMode.HTML,
                )
                try:
                    screenshot_bytes = await _browser_action(user_id, cmd)
                except Exception as be:
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                    await update.effective_message.reply_text(
                        f"❌ Browser error: <code>{html_module.escape(str(be))}</code>",
                        parse_mode=ParseMode.HTML,
                    )
                    session["history"].append({"role": "assistant", "content": reply})
                    break
                try:
                    await status_msg.delete()
                except Exception:
                    pass

                # Send screenshot to user
                url_hint = cmd.get("url", "")
                caption = f"🌐 Step {step + 1} — {action_name}" + (f": {url_hint}" if url_hint else "")
                await update.effective_message.reply_photo(
                    photo=io.BytesIO(screenshot_bytes),
                    caption=caption,
                )

                # Append assistant message + screenshot as next user message
                session["history"].append({"role": "assistant", "content": reply})
                img_b64 = base64.b64encode(screenshot_bytes).decode()
                session["history"].append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                        },
                        {
                            "type": "text",
                            "text": "Here is the current state of the browser. Continue with the next step, or give a final summary if you are done.",
                        },
                    ],
                })

                # Call Claude again
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                reply = call_claude_with_tools(
                    build_system_prompt(session["agent"], user_id=user_id),
                    session["history"],
                    model=model,
                )

                bm = BROWSER_RE.search(reply)
                if not bm:
                    # No more browser actions — final summary
                    session["history"].append({"role": "assistant", "content": reply})
                    await _send_reply(update, reply)
                    await _maybe_send_voice(update, reply, user_id)
                    break
            else:
                # Reached MAX_BROWSER_STEPS
                session["history"].append({"role": "assistant", "content": reply})
                await update.effective_message.reply_text(
                    f"⚠️ Reached max browser steps ({MAX_BROWSER_STEPS}). Stopping automation."
                )

            ustate = get_user_state(user_id)
            ustate["history"] = session["history"][-10:]
            save_bot_state()
            return
        # -----------------------------------------------------------------------

        session["history"].append({"role": "assistant", "content": reply})
        # Persist last 10 messages to bot_state so history survives Railway restarts
        ustate = get_user_state(update.effective_user.id)
        ustate["history"] = session["history"][-10:]
        save_bot_state()
        # Track this exchange for /summary
        last_user_msg = ""
        for msg in reversed(session["history"][:-1]):
            if msg["role"] == "user":
                c = msg["content"]
                last_user_msg = (c if isinstance(c, str) else next((b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text"), ""))[:60]
                break
        if last_user_msg:
            _track_action(session, f"Asked: {last_user_msg}")
        # Show save button for substantive agent outputs (long responses when in agent mode)
        if session.get("agent") and len(reply) > 400:
            await _send_reply(update, reply, reply_markup=save_keyboard())
        else:
            await _send_reply(update, reply)
        # Voice output if enabled
        await _maybe_send_voice(update, reply, user_id)
        # Occasional inline tip
        tip = _maybe_send_tip(session)
        if tip:
            await update.effective_message.reply_text(tip, parse_mode=ParseMode.HTML)
    except anthropic.APIStatusError as e:
        if progress_msg:
            try: await progress_msg.delete()
            except Exception: pass
        if e.status_code == 529:
            await update.effective_message.reply_text(
                "😓 <b>Claude is really busy right now.</b>\n\n"
                "This happens during peak hours. Please try again in 30 seconds!",
                parse_mode=ParseMode.HTML,
            )
        elif e.status_code in (401, 403):
            await update.effective_message.reply_text(
                "🔑 <b>API key issue.</b> Check that ANTHROPIC_API_KEY is set correctly in Railway.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.effective_message.reply_text(
                f"⚠️ <b>Something went wrong on Claude's end</b> (error {e.status_code}).\n"
                f"Please try again in a moment.",
                parse_mode=ParseMode.HTML,
            )
        logging.error(f"Claude API error: {e}")
    except Exception as e:
        if progress_msg:
            try: await progress_msg.delete()
            except Exception: pass
        err_str = str(e).lower()
        if "network" in err_str or "connect" in err_str or "timeout" in err_str:
            msg = "📡 <b>Connection trouble.</b>\nCouldn't reach the server. Check your internet and try again."
        elif "github" in err_str:
            msg = "🐙 <b>GitHub sync issue.</b>\nThe repo is temporarily unavailable. Try again in a moment."
        else:
            msg = "😬 <b>Oops, something went wrong.</b>\nPlease try again — if it keeps happening, use /clear to reset."
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
        logging.error(f"Error in _call_and_reply: {e}")

# ===========================================================================
# SCHEDULE HELPER
# ===========================================================================
async def _post_own_image(update: Update, platform: str, caption: str, img_bytes: bytes):
    """Upload user's own image to imgBB and post directly to Zapier (no GitHub Actions)."""
    IMGBB_KEY  = os.environ.get("IMGBB_API_KEY", "")
    FB_WEBHOOK = os.environ.get("FB_ZAPIER_WEBHOOK", "")
    IG_WEBHOOK = os.environ.get("INSTAGRAM_ZAPIER_WEBHOOK", "")
    label = {"facebook": "Facebook", "instagram": "Instagram",
             "email": "Email", "all": "FB + IG + Email"}.get(platform, platform)
    try:
        # Upload to imgBB for a public URL
        if not IMGBB_KEY:
            await update.effective_message.reply_text("IMGBB_API_KEY not set in Railway — cannot post own image.")
            return
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": IMGBB_KEY},
            files={"image": ("post.jpg", img_bytes, "image/jpeg")},
            timeout=30,
        )
        image_url = resp.json()["data"]["url"]
        payload   = {"caption": caption, "full_message": caption, "image_url": image_url}

        ok = False
        if platform in ("facebook", "all") and FB_WEBHOOK:
            r = requests.post(FB_WEBHOOK, json=payload, timeout=15)
            ok = r.status_code == 200
        if platform in ("instagram", "all") and IG_WEBHOOK:
            ig_payload = {"caption": caption, "full_caption": caption, "image_url": image_url}
            r = requests.post(IG_WEBHOOK, json=ig_payload, timeout=15)
            ok = r.status_code == 200

        if ok:
            await update.effective_message.reply_text(f"✅ Posted to {label} with your image!")
        else:
            await update.effective_message.reply_text(f"⚠️ Zapier returned an error. Check your webhooks.")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error posting own image: {e}")

def _download_scheduled_image(filename: str) -> bytes | None:
    """Download scheduled image from Google Drive. Returns bytes or None."""
    try:
        from drive_helper import download_by_name
        return download_by_name(filename)
    except Exception as e:
        logging.debug(f"Could not download image '{filename}': {e}")
        return None

def reschedule_post(from_date: str, to_date: str) -> dict:
    """
    Move a scheduled post from from_date to to_date in posting_schedule.json.
    Returns {"ok": bool, "message": str, "filename": str, "conflict": str}
    """
    raw = github_read_file("posting_schedule.json")
    if raw.startswith("Error") or raw.startswith("File not found"):
        return {"ok": False, "message": f"Could not read schedule: {raw}", "filename": "", "conflict": ""}
    try:
        data     = json.loads(raw)
        schedule = data.get("schedule", {})
    except Exception:
        return {"ok": False, "message": "Could not parse posting_schedule.json.", "filename": "", "conflict": ""}

    if from_date not in schedule:
        return {"ok": False, "message": f"No post scheduled for {from_date}.", "filename": "", "conflict": ""}

    filename = schedule[from_date]
    conflict = schedule.get(to_date, "")

    del schedule[from_date]
    schedule[to_date] = filename
    data["schedule"]  = dict(sorted(schedule.items()))

    result = github_write_file(
        "posting_schedule.json",
        json.dumps(data, indent=2),
        f"Reschedule: {filename} {from_date} → {to_date} [skip ci]",
    )
    if "Error" in result:
        return {"ok": False, "message": f"Could not save: {result}", "filename": filename, "conflict": conflict}

    _live_ctx_cache["ts"] = 0  # invalidate cache so next message shows updated schedule
    msg = f"✅ Rescheduled!\n\n📸 {filename}\n📅 {from_date} → {to_date}"
    if conflict:
        msg += f"\n\n⚠️ {conflict} was on {to_date} and has been replaced."
    return {"ok": True, "message": msg, "filename": filename, "conflict": conflict}

async def _try_send_image_preview(update: Update, filename: str, img_bytes: bytes = None) -> bool:
    """Send image as Telegram photo. Downloads from Drive if img_bytes not provided."""
    try:
        if img_bytes is None:
            img_bytes = _download_scheduled_image(filename)
        if img_bytes:
            await update.effective_message.reply_photo(photo=img_bytes, caption=f"📸 {filename}")
            return True
    except Exception as e:
        logging.debug(f"Image preview send failed: {e}")
    return False

def _generate_vision_caption(platform: str, img_bytes: bytes, user_prompt: str = "", user_id: int = None) -> str:
    """Call Claude Vision on the actual scheduled image to generate a matching caption."""
    import time
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system = build_system_prompt(None, user_id=user_id)
    context_hint = f" The user's request context: {user_prompt}" if user_prompt else ""
    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(img_bytes).decode("ascii")}},
        {"type": "text", "text": (
            f"Generate a {platform} post caption for this image.\n"
            f"{context_hint}\n\n"
            f"Rules (strictly enforced):\n"
            f"- Look at the image carefully. What is actually happening in it? Lead with that specific detail.\n"
            f"- Do NOT use any banned openers from your caption style rules.\n"
            f"- Include at least one specific Enderun fact (ranking, country count, affiliation, BGC location).\n"
            f"- Sound like a real person wrote this, not an AI. Natural, specific, warm.\n"
            f"- Write ONLY the caption — no labels, no 'Here is the caption:', no headers. Start with the first word."
        )},
    ]
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL, max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            return next((b.text for b in resp.content if hasattr(b, "text")), "").strip()
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            break
        except Exception:
            break
    return ""

def _generate_vision_captions_ab(platform: str, img_bytes: bytes, user_prompt: str = "", user_id: int = None) -> tuple:
    """Generate two caption versions — A (aspirational hook) and B (question hook)."""
    import time
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system = build_system_prompt(None, user_id=user_id)
    hint   = f" Context: {user_prompt}" if user_prompt else ""
    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(img_bytes).decode("ascii")}},
        {"type": "text", "text": (
            f"Generate TWO different {platform} post captions for this image.{hint}\n\n"
            f"First, look at the image carefully. What is specifically happening — who's there, what are they doing, where does it look like? Use that as your anchor.\n\n"
            f"VERSION A — BOLD STATEMENT: Open with a confident, specific declaration rooted in what you see in the image. NOT generic. NOT a banned opener. Should feel like something a real Filipino marketer would actually post.\n\n"
            f"VERSION B — CONVERSATIONAL HOOK: Open with a natural, relatable question or observation. Taglish welcome if it sounds authentic. Ground it in the specific image detail.\n\n"
            f"Both versions must: avoid all banned openers, include at least one real Enderun fact or number, end with a clear CTA, follow platform format rules.\n\n"
            f"Respond in EXACTLY this format — no extra text:\n"
            f"VERSION_A:\n[full caption A here]\n\nVERSION_B:\n[full caption B here]"
        )},
    ]
    for attempt in range(3):
        try:
            resp  = client.messages.create(model=CLAUDE_OPUS_MODEL, max_tokens=1800,
                                           system=system, messages=[{"role":"user","content":user_content}])
            text  = next((b.text for b in resp.content if hasattr(b,"text")), "").strip()
            if "VERSION_A:" in text and "VERSION_B:" in text:
                parts = text.split("VERSION_B:", 1)
                return parts[0].replace("VERSION_A:","").strip(), parts[1].strip()
            return text, text
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            break
        except Exception:
            break
    return "", ""


def _generate_split_captions(img_bytes: bytes, user_prompt: str = "", user_id: int = None) -> tuple:
    """Generate separate Facebook and Instagram captions for the same image."""
    import time
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system = build_system_prompt(None, user_id=user_id)
    hint   = f" Context: {user_prompt}" if user_prompt else ""
    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(img_bytes).decode("ascii")}},
        {"type": "text", "text": (
            f"Generate two captions for this image: one for Facebook, one for Instagram.{hint}\n\n"
            f"Before writing, study the image: What is specifically happening? Who's there? What details stand out?\n"
            f"Anchor both captions in those specific visual details — not generic Enderun talking points.\n\n"
            f"FACEBOOK: Warm and conversational. Taglish welcome — sound like a real Enderun colleague posting, not a brand account. 3-4 short paragraphs. Specific Enderun fact in the body. End with a CTA. 5-10 hashtags on their own line.\n\n"
            f"INSTAGRAM: Hook first — one punchy line that makes someone stop scrolling. Lifestyle tone. Tight format with line breaks. 15-20 hashtags on their own line at the bottom.\n\n"
            f"Both: no banned openers, no filler phrases, must include at least one real number or specific credential.\n\n"
            f"Respond in EXACTLY this format — no extra text:\n"
            f"FACEBOOK:\n[full FB caption here]\n\nINSTAGRAM:\n[full IG caption here]"
        )},
    ]
    for attempt in range(3):
        try:
            resp  = client.messages.create(model=CLAUDE_OPUS_MODEL, max_tokens=1800,
                                           system=system, messages=[{"role":"user","content":user_content}])
            text  = next((b.text for b in resp.content if hasattr(b,"text")), "").strip()
            if "FACEBOOK:" in text and "INSTAGRAM:" in text:
                parts = text.split("INSTAGRAM:", 1)
                return parts[0].replace("FACEBOOK:","").strip(), parts[1].strip()
            return text, text
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            break
        except Exception:
            break
    return "", ""


def _weekly_preview_summary() -> str:
    """Build a text summary of the next 7 days of scheduled posts for approval."""
    try:
        raw = github_read_file("posting_schedule.json")
        schedule = json.loads(raw).get("schedule", {})
    except Exception as e:
        logging.warning(f"[weekly_preview_summary] {e}")
        schedule = {}
    today = datetime.now(PHT).strftime("%Y-%m-%d")
    lines = ["📅 Upcoming 7-day post schedule:\n"]
    count = 0
    for date_str in sorted(schedule.keys()):
        if date_str >= today:
            filename = schedule[date_str].rsplit(".", 1)[0]  # strip extension
            lines.append(f"  {date_str} — {filename}")
            count += 1
        if count >= 7:
            break
    if count == 0:
        lines.append("  (no posts scheduled for the next 7 days)")
    leads = parse_leads_csv()
    active = sum(1 for l in leads if l.get("status", "").lower() == "active")
    lines.append(f"\n👥 Active leads: {active} (will appear in drip email schedule)")
    lines.append("\nRun weekly preview PDF?")
    return "\n".join(lines)

def get_scheduled_image_name() -> str:
    """Return filename (and date if not today) of the next scheduled image."""
    raw = github_read_file("posting_schedule.json")
    if raw.startswith("Error") or raw.startswith("File not found"):
        return ""
    try:
        schedule = json.loads(raw).get("schedule", {})
        today = datetime.now(PHT).strftime("%Y-%m-%d")
        for date_str in sorted(schedule.keys()):
            if date_str >= today:
                name = schedule[date_str]
                return name if date_str == today else f"{name} (scheduled {date_str})"
    except Exception as e:
        logging.warning(f"[get_scheduled_image_name] {e}")
    return ""

# ===========================================================================
# LEADS HELPERS
# ===========================================================================
def parse_leads_csv() -> list:
    raw = github_read_file("leads.csv")
    if raw.startswith("Error") or raw.startswith("File not found"):
        return []
    try:
        return list(csv.DictReader(io.StringIO(raw)))
    except Exception:
        return []

def _score_lead(row: dict) -> tuple:
    """Return (score_int, emoji_label) based on email_count and status."""
    if row.get("status", "").lower() != "active":
        return 0, "💤 Dormant"
    try:
        count = int(row.get("email_count", 0))
    except (ValueError, TypeError):
        count = 0
    if count >= 10:
        return 3, "🔥 Hot"
    if count >= 5:
        return 2, "♨️ Warm"
    return 1, "🧊 Cold"

def format_leads_summary(leads: list) -> str:
    if not leads:
        return "No leads found or leads.csv is empty."
    total    = len(leads)
    active   = sum(1 for l in leads if l.get("status", "").lower() == "active")
    inactive = total - active
    # Engagement score breakdown (active leads only)
    scores = {3: 0, 2: 0, 1: 0}
    for l in leads:
        score, _ = _score_lead(l)
        if score in scores:
            scores[score] += 1
    score_line = f"🔥 Hot: {scores[3]} | ♨️ Warm: {scores[2]} | 🧊 Cold: {scores[1]}"
    # Drip step distribution (active leads only)
    steps: dict = {}
    for l in leads:
        if l.get("status", "").lower() == "active":
            step = l.get("email_count", "0")
            steps[step] = steps.get(step, 0) + 1
    step_summary = " | ".join(
        f"Step {k}: {v}"
        for k, v in sorted(steps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0)[:5]
    ) or "no active leads"
    programs: dict = {}
    for l in leads:
        p = l.get("program_interest", "Unknown")
        programs[p] = programs.get(p, 0) + 1
    prog_lines = "\n".join(
        f"  {p:<32} {c}"
        for p, c in sorted(programs.items(), key=lambda x: -x[1])
    )
    return (
        f"📊 Lead Summary\n{'─'*32}\n"
        f"Total:    {total}\n"
        f"Active:   {active} ({int(active/total*100) if total else 0}%)\n"
        f"Inactive: {inactive} ({int(inactive/total*100) if total else 0}%)\n\n"
        f"Engagement: {score_line}\n"
        f"Drip steps: {step_summary}\n\n"
        f"By Program:\n{prog_lines}"
    )

async def _report_text() -> str:
    """Build a compact inline marketing snapshot for /report and 📋 Quick Report."""
    leads  = parse_leads_csv()
    total  = len(leads)
    active = sum(1 for l in leads if l.get("status", "").lower() == "active")
    pct    = int(active / total * 100) if total else 0
    # Engagement scores
    scores = {3: 0, 2: 0, 1: 0}
    for l in leads:
        s, _ = _score_lead(l)
        if s in scores:
            scores[s] += 1
    # Drip step distribution
    steps: dict = {}
    for l in leads:
        if l.get("status", "").lower() == "active":
            k = l.get("email_count", "0")
            steps[k] = steps.get(k, 0) + 1
    step_parts = " | ".join(
        f"Step {k}: {v}"
        for k, v in sorted(steps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0)[:5]
    ) or "none"
    # Upcoming schedule
    raw = github_read_file("posting_schedule.json")
    sched_lines = []
    gaps = []
    try:
        sched = json.loads(raw).get("schedule", {})
        today = datetime.now(PHT).strftime("%Y-%m-%d")
        upcoming = [(d, sched[d]) for d in sorted(sched.keys()) if d >= today][:3]
        for d, fn in upcoming:
            label = fn.rsplit(".", 1)[0]
            sched_lines.append(f"  {d}: {label[:30]}")
        # Gap detection: check next 3 days
        for i in range(1, 4):
            day = (datetime.now(PHT) + timedelta(days=i)).strftime("%Y-%m-%d")
            if day not in sched:
                gaps.append(day)
    except Exception:
        sched_lines = ["  (schedule unavailable)"]
    now_str = datetime.now(PHT).strftime("%b %d, %Y %I:%M %p")
    lines = [
        f"📋 <b>Marketing Snapshot</b> — {now_str} PHT",
        "",
        f"👥 <b>Leads</b>",
        f"  Total: {total}  |  Active: {active} ({pct}%)",
        f"  🔥 Hot: {scores[3]}  |  ♨️ Warm: {scores[2]}  |  🧊 Cold: {scores[1]}",
        f"  Drip: {step_parts}",
        "",
        f"📅 <b>Upcoming Posts</b>",
    ]
    lines += sched_lines if sched_lines else ["  (none scheduled)"]
    if gaps:
        lines.append(f"  ⚠️ No post scheduled: {', '.join(gaps)}")
    return "\n".join(lines)

async def _eod_recap_text() -> str:
    """Build the end-of-day recap message."""
    now       = datetime.now(PHT)
    today_str = now.strftime("%Y-%m-%d")
    day_label = now.strftime("%A, %B %d")

    # Today's scheduled post
    today_post = "(none scheduled)"
    tomorrow_post = "(none)"
    gaps_soon = []
    try:
        raw   = github_read_file("posting_schedule.json")
        sched = json.loads(raw).get("schedule", {})
        today_post    = sched.get(today_str, "(none scheduled)")
        tomorrow_str  = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow_post = sched.get(tomorrow_str, "(none)")
        for i in range(1, 4):
            d = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            if d not in sched:
                gaps_soon.append((now + timedelta(days=i)).strftime("%b %d"))
    except Exception:
        pass

    # Lead stats
    leads  = parse_leads_csv()
    total  = len(leads)
    active = sum(1 for l in leads if l.get("status", "").lower() == "active")
    scores = {3: 0, 2: 0, 1: 0}
    for l in leads:
        s, _ = _score_lead(l)
        if s in scores:
            scores[s] += 1
    # Drip step distribution
    steps: dict = {}
    for l in leads:
        if l.get("status", "").lower() == "active":
            k = l.get("email_count", "0")
            steps[k] = steps.get(k, 0) + 1
    step_parts = " | ".join(
        f"Step {k}: {v}"
        for k, v in sorted(steps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0)[:5]
    ) or "none"

    # Build message
    lines = [
        f"🌆 <b>EOD Recap — {day_label}</b>",
        f"{'─' * 28}",
        "",
        f"📸 <b>Today's Post</b>",
        f"  {today_post.rsplit('.', 1)[0] if '.' in today_post else today_post}",
        "",
        f"📅 <b>Tomorrow</b>",
        f"  {tomorrow_post.rsplit('.', 1)[0] if '.' in tomorrow_post else tomorrow_post}",
    ]
    if gaps_soon:
        lines += ["", f"⚠️ <b>Upcoming gaps:</b> {', '.join(gaps_soon)}"]
    lines += [
        "",
        f"👥 <b>Leads</b>",
        f"  Active: {active} / {total}",
        f"  🔥 {scores[3]} hot  |  ♨️ {scores[2]} warm  |  🧊 {scores[1]} cold",
        f"  Drip: {step_parts}",
        "",
        f"✅ <b>See you tomorrow, Eva!</b>",
    ]
    return "\n".join(lines)

async def cmd_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End-of-day recap — on demand."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    text = await _eod_recap_text()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def _push_eod_recap(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job: push EOD recap at 5PM PHT to all users."""
    text = await _eod_recap_text()
    for uid_str in list(_bot_state.get("users", {})):
        try:
            await context.bot.send_message(
                chat_id=int(uid_str), text=text, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logging.warning(f"EOD recap push failed for {uid_str}: {e}")

async def _briefing_text() -> str:
    leads    = parse_leads_csv()
    total    = len(leads)
    active   = sum(1 for l in leads if l.get("status", "").lower() == "active")
    now      = datetime.now()
    date_str = now.strftime("%B %d, %Y")
    time_str = now.strftime("%I:%M %p")
    day_tip  = {
        0: "Monday — check last week's analytics and plan the week.",
        1: "Tuesday — good day to review drip email performance.",
        2: "Wednesday — mid-week check. How are the leads?",
        3: "Thursday — prep your weekend content.",
        4: "Friday — review the week. Schedule the weekend posts.",
        5: "Saturday — engagement is higher today. Good day to post.",
        6: "Sunday — weekly preview auto-runs at 5PM. Check your email.",
    }.get(now.weekday(), "")
    # Check schedule for gaps in next 3 days
    gap_warn = ""
    try:
        raw_sched = github_read_file("posting_schedule.json")
        sched = json.loads(raw_sched).get("schedule", {})
        gaps = []
        for i in range(1, 4):
            day = (datetime.now(PHT) + timedelta(days=i)).strftime("%Y-%m-%d")
            if day not in sched:
                gaps.append(day)
        if gaps:
            gap_warn = f"\n⚠️ No post scheduled: {', '.join(gaps)} — consider adding content."
    except Exception:
        pass
    # Today's calendar events
    cal_line = ""
    try:
        from workspace_helper import list_calendar_events
        today_str2 = datetime.now(PHT).strftime("%Y-%m-%d")
        events = list_calendar_events(days=1)
        today_events = []
        for ev in events:
            start = ev.get("start", {})
            date_key = start.get("dateTime", start.get("date", ""))[:10]
            if date_key == today_str2:
                t = ""
                if "dateTime" in start:
                    from datetime import datetime as _dt
                    t = _dt.fromisoformat(start["dateTime"]).strftime("%I:%M %p") + " "
                today_events.append(f"{t}{ev.get('summary','')}")
        if today_events:
            cal_line = "\n📅 Today's events: " + " · ".join(today_events)
    except Exception:
        pass

    return (
        f"🌅 Enderun Marketing — {date_str}\n"
        f"🕐 {time_str} PHT\n\n"
        f"👥 Active Leads: {active} / {total} total\n"
        f"📧 Drip emails: auto-send daily 8AM\n"
        f"📱 Social posts: auto-post daily 8AM\n"
        f"🔍 Social Listening: daily 7:50AM\n"
        f"{cal_line}\n\n"
        f"💡 {day_tip}{gap_warn}\n\n"
        f"What do you need today?"
    )

# ===========================================================================
# COMMAND HANDLERS
# ===========================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    session = get_session(user.id)
    get_user_state(user.id)["name"] = user.first_name or ""
    agent    = session["agent"] or "General Assistant"
    now_pht  = datetime.now(PHT)
    date_str = now_pht.strftime("%A, %B %d")
    hour     = now_pht.hour
    if 5 <= hour < 12:
        tod = "Magandang umaga"
    elif 12 <= hour < 18:
        tod = "Magandang hapon"
    elif 18 <= hour < 22:
        tod = "Magandang gabi"
    else:
        tod = "Hey"
    name_part = f", {user.first_name}" if user.first_name else ""
    await update.message.reply_text(
        f"<b>{tod}{name_part}! 👋</b>\n\n"
        f"I'm <b>Eva</b> — your Enderun Marketing AI.\n\n"
        f"📅 {date_str}\n"
        f"🎯 Agent: <b>{html_module.escape(agent)}</b>\n"
        f"💡 {len(list_agents())} specialists ready · /suggest for my take on today\n\n"
        f"Anong tulong kita? (or just tell me what you need!)",
        parse_mode=ParseMode.HTML,
        reply_markup=persistent_keyboard(),
    )
    await update.message.reply_text(
        "⚡ Quick actions:",
        reply_markup=start_keyboard(),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👩‍💼 <b>Eva — Enderun Marketing AI</b>\n\n"
        "<b>📊 Marketing Intelligence</b>\n"
        "  /suggest            — Eva's proactive recommendations for today\n"
        "  /report             — Quick marketing snapshot in chat\n"
        "  /briefing           — Full morning briefing\n"
        "  /today              — Today's image, leads & drip steps\n\n"
        "<b>👥 Lead Management</b>\n"
        "  /leads              — Lead stats (live from CSV)\n"
        "  /lead [name/email]  — Look up a lead + action buttons\n"
        "  /addlead            — Add a new lead\n"
        "  /updatelead         — Update lead status\n"
        "  /bulklead           — Bulk deactivate leads\n\n"
        "<b>✍️ Content Creation</b>\n"
        "  /ideas [topic]      — 5 content ideas (Reels, carousels, stories)\n"
        "  /hashtags [topic]   — Hashtag sets for FB, IG, TikTok\n"
        "  /tiktok [topic]     — Full TikTok video script\n"
        "  /comment [text]     — Draft replies to FB/IG comments\n"
        "  /templates          — Caption templates per program\n\n"
        "<b>🛡️ Intelligence</b>\n"
        "  /competitor [school] — Quick competitor intel via web search\n\n"
        "<b>🗂️ Google Workspace</b>\n"
        "  /cal [days]          — Google Calendar (next 7 or N days)\n"
        "  /addevent DATE [TIME] Title — Add calendar event\n"
        "  /inbox               — Gmail unread emails\n"
        "  /searchmail [query]  — Search Gmail (from:/subject:/keyword)\n"
        "  /syncsheets          — Sync leads ↔ Google Sheets\n"
        "  /drivelist           — Browse Google Drive folders\n\n"
        "<b>💬 Lead Comms</b>\n"
        "  /whatsapp [name]    — Draft WhatsApp follow-up for a lead\n"
        "  /draftemail [name]  — Draft a custom email for a lead\n"
        "  /addnote [email] [note] — Add a note to a lead\n\n"
        "<b>📅 Content & Schedule</b>\n"
        "  /schedule           — Upcoming posting schedule\n"
        "  /lastposts          — Last 15 captions (with agent tag)\n"
        "  /post [platform]    — Demo post (fb/ig/email/all)\n"
        "  /reschedule         — Move a scheduled post\n\n"
        "<b>🤖 Agents & Session</b>\n"
        "  /agent [name]       — Switch to a specialist agent\n"
        "  /summary            — Recap of this session\n"
        "  /status             — Current agent + session info\n"
        "  /remember [note]    — Eva remembers something for you\n"
        "  /clear              — Reset conversation\n\n"
        "<b>⚙️ System</b>\n"
        "  /retry              — Retry a failed workflow\n"
        "  /broadcast [msg]    — Send to all users (admin)\n"
        "  /chatid             — Your Telegram chat ID\n\n"
        "📎 <b>Send a file</b> (CSV, TXT, JSON, MD) → Eva analyzes it\n"
        "📷 <b>Send a photo</b> → Eva sees it and generates captions\n"
        "🌐 <b>Ask Eva to search the web</b> → live competitor research\n"
        "🎤 <b>Voice message</b> → talk hands-free\n"
        "🖥️ <b>Tell Eva to open a website</b> → browser automation\n\n"
        "Just describe what you need — Eva figures it out.",
        parse_mode=ParseMode.HTML,
    )

async def cmd_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Eva proactively analyzes leads + schedule and gives her top recommendations."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text("💡 Eva is analyzing your marketing situation…")

    now_pht  = datetime.now(PHT)
    today    = now_pht.strftime("%Y-%m-%d")
    date_str = now_pht.strftime("%A, %B %d, %Y")

    # Build a snapshot for Eva
    leads_summary = format_leads_summary(parse_leads_csv())
    sched_raw = github_read_file("posting_schedule.json")
    sched_info = ""
    if not sched_raw.startswith("Error"):
        try:
            sched = json.loads(sched_raw).get("schedule", {})
            upcoming = {d: f for d, f in sorted(sched.items()) if d >= today}
            next3 = list(upcoming.items())[:3]
            sched_info = "Upcoming posts: " + ", ".join(f"{d}: {f}" for d, f in next3) if next3 else "No posts scheduled this week."
            gaps = [d for i in range(1, 5) if (d := (now_pht + timedelta(days=i)).strftime("%Y-%m-%d")) not in sched]
            if gaps:
                sched_info += f"\nSchedule gaps: {', '.join(gaps[:3])}"
        except Exception:
            pass

    suggest_prompt = (
        f"Today is {date_str} PHT. Here is the current marketing situation:\n\n"
        f"{leads_summary}\n\n"
        f"{sched_info}\n\n"
        "As Eva, give me your top 4-5 proactive, specific recommendations for today. "
        "Be direct — what should I do RIGHT NOW? What's being missed? What's the biggest opportunity? "
        "Format as a numbered list. Each item: action + one-line reason. Keep it tight and actionable. "
        "End with one thing you'd do first if you were me."
    )
    # One-shot — use a temporary history so it doesn't pollute conversation
    tmp_messages = session["history"][-4:] + [{"role": "user", "content": suggest_prompt}]
    try:
        reply = call_claude_with_tools(
            build_system_prompt(session["agent"], user_id=user_id),
            tmp_messages,
        )
        try:
            await msg.delete()
        except Exception:
            pass
        await _send_reply(update, f"💡 <b>Eva's Recommendations — {date_str}</b>\n\n" + reply)
    except Exception as e:
        try:
            await msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ Could not generate suggestions: {e}")

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    count   = len(session.get("history", []))
    agent   = session.get("agent") or "General Assistant"
    if count == 0:
        session["pending"] = None
        await update.message.reply_text(
            "✅ Already clear — no messages in memory.",
            reply_markup=start_keyboard(),
        )
        return
    await update.message.reply_text(
        f"🗑️ <b>Clear conversation history?</b>\n\n"
        f"💬 <b>{count}</b> message(s) will be cleared\n"
        f"🤖 Agent: <b>{html_module.escape(agent)}</b>\n\n"
        f"This cannot be undone.",
        parse_mode=ParseMode.HTML,
        reply_markup=clear_confirm_keyboard(),
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    await update.message.reply_text(
        f"🤖 Agent: {session['agent'] or 'General Assistant'}\n"
        f"💬 Messages in memory: {len(session['history'])}\n"
        f"⏳ Pending approval: {'Yes' if session.get('pending') else 'No'}"
    )

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Chat ID: {update.effective_chat.id}\n\n"
        "Add as TELEGRAM_CHAT_ID in GitHub Secrets for workflow notifications."
    )

async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    args    = context.args
    if not args:
        await update.message.reply_text(
            f"Current: {session['agent'] or 'general'}\n\nSelect an agent:",
            reply_markup=agents_keyboard(session["agent"], user_id=update.effective_user.id),
        )
        return
    name = args[0].lower()
    if name == "general":
        session["agent"] = None
        session["history"] = []
        set_user_agent(update.effective_user.id, None)
        await update.message.reply_text("✅ Switched to General Assistant. History cleared.")
        return
    if name not in list_agents():
        await update.message.reply_text(f"Agent '{name}' not found.\n\nUse /agent to see the list.")
        return
    if len(session.get("history", [])) > 2:
        await update.message.reply_text(
            f"Switch to <b>{html_module.escape(name)}</b>?\n\n"
            f"You have {len(session['history'])} messages in context.\n"
            f"Keep them so the new agent has full background, or clear for a fresh start.",
            parse_mode=ParseMode.HTML,
            reply_markup=agent_switch_keyboard(name),
        )
    else:
        _do_switch_agent(session, name, update.effective_user.id, clear=True)
        await update.message.reply_text(f"✅ Switched to: {name}\n🗑️ History cleared.")

async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    VALID = ["facebook", "instagram", "email", "all"]
    if not args:
        await update.message.reply_text("Usage: /post [facebook|instagram|email|all]",
                                        reply_markup=start_keyboard())
        return
    platform = args[0].lower()
    if platform not in VALID:
        await update.message.reply_text(f"Unknown platform. Choose: {', '.join(VALID)}")
        return
    # Route through approval flow so caption is reviewed before posting
    session = get_session(update.effective_user.id)
    email_to = args[1] if len(args) > 1 else ""
    if email_to:
        prompt = f"Generate a demo drip email and post to {platform} — send email to {email_to}."
    else:
        prompt = f"Generate a post and post to {platform}."
    session["history"].append({"role": "user", "content": prompt})
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]
    await _call_and_reply(update, context, session)

# ===========================================================================
# LEADS COMMANDS
# ===========================================================================
async def cmd_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    leads = parse_leads_csv()
    await update.message.reply_text(
        format_leads_summary(leads),
        reply_markup=leads_actions_keyboard(),
    )

async def cmd_add_lead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /add-lead FirstName LastName email@email.com \"Program\"\n\n"
            "Example:\n"
            '  /add-lead Maria Santos msantos@gmail.com "BS Hospitality Management"'
        )
        return
    first   = args[0]
    last    = args[1]
    email   = args[2]
    program = " ".join(args[3:]).strip("\"'") if len(args) > 3 else "General Inquiry"

    if "@" not in email or "." not in email:
        await update.message.reply_text(f"Invalid email: {email}")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    raw = github_read_file("leads.csv")
    if raw.startswith("File not found"):
        raw = "first_name,last_name,email,program_interest,status,email_count\n"
    elif raw.startswith("Error"):
        await update.message.reply_text(f"Could not read leads.csv: {raw}")
        return

    if email.lower() in raw.lower():
        await update.message.reply_text(f"⚠️ A lead with {email} already exists.")
        return

    updated = raw.rstrip("\n") + f"\n{first},{last},{email},{program},active,0\n"
    result  = github_write_file("leads.csv", updated, f"Add lead: {first} {last} [skip ci]")
    if "Error" in result:
        await update.message.reply_text(f"❌ Could not save: {result}")
        return

    leads  = parse_leads_csv()
    active = sum(1 for l in leads if l.get("status", "").lower() == "active")
    await update.message.reply_text(
        f"✅ Lead added!\n\n"
        f"Name:    {first} {last}\n"
        f"Email:   {email}\n"
        f"Program: {program}\n"
        f"Status:  Active\n\n"
        f"Total active leads now: {active}"
    )

# ===========================================================================
# BRIEFING COMMAND
# ===========================================================================
async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    text = await _briefing_text()
    await update.message.reply_text(text, reply_markup=briefing_actions_keyboard())

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    text = await _report_text()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_pdfreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a branded PDF report and send it directly in Telegram."""
    args = context.args or []
    report_type = args[0].lower() if args else "leads"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
    status_msg = await update.message.reply_text("Generating PDF report...")

    try:
        # ── agents / prompts reference guide ───────────────────────────────
        if report_type in ("agents", "prompts"):
            base = Path(__file__).parent
            ref_pdf = base / "output" / "marketing-manager" / "2026-04-25_eva-enderun-marketing-ai.pdf"
            if not ref_pdf.exists():
                await status_msg.edit_text("Reference PDF not found. Run generate_eva_reference.py first.")
                return
            with open(ref_pdf, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename="Eva_Command_and_Agent_Reference_Guide.pdf",
                    caption="Eva — Enderun Marketing AI: Complete Command, Prompt and Agent Reference Guide",
                )
            await status_msg.delete()
            return

        # ── live leads snapshot (default) ───────────────────────────────────
        from report_helper import ReportBuilder

        leads   = parse_leads_csv()
        total   = len(leads)
        active  = sum(1 for l in leads if l.get("status", "").lower() == "active")
        inactive = total - active
        pct     = int(active / total * 100) if total else 0

        scores = {3: 0, 2: 0, 1: 0}
        for l in leads:
            s, _ = _score_lead(l)
            if s in scores:
                scores[s] += 1

        # Program breakdown
        prog_counts: dict = {}
        for l in leads:
            if l.get("status", "").lower() == "active":
                prog = l.get("program", "Unknown") or "Unknown"
                prog_counts[prog] = prog_counts.get(prog, 0) + 1
        prog_rows = [[p, str(c)] for p, c in sorted(prog_counts.items(), key=lambda x: -x[1])]

        # Drip step distribution
        steps: dict = {}
        for l in leads:
            if l.get("status", "").lower() == "active":
                k = str(l.get("email_count", "0"))
                steps[k] = steps.get(k, 0) + 1
        step_rows = [[f"Step {k}", str(v)] for k, v in sorted(steps.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)]

        # Upcoming schedule
        sched_rows = []
        gaps = []
        try:
            raw = github_read_file("posting_schedule.json")
            sched = json.loads(raw).get("schedule", {})
            today = datetime.now(PHT).strftime("%Y-%m-%d")
            upcoming = [(d, sched[d]) for d in sorted(sched.keys()) if d >= today][:5]
            sched_rows = [[d, v.rsplit(".", 1)[0][:40]] for d, v in upcoming]
            for i in range(1, 4):
                day = (datetime.now(PHT) + timedelta(days=i)).strftime("%Y-%m-%d")
                if day not in sched:
                    gaps.append(day)
        except Exception:
            sched_rows = [["—", "Schedule unavailable"]]

        now_label = datetime.now(PHT).strftime("%B %d, %Y %I:%M %p")

        rb = ReportBuilder(
            agent_id="marketing-manager",
            report_title="Marketing Snapshot Report",
            subtitle=f"Generated {now_label} PHT"
        )

        rb.add_section("Lead Overview")
        rb.add_kpi_row([
            ("Total Leads",   str(total),        False),
            ("Active",        f"{active} ({pct}%)", True),
            ("Inactive",      str(inactive),     False),
            ("Hot Leads",     str(scores[3]),    False),
        ])
        rb.add_kpi_row([
            ("Hot",   str(scores[3]), False),
            ("Warm",  str(scores[2]), False),
            ("Cold",  str(scores[1]), False),
        ])

        rb.add_section("Active Leads by Program")
        if prog_rows:
            rb.add_table(headers=["Program", "Leads"], rows=prog_rows)
        else:
            rb.add_paragraph("No active leads found.")

        rb.add_section("Drip Email Step Distribution")
        if step_rows:
            rb.add_table(headers=["Drip Step", "Leads"], rows=step_rows)
        else:
            rb.add_paragraph("No active leads in drip sequence.")

        rb.add_section("Upcoming Scheduled Posts")
        if sched_rows:
            rb.add_table(headers=["Date", "Content"], rows=sched_rows)
        else:
            rb.add_paragraph("No upcoming posts scheduled.")

        if gaps:
            rb.add_alert_box(
                f"No post scheduled on: {', '.join(gaps)}. Consider filling these gaps.",
                level="warning"
            )
        else:
            rb.add_alert_box("Posting schedule looks good — no gaps in the next 3 days.", level="success")

        rb.add_source("leads.csv — live internal data")
        rb.add_source("posting_schedule.json — live schedule data")

        pdf_path = rb.save()

        with open(pdf_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=f"Enderun_Marketing_Snapshot_{datetime.now(PHT).strftime('%Y-%m-%d')}.pdf",
                caption=f"Marketing Snapshot Report — {now_label} PHT",
            )
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"Error generating PDF: {e}")

# ===========================================================================
# SCREENSHOT COMMAND
# ===========================================================================
async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Screenshot any URL via Playwright and send as photo. Defaults to enderunextension.com."""
    args = context.args or []
    url  = args[0] if args else "https://enderunextension.com"
    if not url.startswith("http"):
        url = "https://" + url

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    status_msg = await update.message.reply_text(f"Taking screenshot of {url}...")

    try:
        from playwright.async_api import async_playwright
        import tempfile

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page    = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.goto(url, wait_until="networkidle", timeout=20000)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            await page.screenshot(path=tmp_path, full_page=False)
            await browser.close()

        with open(tmp_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"Screenshot: {url}",
            )
        os.unlink(tmp_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"Screenshot failed: {e}")


# ===========================================================================
# GENERATE IMAGE COMMAND
# ===========================================================================
async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a social media image from a text prompt using Pollinations AI (free, no key needed)."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /generate [prompt]\n\n"
            "Example: /generate modern culinary arts class in a professional kitchen, Enderun Colleges BGC"
        )
        return

    prompt = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    status_msg = await update.message.reply_text(f"Generating image for: {prompt[:60]}...")

    try:
        import urllib.parse, tempfile
        encoded = urllib.parse.quote(prompt)
        img_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&model=flux&nologo=true"

        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"Generated: {prompt[:200]}",
            )
        os.unlink(tmp_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"Image generation failed: {e}")


# ===========================================================================
# DRIP EMAIL PREVIEW COMMAND
# ===========================================================================
async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview the drip email a specific lead will receive next."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /preview [name or email]\n\nExample: /preview Juan  or  /preview juan@email.com"
        )
        return

    query = " ".join(context.args).lower().strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    status_msg = await update.message.reply_text("Finding lead and generating email preview...")

    leads = parse_leads_csv()
    lead  = next(
        (l for l in leads if query in l.get("name", "").lower() or query in l.get("email", "").lower()),
        None
    )

    if not lead:
        await status_msg.edit_text(f"No lead found matching '{query}'. Check the name or email.")
        return

    name       = lead.get("name", "").split()[0] or "there"
    program    = lead.get("program", "General") or "General"
    email_count = int(lead.get("email_count", 0) or 0)
    status     = lead.get("status", "unknown")
    score_val, score_label = _score_lead(lead)
    score_emoji = {3: "🔥", 2: "♨️", 1: "🧊"}.get(score_val, "—")

    try:
        # Get the image this lead would receive
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from send_drip_email import get_image_bytes_for_lead, generate_email_copy

        img_bytes, img_name = get_image_bytes_for_lead(email_count)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        copy = generate_email_copy(Path(tmp_path), name, program)
        os.unlink(tmp_path)

        text = (
            f"<b>Email Preview — {lead.get('name', name)}</b>\n"
            f"{score_emoji} {score_label}  |  Step {email_count}  |  {status.title()}\n"
            f"Program: {program}\n\n"
            f"<b>Subject:</b> {copy.get('subject', '—')}\n"
            f"<b>Preview:</b> {copy.get('preview', '—')}\n\n"
            f"<b>{copy.get('headline', '')}</b>\n"
            f"<i>{copy.get('subheadline', '')}</i>\n\n"
            f"{copy.get('body', '').replace(chr(10)*2, chr(10))[:600]}...\n\n"
            f"<b>{copy.get('highlight_title', '')}</b>\n"
            + "\n".join(f"• {p}" for p in copy.get("highlight_points", [])) +
            f"\n\n[{copy.get('cta_text', 'Learn More')}]  {copy.get('cta_secondary', '')}\n\n"
            f"<i>{copy.get('signature_line', '')}</i>"
        )

        await status_msg.edit_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        # Fallback: show lead info without email body if image unavailable
        await status_msg.edit_text(
            f"<b>Lead: {lead.get('name', name)}</b>\n"
            f"{score_emoji} {score_label}  |  Step {email_count}  |  {status.title()}\n"
            f"Program: {program}\n"
            f"Email: {lead.get('email', '—')}\n\n"
            f"Could not generate email preview: {e}",
            parse_mode=ParseMode.HTML
        )


# ===========================================================================
# SCHEDULE COMMAND
# ===========================================================================
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    now       = datetime.now(PHT)
    today_str = now.strftime("%Y-%m-%d")
    day_name  = now.strftime("%A, %B %d")

    # Today's scheduled image
    raw = github_read_file("posting_schedule.json")
    today_image = "(none scheduled)"
    if not raw.startswith("Error") and not raw.startswith("File not found"):
        try:
            today_image = json.loads(raw).get("schedule", {}).get(today_str, "(none scheduled)")
        except Exception:
            pass

    # Lead stats + drip step distribution
    leads  = parse_leads_csv()
    total  = len(leads)
    active = sum(1 for l in leads if l.get("status", "").lower() == "active")
    steps: dict = {}
    for l in leads:
        if l.get("status", "").lower() == "active":
            step = l.get("email_count", "0")
            steps[step] = steps.get(step, 0) + 1
    step_summary = " | ".join(
        f"Step {k}: {v}"
        for k, v in sorted(steps.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)[:5]
    ) or "no active leads"

    day_tip = {
        0: "Monday — check last week's analytics and plan the week.",
        1: "Tuesday — review drip email performance.",
        2: "Wednesday — mid-week check. How are the leads?",
        3: "Thursday — prep your weekend content.",
        4: "Friday — review the week. Schedule weekend posts.",
        5: "Saturday — engagement is higher today. Good day to post.",
        6: "Sunday — weekly preview auto-runs at 5PM. Check your email.",
    }.get(now.weekday(), "")

    await update.message.reply_text(
        f"📅 Today — {day_name}\n"
        f"{'─'*32}\n"
        f"📸 Scheduled post: {today_image}\n"
        f"👥 Active leads: {active} / {total}\n"
        f"📧 Drip steps: {step_summary}\n\n"
        f"💡 {day_tip}",
        reply_markup=today_actions_keyboard(),
    )

async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    raw = github_read_file("posting_schedule.json")
    if raw.startswith("Error") or raw.startswith("File not found"):
        await update.message.reply_text("Could not load posting_schedule.json from GitHub.")
        return
    try:
        schedule = json.loads(raw).get("schedule", {})
    except Exception:
        await update.message.reply_text("Could not parse posting_schedule.json.")
        return
    today    = datetime.now(PHT).strftime("%Y-%m-%d")
    upcoming = [(d, schedule[d]) for d in sorted(schedule.keys()) if d >= today]

    # Text schedule (next 14)
    lines = [f"📅 Posting Schedule\n{'─'*32}"]
    for date_str, filename in upcoming[:14]:
        marker = " ← today" if date_str == today else ""
        lines.append(f"{date_str}  {filename}{marker}")
    if not upcoming:
        lines.append("No upcoming posts scheduled.")
    await update.message.reply_text("\n".join(lines))

    # Image previews for next 3 — send as media group if available
    if upcoming:
        await update.message.reply_text("⏳ Loading image previews...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
        media_group = []
        for date_str, filename in upcoming[:3]:
            img_bytes = _download_scheduled_image(filename)
            if img_bytes:
                media_group.append(
                    InputMediaPhoto(media=img_bytes, caption=f"📅 {date_str}\n📸 {filename}")
                )
        if media_group:
            await update.message.reply_media_group(media=media_group)
        else:
            await update.message.reply_text("(Could not load image previews from Google Drive.)")

# ===========================================================================
# LEAD LOOKUP COMMAND
# ===========================================================================
async def cmd_lead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /lead [email or name]\n\nExample: /lead maria or /lead maria@gmail.com")
        return
    query_str = " ".join(args).lower().strip()
    leads = parse_leads_csv()
    matches = [l for l in leads if
               query_str in l.get("email", "").lower() or
               query_str in l.get("first_name", "").lower() or
               query_str in l.get("last_name", "").lower()]
    if not matches:
        await update.message.reply_text(f"No lead found matching: {query_str}")
        return
    lines = []
    for l in matches[:5]:
        lines.append(
            f"👤 {l.get('first_name','')} {l.get('last_name','')}\n"
            f"   📧 {l.get('email','')}\n"
            f"   📚 {l.get('program_interest','')}\n"
            f"   🔄 Status: {l.get('status','')}\n"
            f"   📨 Emails sent: {l.get('email_count','0')}"
        )
    header = f"Found {len(matches)} lead(s):\n\n" if len(matches) > 1 else ""
    # Show action buttons for the first matched lead
    first_email = matches[0].get("email", "")
    kb = lead_action_keyboard(first_email) if first_email else None
    await update.message.reply_text(header + "\n\n".join(lines), reply_markup=kb)

# ===========================================================================
# BROADCAST COMMAND
# ===========================================================================
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if ADMIN_IDS and uid not in ADMIN_IDS:
        await update.message.reply_text("This command is for admins only.")
        return
    msg = " ".join(context.args).strip()
    if not msg:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return
    sent = failed = 0
    for target_uid in _bot_state.get("users", {}):
        if target_uid == uid:
            continue
        try:
            await context.bot.send_message(chat_id=int(target_uid), text=f"📢 {msg}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 Broadcast sent.\n✅ Delivered: {sent}\n❌ Failed: {failed}")

# ===========================================================================
# AUTO-AGENT SUGGESTION — keyword detection
# ===========================================================================
_AGENT_KEYWORDS: list = [
    (["competitor", "katunggali", "competition", "iscahm", "cca manila", "lyceum", "dlsu", "ateneo"], "competitor-analysis"),
    (["press release", "media release", "balita", "news release", "media pitch"], "pr"),
    (["email sequence", "drip campaign", "email series", "nurture sequence"], "drip-campaign"),
    (["seo", "google ads", "search ad", "meta ads", "keyword rank", "organic traffic"], "seo-digital"),
    (["design brief", "canva", "layout", "visual brief", "poster design"], "designer"),
    (["tiktok script", "tiktok video", "reel script", "youtube script", "video script"], "video-multimedia"),
    (["analytics", "funnel analysis", "conversion rate", "lead report", "data report"], "data-analysis"),
    (["enrollment funnel", "enrollment forecast", "enrollment tracker", "funnel drop"], "enrollment-tracker"),
    (["influencer", "kol", "content creator", "blogger outreach"], "influencer-kol"),
    (["blog", "long-form", "seo article", "pillar content"], "blog-seo-content"),
    (["open house", "campus tour event", "webinar", "activation"], "events-activations"),
    (["wedding", "event venue", "banquetes", "catering inquiry", "corporate event"], "events-banquetes"),
    (["alumni", "graduate feature", "alumni story"], "alumni-relations"),
    (["whatsapp follow-up", "sms follow-up", "text blast"], "whatsapp-sms"),
    (["parent email", "parent campaign", "parent content"], "parent-engagement"),
    (["facebook comment", "reply to comment", "community reply", "dm reply"], "community-manager"),
    (["revenue model", "market size", "business case", "roi analysis"], "business-analyst"),
]

def _suggest_agent(text: str, current_agent) -> str | None:
    """Return a suggested agent name if the message strongly implies one, else None."""
    tl = text.lower()
    for keywords, agent in _AGENT_KEYWORDS:
        if any(kw in tl for kw in keywords):
            if agent != current_agent:
                return agent
    return None

def agent_suggest_keyboard(agent: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Switch to {agent}",  callback_data=f"agent_suggest:{agent}"),
         InlineKeyboardButton("❌ Stay here",            callback_data="agent_suggest:dismiss")],
    ])

def agent_switch_keyboard(name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Switch + Keep Context",  callback_data=f"agent_switch_keep:{name}"),
         InlineKeyboardButton("✅ Switch + Clear History", callback_data=f"agent_switch_clear:{name}")],
        [InlineKeyboardButton("❌ Stay here",               callback_data="agent_switch_cancel")],
    ])

def _do_switch_agent(session: dict, name: str | None, user_id: int, clear: bool):
    """Apply agent switch to session and bot state."""
    session["agent"] = name
    if clear:
        session["history"] = []
        session.pop("actions", None)
    set_user_agent(user_id, name)

# ===========================================================================
# MEMORY COMMANDS — /remember /forget /memories
# ===========================================================================
async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Usage: /remember [fact]\n\n"
            "Example:\n"
            "  /remember Eva prefers short captions, max 3 paragraphs\n"
            "  /remember Peak season ends April 30\n"
            "  /remember Always mention Les Roches affiliation in hospitality posts\n\n"
            "Use /memories to see all saved notes."
        )
        return
    state    = get_user_state(update.effective_user.id)
    memories = state.get("memories", [])
    memories.append({"text": text, "date": datetime.now(PHT).strftime("%Y-%m-%d")})
    state["memories"] = memories[-15:]  # keep last 15
    save_bot_state()
    await update.message.reply_text(f"✅ Noted! I'll remember this in every conversation:\n\n\"{text}\"")

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    state    = get_user_state(update.effective_user.id)
    memories = state.get("memories", [])
    if not memories:
        await update.message.reply_text("No memories saved yet.")
        return
    if not args:
        lines = [f"{i+1}. {m['text']} ({m['date']})" for i, m in enumerate(memories)]
        await update.message.reply_text(
            "Which memory to delete? Use /forget [number]:\n\n" + "\n".join(lines)
        )
        return
    try:
        idx = int(args[0]) - 1
        if idx < 0 or idx >= len(memories):
            raise ValueError
        removed = memories.pop(idx)
        state["memories"] = memories
        save_bot_state()
        # Store undo data in session
        session = get_session(update.effective_user.id)
        session["undo_memory"] = {
            "memory": removed,
            "idx": idx,
            "expires": (datetime.now(PHT) + timedelta(seconds=30)).isoformat(),
        }
        await update.message.reply_text(
            f"🗑️ Removed: <i>{html_module.escape(removed['text'])}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=undo_memory_keyboard(idx),
        )
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid number. Use /memories to see the list.")

async def cmd_memories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state    = get_user_state(update.effective_user.id)
    memories = state.get("memories", [])
    if not memories:
        await update.message.reply_text(
            "No memories saved yet.\n\nUse /remember [fact] to teach me something about your preferences, "
            "style rules, or business context."
        )
        return
    lines = [f"{i+1}. {m['text']}  ({m['date']})" for i, m in enumerate(memories)]
    await update.message.reply_text(
        f"🧠 {len(memories)} saved note(s):\n\n" + "\n".join(lines) +
        "\n\nUse /forget [number] to remove one."
    )

# ===========================================================================
# UPDATE LEAD / RETRY / LAST POSTS COMMANDS
# ===========================================================================
async def cmd_reschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /reschedule YYYY-MM-DD YYYY-MM-DD\n\n"
            "Example:\n"
            "  /reschedule 2026-04-18 2026-04-20\n\n"
            "Or just say it naturally:\n"
            "  \"ilipat yung Apr 18 post to Apr 20\"\n"
            "  \"move the April 18 post to next Monday\""
        )
        return
    from_date, to_date = args[0].strip(), args[1].strip()
    if not re.match(r'\d{4}-\d{2}-\d{2}', from_date) or not re.match(r'\d{4}-\d{2}-\d{2}', to_date):
        await update.message.reply_text("Dates must be YYYY-MM-DD format. Example: /reschedule 2026-04-18 2026-04-20")
        return
    today_str = datetime.now(PHT).strftime("%Y-%m-%d")
    if to_date < today_str:
        await update.message.reply_text(f"⚠️ {to_date} is in the past. Please choose a future date.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    raw = github_read_file("posting_schedule.json")
    filename = ""
    conflict = ""
    if not raw.startswith("Error"):
        try:
            sched    = json.loads(raw).get("schedule", {})
            filename = sched.get(from_date, "")
            conflict = sched.get(to_date, "")
        except Exception:
            pass
    if not filename:
        await update.message.reply_text(f"No post scheduled for {from_date}.")
        return
    session = get_session(update.effective_user.id)
    session["pending"] = {"action": "reschedule", "from_date": from_date, "to_date": to_date, "filename": filename}
    conflict_note = f"\n⚠️ {conflict} is already on {to_date} — it will be replaced." if conflict else ""
    await update.message.reply_text(
        f"📅 Move this post?\n\n"
        f"📸 {filename}\n"
        f"From: {from_date}\n"
        f"To:   {to_date}"
        f"{conflict_note}",
        reply_markup=reschedule_confirm_keyboard(),
    )

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /updatelead email@x.com [active|inactive]\n\n"
            "Example:\n"
            "  /updatelead juan@gmail.com inactive\n"
            "  /updatelead juan@gmail.com active"
        )
        return
    email      = args[0].lower()
    new_status = args[1].lower()
    if new_status not in ("active", "inactive"):
        await update.message.reply_text("Status must be 'active' or 'inactive'.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    raw = github_read_file("leads.csv")
    if raw.startswith("Error") or raw.startswith("File not found"):
        await update.message.reply_text(f"Could not read leads.csv: {raw}")
        return
    rows = list(csv.DictReader(io.StringIO(raw)))
    found = False
    for row in rows:
        if row.get("email", "").lower() == email:
            row["status"] = new_status
            found = True
            break
    if not found:
        await update.message.reply_text(f"No lead found with email: {email}")
        return
    fieldnames = list(rows[0].keys()) if rows else []
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    result = github_write_file("leads.csv", out.getvalue(), f"Update lead: {email} → {new_status} [skip ci]")
    if "Error" in result:
        await update.message.reply_text(f"❌ Could not save: {result}")
        return
    icon = "🟢" if new_status == "active" else "🔴"
    await update.message.reply_text(f"{icon} Updated: {email} → {new_status}")

async def cmd_bulklead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bulk lead operations: deactivate by count, deactivate by program, or export summary."""
    leads = parse_leads_csv()
    programs = sorted({l.get("program_interest","Unknown") for l in leads if l.get("status","").lower()=="active"})
    total  = len(leads)
    active = sum(1 for l in leads if l.get("status","").lower()=="active")
    rows = [[InlineKeyboardButton(f"🔴 Deactivate high-email leads (>N)", callback_data="blk:count")]]
    for prog in programs[:6]:
        short = prog[:22] + "…" if len(prog) > 22 else prog
        rows.append([InlineKeyboardButton(f"🔴 Deactivate all: {short}", callback_data=f"blk:prog:{prog}")])
    rows.append([InlineKeyboardButton("📄 Export active leads summary", callback_data="blk:export")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text(
        f"📋 <b>Bulk Lead Operations</b>\n\nActive: {active}/{total} leads\n\nChoose an action:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )

async def cmd_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 Retry a workflow — select one to run again:",
        reply_markup=retry_keyboard(),
    )

async def cmd_lastposts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_user_state(update.effective_user.id)
    hist  = state.get("caption_history", [])
    if not hist:
        await update.message.reply_text("No caption history yet. Post something first!")
        return
    lines = []
    for i, item in enumerate(hist, 1):
        cap = item["caption"]
        if i <= 3:
            snippet = cap if len(cap) <= 300 else cap[:300] + "..."
        else:
            snippet = cap[:120] + ("..." if len(cap) > 120 else "")
        agent_tag = f" · {item['agent']}" if item.get("agent") and item["agent"] != "general" else ""
        lines.append(
            f"{i}. [{item['platform'].title()}] {item['date']}{agent_tag}\n"
            f"   {snippet}"
        )
    await update.message.reply_text(
        f"📜 Last {len(hist)} caption(s):\n\n" + "\n\n".join(lines)
    )

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    actions = session.get("actions", [])
    history = session.get("history", [])
    agent   = session.get("agent") or "General Assistant"
    if not actions and not history:
        await update.message.reply_text(
            "📋 Nothing to summarize yet — this session just started!\n\n"
            "Ask me something or use a quick action to get started."
        )
        return
    lines = [
        f"<b>📋 Session Summary</b>",
        f"🤖 Agent: <b>{html_module.escape(agent)}</b>",
        f"💬 Messages: {len(history)}",
        "",
    ]
    if actions:
        lines.append("<b>What happened this session:</b>")
        for a in actions[-10:]:  # show last 10 actions
            lines.append(f"• {html_module.escape(a)}")
    else:
        lines.append("No tracked actions yet — try /leads, /briefing, or post something!")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

# ===========================================================================
# NEW COMMANDS: COUNTDOWN · GAPS · TIKTOK · COMMENT · TEMPLATES
# ===========================================================================

ENROLLMENT_DEADLINES = [
    ("Early Application Deadline",  (1, 31)),
    ("Main Enrollment Season End",  (4, 30)),
    ("School Year Start",           (6, 15)),
    ("Foundation Day / Anniversary",(8, 15)),
    ("SHS Enrollment Deadline",     (3, 31)),
    ("Open House",                  (3, 15)),
]

async def cmd_countdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Days until key enrollment & marketing dates."""
    now = datetime.now(PHT)
    lines = []
    for label, (mo, dy) in ENROLLMENT_DEADLINES:
        try:
            d = datetime(now.year, mo, dy, tzinfo=PHT)
            if d < now:
                d = datetime(now.year + 1, mo, dy, tzinfo=PHT)
            delta = (d - now).days
            if delta == 0:
                icon = "🔴"
            elif delta <= 14:
                icon = "🟠"
            elif delta <= 30:
                icon = "🟡"
            else:
                icon = "🟢"
            lines.append(f"{icon} <b>{delta}d</b> — {label} <i>({d.strftime('%b %d')})</i>")
        except Exception:
            continue
    lines.sort(key=lambda x: int(x.split("<b>")[1].split("d</b>")[0]))
    await update.message.reply_text(
        f"⏳ <b>Enrollment Calendar Countdown</b>\n"
        f"<i>Today: {now.strftime('%b %d, %Y')}</i>\n"
        f"{'─'*28}\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

async def cmd_gaps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect posting schedule gaps in the next 14 days."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    raw = github_read_file("posting_schedule.json")
    if raw.startswith("Error"):
        await update.message.reply_text("⚠️ Could not load posting schedule from GitHub.")
        return
    try:
        sched = json.loads(raw).get("schedule", {})
    except Exception:
        await update.message.reply_text("⚠️ Could not parse posting schedule.")
        return
    now = datetime.now(PHT)
    gap_lines, ok_lines = [], []
    for i in range(14):
        day = now + timedelta(days=i)
        ds  = day.strftime("%Y-%m-%d")
        label = day.strftime("%a %b %d")
        if ds in sched:
            ok_lines.append(f"✅ {label} — <code>{sched[ds]}</code>")
        else:
            gap_lines.append(f"⚠️ {label} — no post scheduled")
    if not gap_lines:
        header = "✅ <b>All clear!</b> Every day in the next 14 days has content.\n\n"
    else:
        header = f"⚠️ <b>{len(gap_lines)} gap(s)</b> found in the next 14 days:\n\n"
    body = "\n".join(gap_lines[:8])
    if len(gap_lines) > 8:
        body += f"\n…and {len(gap_lines)-8} more"
    scheduled_preview = "\n\n📅 <b>Scheduled content:</b>\n" + "\n".join(ok_lines[:6]) if ok_lines else ""
    await update.message.reply_text(
        header + body + scheduled_preview,
        parse_mode=ParseMode.HTML,
    )

async def cmd_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a TikTok video script on a given topic."""
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "🎬 Give me a topic!\n\n"
            "<b>Examples:</b>\n"
            "  /tiktok Les Roches affiliation\n"
            "  /tiktok life at Enderun BGC\n"
            "  /tiktok Open House\n"
            "  /tiktok WSET wine course",
            parse_mode=ParseMode.HTML,
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    prompt = (
        f"Write a TikTok video script for Enderun Colleges about: {topic}\n\n"
        "Format exactly like this:\n\n"
        "🎣 HOOK (0–3s):\n[One punchy line that stops the scroll]\n\n"
        "🎬 BODY (4–22s):\n[3–5 fast punchy statements or scene descriptions, one per line]\n\n"
        "📣 CTA (23–30s):\n[Clear call to action — tour, apply, follow]\n\n"
        "💬 On-Screen Text:\n[2–3 text overlay suggestions]\n\n"
        "🎵 Sound:\n[Trending audio type or suggestion]\n\n"
        "#️⃣ Hashtags:\n[10 relevant hashtags]\n\n"
        "Keep it Gen Z energy — fast, real, aspirational, Filipino-proud. No cringe."
    )
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("video-multimedia", user_id=update.effective_user.id), tmp
    )
    await _send_reply(update, f"🎬 <b>TikTok Script — {topic}</b>\n\n" + reply)

async def cmd_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Draft a reply to a Facebook/Instagram comment in Enderun brand voice."""
    comment_text = " ".join(context.args).strip() if context.args else ""
    if not comment_text:
        await update.message.reply_text(
            "💬 Paste the comment you want to reply to.\n\n"
            "<b>Example:</b>\n"
            '  /comment "How much po ang tuition per semester?"\n\n'
            "Or just send me the comment and say <i>\"reply to this comment\"</i>.",
            parse_mode=ParseMode.HTML,
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    prompt = (
        f"A person commented on Enderun's social media: \"{comment_text}\"\n\n"
        "Write 2 alternative replies from Enderun's community manager. "
        "Format:\n\nOption A:\n[reply]\n\nOption B:\n[reply]\n\n"
        "Rules: warm and professional, not corporate, under 3 sentences each. "
        "If it's an inquiry → guide to DM or campus tour. "
        "If it's praise → thank them and invite engagement. "
        "Taglish OK if comment was in Filipino."
    )
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("community-manager", user_id=update.effective_user.id), tmp
    )
    await _send_reply(update, f"💬 <b>Suggested Replies</b>\n\n{reply}")

_CAPTION_TEMPLATES = {
    "bshm": (
        "BS Hospitality Management",
        "Train at the standard of Les Roches — the world's #3 hospitality school.\n\n"
        "At Enderun, [program highlight or student story].\n\n"
        "Your future in hospitality starts in BGC. Apply now. 🌐"
    ),
    "bsca": (
        "BS Culinary Arts",
        "Trained by the school behind Alain Ducasse.\n\n"
        "[Student achievement / dish / kitchen moment].\n\n"
        "Enderun's BS Culinary Arts — where Filipino chefs become world-class. 👨‍🍳"
    ),
    "bsba": (
        "BS Business Administration",
        "Business education in the heart of BGC — with industry immersion built in.\n\n"
        "[Program highlight or alumni success].\n\n"
        "Enderun BA — for the next generation of Filipino business leaders. 💼"
    ),
    "bstm": (
        "BS Tourism Management",
        "Explore the world — then come back and lead it.\n\n"
        "[Tourism program feature or student story].\n\n"
        "BS Tourism at Enderun: global perspective, Filipino heart. ✈️"
    ),
    "bsaid": (
        "BS Architectural Interior Design",
        "Design is more than aesthetics — it's storytelling.\n\n"
        "[Student project / design feature].\n\n"
        "Enderun AID: where creativity meets world-class standards. 📐"
    ),
    "bsrem": (
        "BS Real Estate Management",
        "The Philippines' most dynamic industry deserves the sharpest minds.\n\n"
        "[Program highlight / industry partner].\n\n"
        "Enderun Real Estate Management — built for BGC, ready for the world. 🏢"
    ),
    "ext_wset": (
        "Extension — WSET Wine",
        "Certified. Credentialed. Ready for any cellar in the world.\n\n"
        "WSET Level [X] at Enderun Extension — [date / class detail].\n\n"
        "Register now at enderunextension.com 🍷"
    ),
    "ext_cul": (
        "Extension — Culinary Short Course",
        "One weekend. A skill for life.\n\n"
        "[Course name] at Enderun Extension — [date].\n\n"
        "Limited seats. Reserve yours at enderunextension.com 🍳"
    ),
    "events": (
        "Events / Banquetes",
        "Your celebration deserves world-class food — crafted by École Ducasse-trained hands.\n\n"
        "[Venue / event type / testimonial].\n\n"
        "Book a food tasting at Restaurant 101. 💍"
    ),
}

def templates_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 BS Hospitality",    callback_data="template:bshm"),
         InlineKeyboardButton("👨‍🍳 BS Culinary",       callback_data="template:bsca")],
        [InlineKeyboardButton("💼 BS Business",       callback_data="template:bsba"),
         InlineKeyboardButton("✈️ BS Tourism",         callback_data="template:bstm")],
        [InlineKeyboardButton("📐 Interior Design",   callback_data="template:bsaid"),
         InlineKeyboardButton("🏢 Real Estate",        callback_data="template:bsrem")],
        [InlineKeyboardButton("🍷 Extension — WSET",  callback_data="template:ext_wset"),
         InlineKeyboardButton("🍳 Extension — Culinary", callback_data="template:ext_cul")],
        [InlineKeyboardButton("💍 Events / Banquetes", callback_data="template:events")],
    ])

async def cmd_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show caption templates per program."""
    await update.message.reply_text(
        "📝 <b>Caption Templates</b>\n\n"
        "Pick a program to get a ready-to-customize caption template:",
        parse_mode=ParseMode.HTML,
        reply_markup=templates_keyboard(),
    )

# ===========================================================================
# NEW COMMANDS: IDEAS · COMPETITOR · HASHTAGS · WHATSAPP · ADDNOTE · DRAFTEMAIL
# ===========================================================================

async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate 5 content ideas for a program or topic."""
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "💡 Give me a topic!\n\n"
            "<b>Examples:</b>\n"
            "  /ideas BS Hospitality\n"
            "  /ideas WSET wine course\n"
            "  /ideas enrollment season Open House\n"
            "  /ideas BGC campus life",
            parse_mode=ParseMode.HTML,
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    prompt = (
        f"Generate 5 specific, immediately actionable content ideas for Enderun's social media about: {topic}\n\n"
        "Format each idea as:\n"
        "[NUMBER]. [FORMAT: Reel/Carousel/Static/Story/TikTok] — Title\n"
        "→ Description (1-2 sentences: what to show, what to say)\n"
        "→ Best platform: FB / IG / TikTok / All\n\n"
        "Mix formats: include at least 1 video/Reel idea, 1 carousel, 1 story.\n"
        "Be specific and practical — each idea should be doable with existing campus assets."
    )
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("content-strategy", user_id=update.effective_user.id), tmp
    )
    await _send_reply(update, f"💡 <b>Content Ideas — {html_module.escape(topic)}</b>\n\n{reply}")


async def cmd_competitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick competitor intelligence via web search."""
    school = " ".join(context.args).strip() if context.args else ""
    if not school:
        await update.message.reply_text(
            "🛡️ Which school?\n\n"
            "<b>Examples:</b>\n"
            "  /competitor DLSU\n"
            "  /competitor CCA Manila\n"
            "  /competitor ISCAHM\n"
            "  /competitor Lyceum Philippines",
            parse_mode=ParseMode.HTML,
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text(f"🔍 Searching for {html_module.escape(school)}…")
    results = web_search(f"{school} Philippines enrollment programs announcements 2026", max_results=5)
    prompt = (
        f"Based on these search results about {school}:\n\n{results}\n\n"
        "Give me a quick competitor intelligence briefing:\n"
        "1. What are they currently promoting or announcing?\n"
        "2. Their apparent strengths vs Enderun Colleges\n"
        "3. Weaknesses or gaps Enderun can exploit\n"
        "4. One specific counter-move Enderun should make now\n\n"
        "Keep it punchy — max 8 bullet points. Focus on actionable insights."
    )
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("competitor-analysis", user_id=update.effective_user.id), tmp
    )
    try:
        await msg.delete()
    except Exception:
        pass
    await _send_reply(update, f"🛡️ <b>{html_module.escape(school)} — Quick Intel</b>\n\n{reply}")


async def cmd_hashtags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate optimized hashtag sets for FB, IG, and TikTok."""
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "#️⃣ Give me a topic!\n\n"
            "<b>Examples:</b>\n"
            "  /hashtags culinary arts BGC\n"
            "  /hashtags WSET wine certification\n"
            "  /hashtags hospitality management Philippines\n"
            "  /hashtags Enderun campus life",
            parse_mode=ParseMode.HTML,
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    prompt = (
        f"Generate optimized hashtag sets for Enderun social media content about: {topic}\n\n"
        "Provide three ready-to-copy sets:\n\n"
        "📘 FACEBOOK (8-12 hashtags — broad + niche, no over-tagging)\n\n"
        "📸 INSTAGRAM (25-30 hashtags — mix of: broad reach, niche community, location BGC/Taguig/PH, program-specific, aspirational lifestyle, Enderun-branded)\n\n"
        "🎵 TIKTOK (6-8 hashtags — viral/trending + niche)\n\n"
        "Format: each platform's hashtags on a single line, space-separated. Ready to copy-paste directly into a post."
    )
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("social-media", user_id=update.effective_user.id), tmp
    )
    await _send_reply(update, f"#️⃣ <b>Hashtag Sets — {html_module.escape(topic)}</b>\n\n{reply}")


async def cmd_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Draft WhatsApp follow-up message for a lead."""
    query_str = " ".join(context.args).strip() if context.args else ""
    leads = parse_leads_csv()
    lead = None
    if query_str:
        parts = query_str.split(None, 1)
        search_term = parts[0].lower()
        topic_hint  = parts[1] if len(parts) > 1 else ""
        matches = [l for l in leads if
                   search_term in l.get("first_name", "").lower() or
                   search_term in l.get("last_name", "").lower() or
                   search_term in l.get("email", "").lower()]
        lead = matches[0] if matches else None
    else:
        topic_hint = ""

    if lead:
        name    = f"{lead.get('first_name','')} {lead.get('last_name','')}".strip()
        program = lead.get("program_interest", "General Inquiry")
        count   = lead.get("email_count", "0")
        _, score_label = _score_lead(lead)
        prompt = (
            f"Write WhatsApp follow-up messages for Enderun lead: {name}\n"
            f"Program interest: {program}\n"
            f"Drip emails received: {count} ({score_label})\n"
            f"Context/topic: {topic_hint or 'general follow-up'}\n\n"
            "Write 2 WhatsApp message options:\n"
            "Option A — Warm check-in (casual, friendly, conversational)\n"
            "Option B — Urgency angle (enrollment deadline, limited slots)\n\n"
            "Rules: under 80 words each, conversational tone, Taglish OK if natural, end with a clear open question or CTA."
        )
        header = f"💬 <b>WhatsApp — {html_module.escape(name)}</b>\n<i>{html_module.escape(program)} · {score_label}</i>"
    else:
        prompt = (
            f"Write WhatsApp follow-up message templates for Enderun Colleges leads.\n"
            f"Context: {query_str if query_str else 'general lead follow-up'}\n\n"
            "Option A — Warm check-in (casual, friendly, conversational)\n"
            "Option B — Urgency angle (enrollment deadline, limited slots)\n\n"
            "Rules: under 80 words each, conversational tone, Taglish OK if natural, end with a clear open question or CTA."
        )
        header = f"💬 <b>WhatsApp Templates</b>"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("whatsapp-sms", user_id=update.effective_user.id), tmp
    )
    await _send_reply(update, f"{header}\n\n{reply}")


async def cmd_addnote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a note to a specific lead by email."""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /addnote [email] [note]\n\n"
            "Example:\n"
            "  /addnote maria@gmail.com called yesterday, very interested in BSHM\n"
            "  /addnote juan@gmail.com attended Open House, wants scholarship info",
        )
        return
    email = args[0].lower()
    note  = " ".join(args[1:]).strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    raw = github_read_file("leads.csv")
    if raw.startswith("Error") or raw.startswith("File not found"):
        await update.message.reply_text(f"Could not read leads.csv: {raw}")
        return
    rows       = list(csv.DictReader(io.StringIO(raw)))
    fieldnames = list(rows[0].keys()) if rows else []
    if "notes" not in fieldnames:
        fieldnames.append("notes")
        for row in rows:
            row.setdefault("notes", "")
    found = False
    for row in rows:
        if row.get("email", "").lower() == email:
            existing  = row.get("notes", "")
            timestamp = datetime.now(PHT).strftime("%b %d")
            new_entry = f"[{timestamp}] {note}"
            row["notes"] = (existing + " | " + new_entry).lstrip(" | ")
            found = True
            break
    if not found:
        await update.message.reply_text(f"No lead found with email: {email}")
        return
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    result = github_write_file("leads.csv", out.getvalue(), f"Add note to {email} [skip ci]")
    if "Error" in result:
        await update.message.reply_text(f"❌ Could not save: {result}")
        return
    await update.message.reply_text(
        f"✅ Note saved to <code>{html_module.escape(email)}</code>\n\n"
        f"<i>{html_module.escape(note)}</i>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_draftemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Draft a custom email for a lead."""
    query_str = " ".join(context.args).strip() if context.args else ""
    if not query_str:
        await update.message.reply_text(
            "Usage: /draftemail [name or email] [topic]\n\n"
            "Examples:\n"
            "  /draftemail Maria WSET wine course\n"
            "  /draftemail juan@gmail.com Open House invitation\n"
            "  /draftemail Santos scholarship inquiry",
        )
        return
    parts       = query_str.split(None, 1)
    search_term = parts[0].lower()
    topic       = parts[1] if len(parts) > 1 else ""
    leads  = parse_leads_csv()
    matches = [l for l in leads if
               search_term in l.get("first_name", "").lower() or
               search_term in l.get("last_name", "").lower() or
               search_term in l.get("email", "").lower()]
    lead = matches[0] if matches else None

    if lead:
        name    = f"{lead.get('first_name','')} {lead.get('last_name','')}".strip()
        program = lead.get("program_interest", "General Inquiry")
        count   = lead.get("email_count", "0")
        notes   = lead.get("notes", "")
        prompt  = (
            f"Write a personalized email for Enderun lead: {name}\n"
            f"Program interest: {program}\n"
            f"Drip emails already sent: {count}\n"
            f"Lead notes: {notes or 'none'}\n"
            f"Email topic: {topic or 'general enrollment follow-up'}\n\n"
            "Write a warm, personalized email:\n"
            "Subject: [subject line]\n\n"
            "[Full email body — 3-4 short paragraphs]\n\n"
            "Rules: address them by first name, Enderun brand voice (warm, aspirational, professional), "
            "end with a clear CTA (campus tour, apply now, reply to inquire)."
        )
        header = f"📧 <b>Email Draft — {html_module.escape(name)}</b>\n<i>{html_module.escape(program)}</i>"
    else:
        prompt = (
            f"Write a personalized Enderun email about: {query_str}\n\n"
            "Subject: [subject line]\n\n"
            "[Full email body — 3-4 short paragraphs]\n\n"
            "Rules: warm, aspirational, professional Enderun brand voice. End with a clear CTA."
        )
        header = "📧 <b>Email Draft</b>"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text("✍️ Drafting email with Opus 4.7…")
    tmp = [{"role": "user", "content": prompt}]
    reply = call_claude_with_tools(
        build_system_prompt("drip-campaign", user_id=update.effective_user.id), tmp
    )
    try:
        await msg.delete()
    except Exception:
        pass
    await _send_reply(update, f"{header}\n\n{reply}")


# ===========================================================================
# CRYPTO TRADING ANALYSIS COMMAND
# ===========================================================================

async def cmd_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Crypto market analysis and trade setup via crypto-trader agent."""
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "📊 <b>Crypto Market Analyst</b>\n\n"
            "Usage: /trade [coin or question]\n\n"
            "Examples:\n"
            "  /trade BTC analysis\n"
            "  /trade ETH 4H setup\n"
            "  /trade SOL entry point\n"
            "  /trade market overview\n"
            "  /trade is it a good time to buy crypto?\n\n"
            "<i>Powered by Claude Opus 4.7 + crypto-trader agent</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text("📊 Analyzing market… one moment.")

    user_id = update.effective_user.id
    session = get_session(user_id)
    tmp = [{"role": "user", "content": query}]
    reply = call_claude_with_tools(
        build_system_prompt("crypto-trader", user_id=user_id), tmp
    )
    try:
        await msg.delete()
    except Exception:
        pass
    await _send_reply(update, f"📊 <b>Crypto Analysis</b>\n\n{reply}")


# ===========================================================================
# TRADING BOT COMMANDS — SCANNER · EXECUTE · POSITIONS · BALANCE
# ===========================================================================

def _trade_confirm_keyboard(symbol: str, action: str, market: str) -> InlineKeyboardMarkup:
    safe_sym = symbol.replace("/", "_").replace(":", "_")
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"✅ Execute {action.upper()} ${TRADE_BUDGET_USDT:.0f}",
                callback_data=f"trade_exec:{safe_sym}:{action}:{market}",
            ),
            InlineKeyboardButton("❌ Skip", callback_data="trade_skip"),
        ],
        [InlineKeyboardButton("📊 More Analysis", callback_data=f"trade_analyze:{safe_sym}:{market}")],
    ])


try:
    from trading_engine import TRADE_BUDGET_USDT as _TBU
    TRADE_BUDGET_USDT = _TBU
except Exception:
    TRADE_BUDGET_USDT = 50.0

_scanner_active = False


async def cmd_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start or stop the auto signal scanner."""
    global _scanner_active, _scanner_enabled
    args = context.args
    sub  = args[0].lower() if args else ""

    if sub == "stop":
        _scanner_active  = False
        _scanner_enabled = False
        await update.message.reply_text("🛑 Auto scanner stopped. Use /scanner start to resume.")
        return

    if sub == "start":
        _scanner_enabled = True
        await update.message.reply_text("🟢 Auto scanner started! You'll get alerts every 15 minutes when signals fire.")
        return

    if sub == "status":
        status = "🟢 Running (every 15 min)" if _scanner_enabled else "🔴 Stopped"
        await update.message.reply_text(f"Auto Scanner: {status}")
        return

    # Default: run one scan now
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text("🔍 Scanning market for signals…")

    try:
        from trading_engine import scan_all, format_signal_message
        signals = scan_all(timeframe="15m")
    except Exception as e:
        await msg.edit_text(f"❌ Scanner error: {e}")
        return

    try:
        await msg.delete()
    except Exception:
        pass

    if not signals:
        await update.message.reply_text(
            "🔍 <b>Market Scan Complete</b>\n\nNo strong signals found right now. "
            "Market may be ranging — best to wait.\n\n"
            "<i>Run /scanner again in 15 minutes.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    for sig in signals[:5]:  # Max 5 alerts per scan
        text = format_signal_message(sig)
        symbol = sig.get("symbol", "")
        action = sig.get("action", "buy")
        market = sig.get("market", "spot")
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=_trade_confirm_keyboard(symbol, action, market),
        )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show open futures positions."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        from trading_engine import get_open_positions, BYBIT_TESTNET
        positions = get_open_positions(market="futures")
        testnet   = "🧪 TESTNET" if BYBIT_TESTNET else "🔴 LIVE"
        if not positions:
            await update.message.reply_text(
                f"📂 <b>Open Positions</b> {testnet}\n\nNo open positions.",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [f"📂 <b>Open Positions</b> {testnet}\n"]
        for p in positions:
            sym   = p.get("symbol", "")
            side  = p.get("side", "").upper()
            size  = p.get("contracts", 0)
            entry = p.get("entryPrice", 0)
            pnl   = p.get("unrealizedPnl", 0)
            pnl_e = "🟢" if float(pnl) >= 0 else "🔴"
            lines.append(
                f"\n{pnl_e} <b>{sym}</b> {side}\n"
                f"  Size: {size} | Entry: ${float(entry):,.2f}\n"
                f"  PnL: {pnl_e} ${float(pnl):+.2f} USDT"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Binance USDT balance (spot + futures)."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        from trading_engine import get_balance, BYBIT_TESTNET
        spot_bal    = get_balance("spot")
        futures_bal = get_balance("futures")
        testnet     = "🧪 TESTNET" if BYBIT_TESTNET else "🔴 LIVE"
        await update.message.reply_text(
            f"💰 <b>Bybit Balance</b> {testnet}\n\n"
            f"<b>Spot:</b>\n"
            f"  Free:  ${spot_bal['free']:,.2f} USDT\n"
            f"  Total: ${spot_bal['total']:,.2f} USDT\n\n"
            f"<b>Futures:</b>\n"
            f"  Free:  ${futures_bal['free']:,.2f} USDT\n"
            f"  Total: ${futures_bal['total']:,.2f} USDT",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching balance: {e}\n\nMake sure BYBIT_API_KEY and BYBIT_SECRET_KEY are set in Railway.")


# ===========================================================================
# PAPER TRADING COMMANDS
# ===========================================================================

def _paper_exec_keyboard(symbol: str, action: str, sl: float, tp1: float, tp2: float) -> InlineKeyboardMarkup:
    safe = symbol.replace("/", "_")
    sl_s  = f"{sl:.4f}"  if sl  else "0"
    tp1_s = f"{tp1:.4f}" if tp1 else "0"
    tp2_s = f"{tp2:.4f}" if tp2 else "0"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"✅ Paper {action.upper()} ${TRADE_BUDGET_USDT:.0f}",
                callback_data=f"paper_exec:{safe}:{action}:{sl_s}:{tp1_s}:{tp2_s}",
            ),
            InlineKeyboardButton("❌ Skip", callback_data="trade_skip"),
        ],
    ])


async def cmd_paperscan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan market and show paper trade signals with execute buttons."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text("🔍 Scanning market with real prices…")
    try:
        from trading_engine import scan_all, format_signal_message
        signals = scan_all(timeframe="15m", min_grade="B")
    except Exception as e:
        await msg.edit_text(f"❌ Scanner error: {e}")
        return
    try:
        await msg.delete()
    except Exception:
        pass
    if not signals:
        await update.message.reply_text(
            "🔍 <b>Scan Complete</b>\n\nNo B-grade or higher signals right now. Try again in 15 minutes.",
            parse_mode=ParseMode.HTML,
        )
        return
    for sig in signals[:5]:
        text   = format_signal_message(sig)
        symbol = sig.get("symbol", "")
        action = sig.get("action", "buy")
        sl     = sig.get("sl") or 0
        tp1    = sig.get("tp1") or 0
        tp2    = sig.get("tp2") or 0
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=_paper_exec_keyboard(symbol, action, sl, tp1, tp2),
        )


async def cmd_paperportfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show paper trading portfolio with live PnL."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        from paper_trading import get_portfolio, format_portfolio_message
        p    = get_portfolio()
        text = format_portfolio_message(p)
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Refresh",      callback_data="paper_portfolio"),
                    InlineKeyboardButton("🔍 Scan Signals", callback_data="paper_scan"),
                ],
                [InlineKeyboardButton("🗑 Reset Account", callback_data="paper_reset_confirm")],
            ]),
        )
    except Exception as e:
        logging.warning(f"[paperportfolio] {e}")
        await update.message.reply_text(
            f"📋 <b>Paper Trading Portfolio</b> 🧪\n\n"
            f"💰 Balance: <b>$1,000.00 USDT</b> (starting)\n"
            f"📂 No open positions yet.\n\n"
            f"Use /paperscan to find signals and start trading!\n\n"
            f"<i>Error detail: {e}</i>",
            parse_mode=ParseMode.HTML,
        )


async def cmd_paperclose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close a paper trade position manually."""
    symbol = " ".join(context.args).strip().upper() if context.args else ""
    if not symbol:
        from paper_trading import get_portfolio
        p = get_portfolio()
        if not p["open_positions"]:
            await update.message.reply_text("No open paper positions to close.")
            return
        buttons = [
            [InlineKeyboardButton(
                f"Close {pos['symbol'].replace('/USDT','')} {'🟢LONG' if pos['side']=='buy' else '🔴SHORT'}",
                callback_data=f"paper_close:{pos['symbol'].replace('/','-')}",
            )]
            for pos in p["open_positions"]
        ]
        await update.message.reply_text(
            "Which position do you want to close?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    if "/USDT" not in symbol:
        symbol += "/USDT"
    from paper_trading import close_position, format_close_message
    result = close_position(symbol)
    await update.message.reply_text(format_close_message(result), parse_mode=ParseMode.HTML)


async def cmd_paperreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset paper trading account."""
    await update.message.reply_text(
        "⚠️ This will reset your paper trading account to $1,000 USDT and clear all trades.\n\nAre you sure?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, reset", callback_data="paper_reset_confirm"),
            InlineKeyboardButton("❌ Cancel",     callback_data="cancel"),
        ]]),
    )


async def _handle_paper_callback(update: Update, data: str):
    """Handle all paper trading callbacks."""
    query = update.callback_query
    await query.answer()

    if data == "paper_portfolio":
        from paper_trading import get_portfolio, format_portfolio_message
        p = get_portfolio()
        try:
            await query.edit_message_text(
                format_portfolio_message(p),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔄 Refresh", callback_data="paper_portfolio"),
                        InlineKeyboardButton("🔍 Scan Signals", callback_data="paper_scan"),
                    ],
                    [InlineKeyboardButton("🗑 Reset Account", callback_data="paper_reset_confirm")],
                ]),
            )
        except Exception:
            pass
        return

    if data == "paper_scan":
        await query.edit_message_reply_markup(reply_markup=None)
        try:
            from trading_engine import scan_all, format_signal_message
            signals = scan_all(timeframe="15m", min_grade="B")
            if not signals:
                await query.message.reply_text("🔍 No B-grade or higher signals right now. Try again in 15 minutes.")
                return
            for sig in signals[:5]:
                text   = format_signal_message(sig)
                symbol = sig.get("symbol", "")
                action = sig.get("action", "buy")
                sl     = sig.get("sl") or 0
                tp1    = sig.get("tp1") or 0
                tp2    = sig.get("tp2") or 0
                await query.message.reply_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=_paper_exec_keyboard(symbol, action, sl, tp1, tp2),
                )
        except Exception as e:
            await query.message.reply_text(f"❌ Scan error: {e}")
        return

    if data == "paper_reset_confirm":
        from paper_trading import reset_portfolio, STARTING_BALANCE
        reset_portfolio()
        try:
            await query.edit_message_text(
                f"✅ Paper account reset to <b>${STARTING_BALANCE:,.2f} USDT</b>. Fresh start!",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await query.message.reply_text(f"✅ Paper account reset to ${STARTING_BALANCE:,.2f} USDT.")
        return

    if data.startswith("paper_close:"):
        symbol = data.split(":", 1)[1].replace("-", "/")
        from paper_trading import close_position, format_close_message
        result = close_position(symbol)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(format_close_message(result), parse_mode=ParseMode.HTML)
        return

    if data.startswith("paper_exec:"):
        parts  = data.split(":")
        safe   = parts[1]
        action = parts[2]
        sl     = float(parts[3]) if len(parts) > 3 and parts[3] != "0" else None
        tp1    = float(parts[4]) if len(parts) > 4 and parts[4] != "0" else None
        tp2    = float(parts[5]) if len(parts) > 5 and parts[5] != "0" else None
        symbol = safe.replace("_", "/")

        await query.edit_message_reply_markup(reply_markup=None)
        thinking = await query.message.reply_text(f"⚡ Opening paper {action.upper()} on {symbol}…")

        from paper_trading import open_position, TRADE_BUDGET_USDT
        result = open_position(symbol, action, TRADE_BUDGET_USDT, sl=sl, tp1=tp1, tp2=tp2)

        try:
            await thinking.delete()
        except Exception:
            pass

        if "error" in result:
            await query.message.reply_text(f"❌ {result['error']}")
            return

        coin   = symbol.replace("/USDT", "")
        side_e = "🟢 LONG" if action == "buy" else "🔴 SHORT"
        sl_s   = f"${sl:,.4f}" if sl else "—"
        tp1_s  = f"${tp1:,.4f}" if tp1 else "—"
        tp2_s  = f"${tp2:,.4f}" if tp2 else "—"

        await query.message.reply_text(
            f"✅ <b>Paper Trade Opened!</b> 🧪\n\n"
            f"{side_e} <b>{coin}/USDT</b>\n"
            f"Entry:   <b>${result['entry_price']:,.4f}</b>\n"
            f"Amount:  ${result['usdt_amount']} USDT → {result['quantity']} {coin}\n"
            f"SL:      {sl_s}\n"
            f"TP1:     {tp1_s}\n"
            f"TP2:     {tp2_s}\n"
            f"Balance: ${result['balance_left']:,.2f} USDT remaining\n\n"
            f"<i>Use /paperportfolio to track · /paperclose to exit</i>",
            parse_mode=ParseMode.HTML,
        )


async def _handle_trade_callback(update: Update, data: str):
    """Handle trade execution callbacks from confirm keyboard."""
    query = update.callback_query
    await query.answer()

    if data == "trade_skip":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏭ Signal skipped.")
        return

    parts = data.split(":")
    if parts[0] == "trade_exec" and len(parts) >= 4:
        safe_sym = parts[1]
        action   = parts[2]
        market   = parts[3]
        symbol   = safe_sym.replace("_", "/", 1)
        if market == "futures":
            symbol = symbol.replace("_USDT", "/USDT:USDT") if "_USDT" in symbol else symbol

        await query.edit_message_reply_markup(reply_markup=None)
        status_msg = await query.message.reply_text(f"⚡ Executing {action.upper()} {symbol}…")

        try:
            from trading_engine import (
                place_spot_order, place_futures_order,
                TRADE_BUDGET_USDT, BYBIT_TESTNET,
            )
            testnet = "🧪 TESTNET" if BYBIT_TESTNET else "🔴 LIVE"

            if market == "futures":
                order = place_futures_order(symbol, action, TRADE_BUDGET_USDT, leverage=5)
            else:
                order = place_spot_order(symbol, action, TRADE_BUDGET_USDT)

            if "error" in order:
                await status_msg.edit_text(f"❌ Order failed: {order['error']}")
                return

            order_id = order.get("id", "N/A")
            filled   = order.get("filled", order.get("amount", 0))
            avg_price= order.get("average", order.get("price", 0))
            coin     = symbol.replace("/USDT:USDT", "").replace("/USDT", "")

            await status_msg.edit_text(
                f"✅ <b>Order Executed!</b> {testnet}\n\n"
                f"{'🟢 BUY (Long)' if action == 'buy' else '🔴 SELL (Short)'} <b>{coin}/USDT</b>\n"
                f"Order ID: <code>{order_id}</code>\n"
                f"Filled: {float(filled):.6f} {coin}\n"
                f"Avg Price: ${float(avg_price):,.4f}\n"
                f"Budget: ${TRADE_BUDGET_USDT} USDT\n\n"
                f"Use /positions to track open trades.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Execution error: {e}")

    elif parts[0] == "trade_analyze" and len(parts) >= 3:
        safe_sym = parts[1]
        market   = parts[2]
        symbol   = safe_sym.replace("_", "/", 1)
        await query.edit_message_reply_markup(reply_markup=None)
        thinking = await query.message.reply_text("📊 Running deep analysis…")
        try:
            from trading_engine import fetch_ohlcv, compute_signals
            ohlcv = fetch_ohlcv(symbol, timeframe="1h", limit=100, market=market)
            sig   = compute_signals(ohlcv)
            price = sig.get("price", 0)
            prompt = (
                f"Current {symbol} data:\n"
                f"Price: ${price:,.4f}, RSI: {sig.get('rsi')}, "
                f"Score: {sig.get('score')} (bullish={sig.get('bullish')}, bearish={sig.get('bearish')})\n"
                f"Signals: {', '.join(sig.get('signals', []))}\n\n"
                "Give a detailed 1H trade analysis with entry, SL, TP1, TP2, and your confidence level."
            )
            agent_md = load_agent("crypto-trader")
            reply = call_claude_with_tools(f"{load_claude_md()}\n\n{agent_md}",
                                           [{"role": "user", "content": prompt}])
            await thinking.delete()
            await _send_reply(update, f"📊 <b>{symbol} Deep Analysis</b>\n\n{reply}")
        except Exception as e:
            await thinking.edit_text(f"❌ Analysis error: {e}")


# ===========================================================================
# GOOGLE WORKSPACE COMMANDS — CALENDAR · SHEETS · GMAIL · DRIVE
# ===========================================================================

# ── CALENDAR ────────────────────────────────────────────────────────────────

async def cmd_cal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Google Calendar events for the next 7 days."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            pass
    try:
        from workspace_helper import list_calendar_events, format_events_text
        events = list_calendar_events(days=days)
        text   = format_events_text(
            events,
            header=f"📅 <b>Calendar — Next {days} Days</b>\n{'─'*28}\n\n",
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                        reply_markup=cal_actions_keyboard())
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Could not load calendar.\n\n"
            f"Make sure:\n"
            f"1. GOOGLE_CALENDAR_ID is set in Railway\n"
            f"2. The calendar is shared with the service account email\n\n"
            f"Error: {e}"
        )


async def cmd_addevent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add an event to Google Calendar. /addevent YYYY-MM-DD [HH:MM] Title"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /addevent YYYY-MM-DD [HH:MM] Event Title\n\n"
            "Examples:\n"
            "  /addevent 2026-05-15 09:00 Open House\n"
            "  /addevent 2026-05-20 Enrollment Deadline\n\n"
            "Or just say it naturally:\n"
            "  \"Eva, lagyan mo sa calendar ang Open House on May 15 9am\""
        )
        return
    date_str = args[0]
    if not re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        await update.message.reply_text("Date must be YYYY-MM-DD format. Example: 2026-05-15")
        return
    time_str = ""
    title_start = 1
    if len(args) > 1 and re.match(r'\d{1,2}:\d{2}', args[1]):
        time_str    = args[1].zfill(5)
        title_start = 2
    title = " ".join(args[title_start:]).strip()
    if not title:
        await update.message.reply_text("Please include an event title.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        from workspace_helper import add_calendar_event
        ev = add_calendar_event(title, date_str, time_str)
        if ev:
            time_label = f" at {time_str}" if time_str else " (all day)"
            await update.message.reply_text(
                f"✅ <b>Event added to Google Calendar!</b>\n\n"
                f"📅 {date_str}{time_label}\n"
                f"📌 {title}\n\n"
                f"<a href=\"{ev.get('htmlLink','')}\">View in Calendar</a>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text("⚠️ Event may not have been created. Check GOOGLE_CALENDAR_ID in Railway.")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not add event: {e}")


def cal_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Next 14 Days", callback_data="cal:14"),
         InlineKeyboardButton("📅 This Month",   callback_data="cal:30")],
        [InlineKeyboardButton("➕ Add Event",     callback_data="cal:add_prompt")],
    ])


# ── GMAIL ─────────────────────────────────────────────────────────────────────

async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last 5 unread emails from Gmail inbox."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text("📬 Checking inbox…")
    try:
        from workspace_helper import search_gmail, format_emails_text
        emails = search_gmail("is:unread", limit=5)
        text   = format_emails_text(
            emails,
            header=f"📬 <b>Inbox — Unread</b>\n{'─'*28}\n\n",
        )
        try:
            await msg.delete()
        except Exception:
            pass
        await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                        reply_markup=inbox_actions_keyboard())
    except Exception as e:
        try:
            await msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ Could not read Gmail: {e}")


async def cmd_searchmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search Gmail. /searchmail [from:name | subject:text | keyword]"""
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "Usage: /searchmail [query]\n\n"
            "Examples:\n"
            "  /searchmail from:maria\n"
            "  /searchmail subject:enrollment\n"
            "  /searchmail WSET"
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.message.reply_text(f"🔍 Searching mail for \"{query}\"…")
    try:
        from workspace_helper import search_gmail, format_emails_text
        emails = search_gmail(query, limit=5)
        text   = format_emails_text(
            emails,
            header=f"📧 <b>Mail Search — {html_module.escape(query)}</b>\n{'─'*28}\n\n",
        )
        try:
            await msg.delete()
        except Exception:
            pass
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        try:
            await msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ Search failed: {e}")


def inbox_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Search Mail", callback_data="mail:search_prompt"),
         InlineKeyboardButton("🔄 Refresh",      callback_data="mail:refresh")],
    ])


# ── GOOGLE SHEETS — LEADS ─────────────────────────────────────────────────────

async def cmd_syncsheets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sync leads.csv → Google Sheets (push) or Sheets → leads.csv (pull)."""
    args = context.args
    direction = args[0].lower() if args else ""
    if direction not in ("push", "pull", ""):
        await update.message.reply_text("Usage: /syncsheets push  OR  /syncsheets pull")
        return
    if not direction:
        from workspace_helper import GOOGLE_LEADS_SHEET_ID, get_sheet_url
        if not GOOGLE_LEADS_SHEET_ID:
            await update.message.reply_text(
                "⚠️ GOOGLE_LEADS_SHEET_ID not set in Railway.\n\n"
                "Steps:\n"
                "1. Create a Google Sheet\n"
                "2. Share it with the service account email (Editor)\n"
                "3. Copy the Sheet ID from the URL\n"
                "4. Add GOOGLE_LEADS_SHEET_ID to Railway env vars"
            )
            return
        await update.message.reply_text(
            "Which direction?\n\n"
            "📤 <b>Push</b> — Upload leads.csv → Google Sheets (overwrites sheet)\n"
            "📥 <b>Pull</b> — Download Google Sheets → leads.csv (overwrites local CSV)\n\n"
            f"Sheet: <a href=\"{get_sheet_url()}\">Open Google Sheet</a>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Push CSV → Sheet", callback_data="sheets:push"),
                 InlineKeyboardButton("📥 Pull Sheet → CSV", callback_data="sheets:pull")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        return
    await _do_sheets_sync(update, context, direction)


async def _do_sheets_sync(update: Update, context: ContextTypes.DEFAULT_TYPE, direction: str):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    msg = await update.effective_message.reply_text(
        f"⏳ {'Pushing CSV to Sheets' if direction == 'push' else 'Pulling from Sheets to CSV'}…"
    )
    try:
        from workspace_helper import read_leads_from_sheet, write_leads_to_sheet, get_sheet_url
        if direction == "push":
            raw = github_read_file("leads.csv")
            if raw.startswith("Error"):
                await msg.edit_text(f"❌ Could not read leads.csv: {raw}")
                return
            rows = list(csv.DictReader(io.StringIO(raw)))
            headers = list(rows[0].keys()) if rows else ["first_name","last_name","email","program_interest","status","email_count"]
            ok = write_leads_to_sheet(rows, headers)
            if ok:
                await msg.edit_text(
                    f"✅ <b>Pushed {len(rows)} leads to Google Sheets!</b>\n"
                    f"<a href=\"{get_sheet_url()}\">Open Sheet</a>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await msg.edit_text("❌ Push failed. Check GOOGLE_LEADS_SHEET_ID and sheet permissions.")
        else:  # pull
            rows = read_leads_from_sheet()
            if not rows:
                await msg.edit_text("❌ Sheet is empty or could not be read.")
                return
            headers = list(rows[0].keys())
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
            result = github_write_file("leads.csv", out.getvalue(), f"Pull {len(rows)} leads from Google Sheets [skip ci]")
            if "Error" in result:
                await msg.edit_text(f"❌ Could not save to GitHub: {result}")
            else:
                await msg.edit_text(f"✅ <b>Pulled {len(rows)} leads from Sheets → leads.csv!</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"❌ Sync error: {e}")


# ── GOOGLE DRIVE BROWSE & UPLOAD ──────────────────────────────────────────────

async def cmd_drivelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse Google Drive folders accessible to Eva."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        from workspace_helper import list_drive_folders
        folders = list_drive_folders()
        if not folders:
            await update.message.reply_text(
                "No folders found. Make sure the service account has access to your Drive folders.\n\n"
                "Share folders with the service account email in Google Drive."
            )
            return
        lines = [f"📁 <b>Drive Folders ({len(folders)} visible)</b>\n{'─'*28}"]
        rows  = []
        for f in folders[:12]:
            lines.append(f"📁 {f['name']}")
            short = f['name'][:20] + "…" if len(f['name']) > 20 else f['name']
            rows.append([InlineKeyboardButton(f"📁 {short}", callback_data=f"drive:folder:{f['id']}:{f['name'][:20]}")])
        rows.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Could not list Drive folders: {e}")


# ===========================================================================
# COMPETITOR ALERT (daily scheduled job — web searches for competitor news)
# ===========================================================================
_COMPETITOR_SEARCH_TERMS = [
    "DLSU hospitality management enrollment",
    "CCA Manila culinary arts announcement",
    "ISCAHM Philippines new program",
    "LPU Manila hospitality scholarship",
]

async def _competitor_alert_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily job: search for competitor news and alert if something notable is found."""
    try:
        findings = []
        for term in _COMPETITOR_SEARCH_TERMS:
            results = web_search(term, max_results=2)
            if results and "No results" not in results:
                first_line = results.split("\n")[2] if len(results.split("\n")) > 2 else ""
                if first_line:
                    findings.append(f"🔍 <b>{term}</b>\n{first_line}")
        if not findings:
            return
        msg = (
            "🛡️ <b>Competitor Alert — Daily Intelligence</b>\n"
            f"<i>{datetime.now(PHT).strftime('%b %d, %Y')}</i>\n"
            f"{'─'*28}\n\n"
        ) + "\n\n".join(findings[:4]) + (
            "\n\n💡 <i>Use /agent competitor-analysis to build a full counter-strategy.</i>"
        )
        for uid_str in list(_bot_state.get("users", {})):
            try:
                await context.bot.send_message(
                    chat_id=int(uid_str), text=msg, parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
    except Exception as e:
        logging.warning(f"Competitor alert job error: {e}")

# ===========================================================================
# MESSAGE HANDLERS
# ===========================================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    session = get_session(user.id)
    text    = update.message.text.strip()
    if not text:
        return
    get_user_state(user.id)["name"] = user.first_name or ""

    # Split caption edit intercept (FB or IG)
    if session.get("awaiting_split_edit") and session.get("pending"):
        platform = session.pop("awaiting_split_edit")
        if platform == "fb":
            session["pending"]["caption_fb"] = text
        else:
            session["pending"]["caption_ig"] = text
        plabel = "Facebook" if platform == "fb" else "Instagram"
        await update.message.reply_text(
            f"✅ {plabel} caption updated.", reply_markup=split_caption_keyboard()
        )
        return

    # Caption edit intercept — user typed a replacement caption
    if session.get("awaiting_caption_edit") and session.get("pending"):
        session["awaiting_caption_edit"] = False
        session["pending"]["caption"] = text
        label = {"facebook": "Facebook", "instagram": "Instagram",
                 "email": "Email", "all": "FB + IG + Email"}.get(session["pending"]["action"], session["pending"]["action"])
        await update.message.reply_text(f"✅ Caption updated. Post to {label}?\n\n{text}",
                                        reply_markup=post_confirm_keyboard())
        return

    # Persistent keyboard shortcuts
    if text == "🌅 Briefing":
        await cmd_briefing(update, context); return
    if text == "📊 Leads":
        await cmd_leads(update, context); return
    if text == "📅 Today":
        await cmd_today(update, context); return
    if text == "🔍 Listen":
        await trigger_named_workflow(update, "social_listening.yml", "Social Listening"); return
    if text in ("📘 Post FB", "📸 Post IG"):
        platform = "facebook" if text == "📘 Post FB" else "instagram"
        session["history"].append({"role": "user", "content": f"Generate a post and post to {platform}."})
        if len(session["history"]) > MAX_HISTORY:
            session["history"] = session["history"][-MAX_HISTORY:]
        await _call_and_reply(update, context, session)
        return

    # Natural language calendar detection
    _CAL_TRIGGERS = ["lagyan sa calendar", "add sa calendar", "ilagay sa calendar",
                     "schedule natin", "ilagay mo sa calendar", "add to calendar",
                     "put on calendar", "mark the calendar", "iskedyul"]
    if any(t in text.lower() for t in _CAL_TRIGGERS):
        # Let Claude handle it, but inject calendar intent into prompt
        text = text + "\n\n[Intent: add event to Google Calendar. Extract date, time, and title from the user message and respond with /addevent command format, then call add_calendar_event from workspace_helper.]"

    # Auto-agent suggestion — soft nudge, does not interrupt the reply
    suggested = _suggest_agent(text, session.get("agent"))

    session["history"].append({"role": "user", "content": text})
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]
    await _call_and_reply(update, context, session)

    # Send suggestion AFTER the reply so it doesn't feel like a blocker
    if suggested:
        await update.message.reply_text(
            f"💡 Tip: The {suggested} agent is specialized for this — want to switch?",
            reply_markup=agent_suggest_keyboard(suggested),
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    doc     = update.message.document
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("File too large (max 10MB).")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        tg_file   = await context.bot.get_file(doc.file_id)
        raw_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"Could not download file: {e}")
        return
    caption  = (update.message.caption or "").strip() or "Please analyze this."
    mime     = (doc.mime_type or "").lower()
    filename = doc.file_name or "file"
    if mime.startswith("image/"):
        media_type = mime if mime in ("image/jpeg","image/png","image/gif","image/webp") else "image/jpeg"
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(raw_bytes).decode("ascii")}},
            {"type": "text", "text": caption},
        ]
    elif mime == "application/pdf" or filename.lower().endswith(".pdf"):
        # Send PDF natively to Claude (no Python PDF library needed)
        await update.message.reply_text("📄 Reading PDF...")
        user_content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(raw_bytes).decode("ascii")}},
            {"type": "text", "text": caption or "Please analyze this PDF document."},
        ]
    else:
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text_content = raw_bytes.decode(enc); break
            except Exception:
                continue
        else:
            await update.message.reply_text(f"Cannot read '{filename}'. Send CSV, TXT, JSON, MD, or PDF.")
            return
        if len(text_content) > 8000:
            text_content = text_content[:8000] + f"\n\n[...truncated — {len(text_content):,} chars]"
        user_content = f"[File: {filename}]\n\n{text_content}\n\n---\n{caption}"
    session["history"].append({"role": "user", "content": user_content})
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]
    await _call_and_reply(update, context, session)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    photo   = update.message.photo[-1]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        tg_file   = await context.bot.get_file(photo.file_id)
        raw_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"Could not download photo: {e}")
        return

    # If user is responding to "send your own image" prompt
    if session.get("awaiting_own_image") and session.get("pending"):
        session["awaiting_own_image"] = False
        pending = session["pending"]
        action  = pending["action"]
        label   = {"facebook": "Facebook", "instagram": "Instagram",
                   "email": "Email", "all": "FB + IG + Email"}.get(action, action)
        uid = update.effective_user.id
        await update.message.reply_text("⏳ Generating captions for your image...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        pending["own_image_bytes"] = raw_bytes

        if action == "all":
            fb_cap, ig_cap = _generate_split_captions(raw_bytes, pending.get("prompt",""), uid)
            pending["caption_fb"] = strip_md(fb_cap)
            pending["caption_ig"] = strip_md(ig_cap)
            pending["caption"]    = strip_md(fb_cap)
            if fb_cap:
                await _send_reply(update, f"📘 Facebook:\n\n{strip_md(fb_cap)}")
            if ig_cap:
                await _send_reply(update, f"📸 Instagram:\n\n{strip_md(ig_cap)}")
            await update.effective_message.reply_text(
                "Two separate captions ready. Approve to post both:",
                reply_markup=split_caption_keyboard(),
            )
        else:
            cap_a, cap_b = _generate_vision_captions_ab(action, raw_bytes, pending.get("prompt",""), uid)
            pending["caption_a"] = strip_md(cap_a)
            pending["caption_b"] = strip_md(cap_b)
            pending["caption"]   = strip_md(cap_a)
            if cap_a:
                await _send_reply(update, f"🅰️ Version A:\n\n{strip_md(cap_a)}")
            if cap_b:
                await _send_reply(update, f"🅱️ Version B:\n\n{strip_md(cap_b)}")
            await update.effective_message.reply_text(
                f"Two versions for {label} — choose one:\n\n"
                f"⚠️ Make sure the caption matches your image before approving.",
                reply_markup=ab_caption_keyboard(),
            )
        return

    # Normal photo analysis
    user_caption = (update.message.caption or "").strip() or "Please analyze this image."
    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(raw_bytes).decode("ascii")}},
        {"type": "text", "text": user_caption},
    ]
    session["history"].append({"role": "user", "content": user_content})
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]
    # Store photo for potential posting
    session["last_photo_bytes"] = raw_bytes
    await _call_and_reply(update, context, session)
    # Offer to post the photo after analysis
    await update.effective_message.reply_text(
        "Want to post this image?",
        reply_markup=photo_post_keyboard(),
    )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GROQ_API_KEY:
        await update.message.reply_text(
            "🎤 Voice messages need a Groq API key (free).\n\n"
            "1. Sign up at console.groq.com (libre, walang credit card)\n"
            "2. Create an API key\n"
            "3. Add GROQ_API_KEY to Railway environment variables"
        )
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        from groq import Groq
        tg_file   = await context.bot.get_file(update.message.voice.file_id)
        ogg_bytes = bytes(await tg_file.download_as_bytearray())
        ogg_file  = io.BytesIO(ogg_bytes)
        ogg_file.name = "voice.ogg"
        groq_client = Groq(api_key=GROQ_API_KEY)
        transcript  = groq_client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=ogg_file,
        )
        transcribed = transcript.text.strip()
    except Exception as e:
        await update.message.reply_text(f"Could not transcribe voice: {e}")
        return
    if not transcribed:
        await update.message.reply_text("Could not understand the voice message. Please try again.")
        return
    await update.message.reply_text(f"🎤 \"{transcribed}\"")
    session = get_session(update.effective_user.id)
    session["history"].append({"role": "user", "content": transcribed})
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]
    await _call_and_reply(update, context, session)

# ===========================================================================
# CALLBACK QUERY HANDLER (inline buttons)
# ===========================================================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    session = get_session(update.effective_user.id)

    # Paper trading callbacks
    if (data.startswith("paper_exec:") or data.startswith("paper_close:") or
            data in ("paper_portfolio", "paper_scan", "paper_reset_confirm")):
        await _handle_paper_callback(update, data)
        return

    # Live trading callbacks
    if data.startswith("trade_exec:") or data.startswith("trade_analyze:") or data == "trade_skip":
        await _handle_trade_callback(update, data)
        return

    # Post approval
    if data == "confirm":
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("No pending post. Say what you'd like to post first.")
            return
        if _posting_lock.locked():
            await query.answer("⏳ Another post is being published. Please wait a moment.")
            return
        async with _posting_lock:
            await query.edit_message_text(f"✅ Confirmed. Posting to {pending['action'].title()}...")
            own_bytes = pending.pop("own_image_bytes", None)
            session["pending"] = None
            if pending.get("caption"):
                save_caption_history(update.effective_user.id, pending["caption"], pending["action"], session.get("agent"))
                _track_action(session, f"Posted to {pending['action'].title()}: {pending['caption'][:50]}…")
            if own_bytes:
                await _post_own_image(update, pending["action"], pending.get("caption", ""), own_bytes)
            else:
                await _do_dispatch(update, pending["action"], pending.get("email_to", ""), pending.get("caption", ""), pending.get("image", ""))
        return

    if data == "cancel":
        session["pending"] = None
        await query.edit_message_text("❌ Post cancelled.")
        return

    if data == "clear_confirm":
        count = len(session.get("history", []))
        session["history"] = []
        session["pending"] = None
        session.pop("actions", None)
        # Persist the cleared history to GitHub immediately so it survives restarts
        ustate = get_user_state(query.from_user.id)
        ustate["history"] = []
        save_bot_state()
        await query.edit_message_text(
            f"✅ Cleared {count} message(s). Fresh start!",
            reply_markup=start_keyboard(),
        )
        return

    if data == "clear_cancel":
        await query.edit_message_text("👍 Kept your history.")
        return

    if data.startswith("template:"):
        key = data.split(":", 1)[1]
        if key in _CAPTION_TEMPLATES:
            prog_name, _ = _CAPTION_TEMPLATES[key]
            await query.edit_message_text(f"✍️ Generating fresh caption for {prog_name}...")
            uid = query.from_user.id
            now_pht = datetime.now(PHT)
            season_ctx = _build_live_context()
            prompt = (
                f"Write a ready-to-post Facebook caption for Enderun's {prog_name} program.\n\n"
                f"Today is {now_pht.strftime('%A, %B %d, %Y')}. {season_ctx}\n\n"
                f"Rules:\n"
                f"- Do NOT use any banned openers from your caption style rules\n"
                f"- Include one specific Enderun credential: Les Roches #3 globally, École Ducasse / Alain Ducasse, 30+ countries for internship, BGC campus, or class size 20-25 students\n"
                f"- Sound like a real Filipino marketer wrote this — not a press release\n"
                f"- Taglish is welcome if it feels natural\n"
                f"- 3-4 short paragraphs, end with a clear CTA\n"
                f"- 6-10 hashtags on their own line at the bottom\n"
                f"- Write ONLY the caption — no intro text, no headers, start directly with the first word"
            )
            tmp = [{"role": "user", "content": prompt}]
            caption = call_claude_with_tools(build_system_prompt("social-media", user_id=uid), tmp)
            save_caption_history(uid, caption, "facebook", "social-media")
            await query.edit_message_text(
                f"📝 <b>{html_module.escape(prog_name)}</b>\n\n"
                f"{html_module.escape(caption)}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀ Back to Templates", callback_data="nav:templates"),
                ]]),
            )
        return

    if data == "cancel_edit":
        session.pop("awaiting_caption_edit", None)
        if session.get("pending"):
            await query.edit_message_text("↩️ Edit cancelled.", reply_markup=post_confirm_keyboard())
        else:
            await query.edit_message_text("↩️ Edit cancelled.")
        return

    if data == "cancel_split_edit":
        session.pop("awaiting_split_edit", None)
        if session.get("pending"):
            await query.edit_message_text("↩️ Edit cancelled.", reply_markup=split_caption_keyboard())
        else:
            await query.edit_message_text("↩️ Edit cancelled.")
        return

    if data == "edit_caption":
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("No pending post. Start a new post request.")
            return
        session["awaiting_caption_edit"] = True
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel edit", callback_data="cancel_edit")]])
        await query.edit_message_text(
            "✏️ Type your new caption below. It will replace the generated one.",
            reply_markup=cancel_kb,
        )
        return

    # A/B caption selection
    if data.startswith("ab_use:"):
        choice  = data.split(":", 1)[1]
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired. Please start a new post.")
            return
        pending["caption"] = pending.get(f"caption_{choice}", pending.get("caption_a", ""))
        label = {"facebook":"Facebook","instagram":"Instagram","email":"Email"}.get(pending["action"], pending["action"])
        await query.edit_message_text(
            f"✅ Version {choice.upper()} selected. Post to {label}?",
            reply_markup=post_confirm_keyboard(),
        )
        return

    if data == "ab_regen":
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired.")
            return
        img_bytes = _download_scheduled_image(pending.get("image",""))
        if not img_bytes and not pending.get("own_image_bytes"):
            await query.edit_message_text("Could not reload image for regeneration.")
            return
        img_bytes = img_bytes or pending.get("own_image_bytes")
        await query.edit_message_text("✍️ Regenerating both versions with Opus 4.7…")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        uid = update.effective_user.id
        cap_a, cap_b = _generate_vision_captions_ab(pending["action"], img_bytes, pending.get("prompt",""), uid)
        pending["caption_a"] = strip_md(cap_a)
        pending["caption_b"] = strip_md(cap_b)
        pending["caption"]   = strip_md(cap_a)
        # Accumulate versions for comparison
        versions = pending.setdefault("versions", [])
        if cap_a or cap_b:
            versions.append({"a": strip_md(cap_a), "b": strip_md(cap_b)})
        label = {"facebook":"Facebook","instagram":"Instagram","email":"Email"}.get(pending["action"],pending["action"])
        if cap_a: await _send_reply(update, f"🅰️ Version A:\n\n{strip_md(cap_a)}")
        if cap_b: await _send_reply(update, f"🅱️ Version B:\n\n{strip_md(cap_b)}")
        await update.effective_message.reply_text(
            f"Choose a version for {label}:",
            reply_markup=ab_caption_keyboard(has_prev=len(versions) > 1),
        )
        return

    # FB vs IG split caption actions
    if data == "split_post":
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired.")
            return
        await query.edit_message_text("✅ Posting to Facebook and Instagram...")
        own_bytes = pending.pop("own_image_bytes", None)
        session["pending"] = None
        if pending.get("caption_fb"):
            save_caption_history(update.effective_user.id, pending["caption_fb"], "facebook", session.get("agent"))
        if pending.get("caption_ig"):
            save_caption_history(update.effective_user.id, pending["caption_ig"], "instagram", session.get("agent"))
        if own_bytes:
            await _post_own_image(update, "facebook", pending.get("caption_fb",""), own_bytes)
            await _post_own_image(update, "instagram", pending.get("caption_ig",""), own_bytes)
        else:
            await trigger_github_post(update, "facebook", "", pending.get("caption_fb",""), pending.get("image",""))
            await trigger_github_post(update, "instagram", "", pending.get("caption_ig",""), pending.get("image",""))
        return

    if data.startswith("split_edit:"):
        platform = data.split(":", 1)[1]  # "fb" or "ig"
        pending  = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired.")
            return
        session["awaiting_split_edit"] = platform
        plabel = "Facebook" if platform == "fb" else "Instagram"
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel edit", callback_data="cancel_split_edit")]])
        await query.edit_message_text(f"✏️ Type your new {plabel} caption below.", reply_markup=cancel_kb)
        return

    if data == "split_regen":
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired.")
            return
        img_bytes = _download_scheduled_image(pending.get("image",""))
        if not img_bytes and not pending.get("own_image_bytes"):
            await query.edit_message_text("Could not reload image for regeneration.")
            return
        img_bytes = img_bytes or pending.get("own_image_bytes")
        await query.edit_message_text("✍️ Regenerating FB + IG captions with Opus 4.7…")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        uid = update.effective_user.id
        fb_cap, ig_cap = _generate_split_captions(img_bytes, pending.get("prompt",""), uid)
        pending["caption_fb"] = strip_md(fb_cap)
        pending["caption_ig"] = strip_md(ig_cap)
        pending["caption"]    = strip_md(fb_cap)
        if fb_cap: await _send_reply(update, f"📘 Facebook:\n\n{strip_md(fb_cap)}")
        if ig_cap: await _send_reply(update, f"📸 Instagram:\n\n{strip_md(ig_cap)}")
        await update.effective_message.reply_text("Updated captions ready:", reply_markup=split_caption_keyboard())
        return

    if data == "reschedule_confirm":
        pending = session.get("pending")
        if not pending or pending.get("action") != "reschedule":
            await query.edit_message_text("No pending reschedule.")
            return
        session["pending"] = None
        await query.edit_message_text("⏳ Updating schedule...")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        result = reschedule_post(pending["from_date"], pending["to_date"])
        await query.message.reply_text(result["message"])
        return

    if data == "drip_confirm":
        await query.edit_message_reply_markup(reply_markup=None)
        await trigger_drip_all(update)
        return

    if data == "drip_cancel":
        await query.edit_message_text("❌ Drip blast cancelled.")
        return

    if data == "regen":
        pending = session.get("pending")
        platform = pending["action"].title() if pending else "the platform"
        original_prompt = pending.get("prompt", "") if pending else ""
        session["pending"] = None
        if original_prompt:
            regen_msg = f"Regenerate the {platform} post with a completely different angle and hook. Original request: {original_prompt}"
        else:
            regen_msg = f"Please regenerate with a different angle for {platform}."
        session["history"].append({"role": "user", "content": regen_msg})
        if len(session["history"]) > MAX_HISTORY:
            session["history"] = session["history"][-MAX_HISTORY:]
        await query.edit_message_text("🔄 Regenerating...")
        await _call_and_reply(update, context, session)
        return

    # Image picker selection
    if data.startswith("imgpick:"):
        choice = data.split(":", 1)[1]
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired. Please try again.")
            return

        if choice == "own":
            session["awaiting_own_image"] = True
            await query.edit_message_text("📤 Send me the image you want to post (as a photo in Telegram).")
            return

        # Numeric choice — pick from img_options
        opts = session.get("img_options", [])
        try:
            idx = int(choice)
            _, filename = opts[idx]
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid selection. Please try again.")
            return

        action = pending["action"]
        uid    = update.effective_user.id
        label  = {"facebook":"Facebook","instagram":"Instagram",
                  "email":"Email","all":"FB + IG"}.get(action, action)

        prog = await query.message.reply_text("🔍 Loading image from Google Drive…")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")

        img_bytes = _download_scheduled_image(filename)
        pending["image"]       = filename
        session["img_options"] = []

        if img_bytes:
            await _try_send_image_preview(update, filename, img_bytes)

        if action == "all":
            # FB vs IG — split captions
            try: await prog.edit_text("✍️ Writing Facebook + Instagram captions with Opus 4.7…")
            except Exception as e: logging.warning(f"[imgpick] progress edit: {e}")
            fb_cap, ig_cap = _generate_split_captions(img_bytes, pending.get("prompt",""), uid) if img_bytes else ("","")
            try: await prog.delete()
            except Exception as e: logging.warning(f"[imgpick] progress delete: {e}")
            if not fb_cap and not ig_cap:
                await update.effective_message.reply_text("⚠️ Caption generation failed. Please try again.")
                return
            pending["caption_fb"] = strip_md(fb_cap)
            pending["caption_ig"] = strip_md(ig_cap)
            pending["caption"]    = strip_md(fb_cap)
            if fb_cap:
                await _send_reply(update, f"📘 Facebook:\n\n{strip_md(fb_cap)}")
            if ig_cap:
                await _send_reply(update, f"📸 Instagram:\n\n{strip_md(ig_cap)}")
            _track_action(session, f"Generated FB+IG split captions for {filename}")
            await update.effective_message.reply_text(
                "Two separate captions ready. Approve to post both:",
                reply_markup=split_caption_keyboard(),
            )
        else:
            # A/B versions for single platform
            try: await prog.edit_text(f"✍️ Writing two {label} caption versions with Opus 4.7…")
            except Exception as e: logging.warning(f"[imgpick] progress edit: {e}")
            cap_a, cap_b = _generate_vision_captions_ab(action, img_bytes, pending.get("prompt",""), uid) if img_bytes else ("","")
            try: await prog.delete()
            except Exception as e: logging.warning(f"[imgpick] progress delete: {e}")
            if not cap_a and not cap_b:
                await update.effective_message.reply_text("⚠️ Caption generation failed. Please try again.")
                return
            pending["caption_a"] = strip_md(cap_a)
            pending["caption_b"] = strip_md(cap_b)
            pending["caption"]   = strip_md(cap_a)
            # Track version history for comparison
            versions = pending.setdefault("versions", [])
            versions.append({"a": strip_md(cap_a), "b": strip_md(cap_b)})
            if cap_a:
                await _send_reply(update, f"🅰️ Version A:\n\n{strip_md(cap_a)}")
            if cap_b:
                await _send_reply(update, f"🅱️ Version B:\n\n{strip_md(cap_b)}")
            _track_action(session, f"Generated A/B captions for {filename} ({label})")
            img_note = "" if img_bytes else f"\n📸 {filename}"
            await update.effective_message.reply_text(
                f"Two versions for {label} — choose one:{img_note}",
                reply_markup=ab_caption_keyboard(has_prev=len(versions) > 1),
            )
        return

    # Compare caption versions
    if data == "compare_versions":
        pending = session.get("pending")
        if not pending or not pending.get("versions"):
            await query.answer("No previous versions to compare.")
            return
        versions = pending["versions"]
        lines = [f"📜 <b>Caption History</b> — {len(versions)} version(s)\n"]
        kb_rows = []
        for i, v in enumerate(versions, 1):
            lines.append(f"<b>V{i}A:</b> {html_module.escape(v['a'][:200])}{'…' if len(v['a'])>200 else ''}")
            lines.append(f"<b>V{i}B:</b> {html_module.escape(v['b'][:200])}{'…' if len(v['b'])>200 else ''}\n")
            kb_rows.append([
                InlineKeyboardButton(f"✅ Use V{i}A", callback_data=f"use_version:{i-1}:a"),
                InlineKeyboardButton(f"✅ Use V{i}B", callback_data=f"use_version:{i-1}:b"),
            ])
        kb_rows.append([InlineKeyboardButton("↩️ Back", callback_data="ab_back")])
        await query.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb_rows),
        )
        return

    if data.startswith("use_version:"):
        parts = data.split(":")
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired. Please start a new post.")
            return
        try:
            idx, choice = int(parts[1]), parts[2]
            v = pending["versions"][idx]
            pending["caption"] = v["a"] if choice == "a" else v["b"]
        except (IndexError, KeyError, ValueError):
            await query.answer("Version not found.")
            return
        label = {"facebook":"Facebook","instagram":"Instagram","email":"Email"}.get(pending["action"], pending["action"])
        await query.edit_message_text(
            f"✅ V{idx+1}{choice.upper()} selected. Post to {label}?",
            reply_markup=post_confirm_keyboard(),
        )
        return

    if data == "ab_back":
        pending = session.get("pending")
        if not pending:
            await query.edit_message_text("Session expired.")
            return
        label = {"facebook":"Facebook","instagram":"Instagram","email":"Email"}.get(pending.get("action",""), "post")
        versions = pending.get("versions", [])
        await query.edit_message_text(
            f"Two versions for {label} — choose one:",
            reply_markup=ab_caption_keyboard(has_prev=len(versions) > 1),
        )
        return

    # Save output to GitHub
    if data == "save_output":
        await query.edit_message_reply_markup(reply_markup=None)
        session["history"].append({"role": "user", "content": "Save the output you just generated to the appropriate folder in the GitHub repo using the write_file tool. Use YYYY-MM-DD format in the filename."})
        if len(session["history"]) > MAX_HISTORY:
            session["history"] = session["history"][-MAX_HISTORY:]
        await _call_and_reply(update, context, session)
        return

    # Photo quick-post (post last analyzed photo)
    if data.startswith("photo_post:"):
        action = data.split(":", 1)[1]
        if action == "dismiss":
            await query.edit_message_reply_markup(reply_markup=None)
            return
        if action == "drive":
            img_bytes = session.get("last_photo_bytes")
            if not img_bytes:
                await query.edit_message_text("⚠️ Photo no longer in memory. Please send it again.")
                return
            # Show folder picker
            try:
                from workspace_helper import list_drive_folders
                folders = list_drive_folders()
                if not folders:
                    await query.edit_message_text("No Drive folders found. Share folders with the service account first.")
                    return
                rows = []
                for f in folders[:10]:
                    short = f['name'][:22] + "…" if len(f['name']) > 22 else f['name']
                    rows.append([InlineKeyboardButton(f"📁 {short}", callback_data=f"drive_upload:{f['id']}:{f['name'][:20]}")])
                rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
                await query.edit_message_text(
                    "📁 Choose a Drive folder to save this photo:",
                    reply_markup=InlineKeyboardMarkup(rows),
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Could not list Drive folders: {e}")
            return
        img_bytes = session.get("last_photo_bytes")
        if not img_bytes:
            await query.edit_message_text("⚠️ Photo no longer in memory. Please send it again.")
            return
        label = {"facebook": "Facebook", "instagram": "Instagram", "all": "FB + IG"}.get(action, action)
        uid   = update.effective_user.id
        await query.edit_message_text(f"✍️ Generating caption for {label} with Opus 4.7…")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        session["pending"] = {"action": action, "email_to": "", "caption": "", "prompt": "", "own_image_bytes": img_bytes}
        if action == "all":
            fb_cap, ig_cap = _generate_split_captions(img_bytes, "", uid)
            session["pending"]["caption_fb"] = strip_md(fb_cap)
            session["pending"]["caption_ig"] = strip_md(ig_cap)
            session["pending"]["caption"]    = strip_md(fb_cap)
            if fb_cap: await _send_reply(update, f"📘 Facebook:\n\n{strip_md(fb_cap)}")
            if ig_cap: await _send_reply(update, f"📸 Instagram:\n\n{strip_md(ig_cap)}")
            await update.effective_message.reply_text(
                "Two captions ready. Approve to post both:",
                reply_markup=split_caption_keyboard(),
            )
        else:
            cap_a, cap_b = _generate_vision_captions_ab(action, img_bytes, "", uid)
            session["pending"]["caption_a"] = strip_md(cap_a)
            session["pending"]["caption_b"] = strip_md(cap_b)
            session["pending"]["caption"]   = strip_md(cap_a)
            versions = session["pending"].setdefault("versions", [])
            versions.append({"a": strip_md(cap_a), "b": strip_md(cap_b)})
            if cap_a: await _send_reply(update, f"🅰️ Version A:\n\n{strip_md(cap_a)}")
            if cap_b: await _send_reply(update, f"🅱️ Version B:\n\n{strip_md(cap_b)}")
            await update.effective_message.reply_text(
                f"Two versions for {label} — choose one:",
                reply_markup=ab_caption_keyboard(has_prev=False),
            )
        return

    # Quick post buttons
    if data.startswith("qpost:"):
        action = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=None)
        if action == "drip-all":
            leads  = parse_leads_csv()
            active = sum(1 for l in leads if l.get("status", "").lower() == "active")
            await query.message.reply_text(
                f"📨 Send drip emails to all active leads?\n\n"
                f"👥 Active leads: {active}\n"
                f"⚠️ Sequence counters will NOT be updated.",
                reply_markup=drip_confirm_keyboard(active),
            )
        else:
            prompt = f"Generate content and post to {action}."
            session["history"].append({"role": "user", "content": prompt})
            if len(session["history"]) > MAX_HISTORY:
                session["history"] = session["history"][-MAX_HISTORY:]
            await _call_and_reply(update, context, session)
        return

    # Workflow confirm (▶️ Run Now button)
    if data.startswith("wf_run:"):
        wf = data.split(":", 1)[1]
        if wf in WORKFLOW_MAP:
            wf_file, wf_label = WORKFLOW_MAP[wf]
            await query.edit_message_text(f"▶️ Running {wf_label}...")
            await trigger_named_workflow(update, wf_file, wf_label)
        return

    # Workflow quick buttons
    if data.startswith("workflow:"):
        wf = data.split(":", 1)[1]
        if wf == "weekly-preview":
            await query.edit_message_reply_markup(reply_markup=None)
            summary = _weekly_preview_summary()
            await query.message.reply_text(summary, reply_markup=workflow_confirm_keyboard("weekly-preview"))
        elif wf in WORKFLOW_MAP:
            wf_file, wf_label = WORKFLOW_MAP[wf]
            await query.edit_message_reply_markup(reply_markup=None)
            await trigger_named_workflow(update, wf_file, wf_label)
        return

    # Lead stats
    if data == "leads":
        await query.edit_message_reply_markup(reply_markup=None)
        leads = parse_leads_csv()
        await query.message.reply_text(format_leads_summary(leads), reply_markup=leads_actions_keyboard())
        return

    # Hot leads
    if data == "leads_hot":
        await query.edit_message_reply_markup(reply_markup=None)
        leads = parse_leads_csv()
        hot = sorted(
            [l for l in leads if _score_lead(l)[0] == 3],
            key=lambda x: int(x.get("email_count", 0) or 0),
            reverse=True,
        )[:10]
        if not hot:
            await query.message.reply_text("No hot leads yet — hot leads have 10+ emails sent.")
            return
        lines = [f"🔥 Top {len(hot)} Hot Leads (10+ emails sent):\n"]
        for l in hot:
            lines.append(
                f"👤 {l.get('first_name','')} {l.get('last_name','')}\n"
                f"   📚 {l.get('program_interest','')}\n"
                f"   📨 {l.get('email_count','0')} emails sent"
            )
        await query.message.reply_text("\n\n".join(lines))
        return

    # Quick report
    if data == "quick_report":
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        text = await _report_text()
        await query.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Briefing
    if data == "briefing":
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        await query.edit_message_reply_markup(reply_markup=None)
        text = await _briefing_text()
        await query.message.reply_text(text, reply_markup=briefing_actions_keyboard())
        return

    # Navigation shortcuts from contextual buttons
    if data.startswith("nav:"):
        nav = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=None)
        if nav == "schedule":
            await cmd_schedule(update, context)
        elif nav == "addlead":
            await query.message.reply_text(
                "Usage: <code>/addlead FirstName LastName email@x.com \"Program\"</code>\n\n"
                "Example:\n"
                "<code>/addlead Maria Santos msantos@gmail.com \"BS Hospitality Management\"</code>",
                parse_mode=ParseMode.HTML,
            )
        elif nav == "lead_prompt":
            await query.message.reply_text("Use <code>/lead [name or email]</code> to look up a lead.", parse_mode=ParseMode.HTML)
        elif nav == "reschedule_prompt":
            await query.message.reply_text(
                "Use <code>/reschedule YYYY-MM-DD YYYY-MM-DD</code> to move a post.\n\n"
                "Or say it naturally: <i>\"ilipat yung Apr 18 post to Apr 20\"</i>",
                parse_mode=ParseMode.HTML,
            )
        elif nav == "post_again":
            session["history"].append({"role": "user", "content": "Generate a new post for Facebook."})
            if len(session["history"]) > MAX_HISTORY:
                session["history"] = session["history"][-MAX_HISTORY:]
            await _call_and_reply(update, context, session)
        elif nav == "templates":
            await query.message.reply_text(
                "📝 <b>Caption Templates</b>\n\nPick a program:",
                parse_mode=ParseMode.HTML,
                reply_markup=templates_keyboard(),
            )
        return

    # Lead status toggle (from /lead action buttons)
    if data.startswith("lead_inactive:") or data.startswith("lead_activate:"):
        action_type, safe_email = data.split(":", 1)
        email      = safe_email.replace("__at__", "@").replace("__dot__", ".")
        new_status = "inactive" if action_type == "lead_inactive" else "active"
        prev_status = "active" if new_status == "inactive" else "inactive"
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        raw = github_read_file("leads.csv")
        if raw.startswith("Error") or raw.startswith("File not found"):
            await query.message.reply_text(f"Could not read leads.csv: {raw}")
            return
        rows = list(csv.DictReader(io.StringIO(raw)))
        found = False
        for row in rows:
            if row.get("email", "").lower() == email.lower():
                row["status"] = new_status
                found = True
                break
        if not found:
            await query.message.reply_text(f"Lead not found: {email}")
            return
        fieldnames = list(rows[0].keys()) if rows else []
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        result = github_write_file("leads.csv", out.getvalue(), f"Update lead: {email} → {new_status} [skip ci]")
        if "Error" in result:
            await query.message.reply_text(f"❌ Could not save: {result}")
            return
        icon = "🟢" if new_status == "active" else "🔴"
        _track_action(session, f"Lead {email} → {new_status}")
        # Store undo data in session (30-second window)
        session["undo_lead"] = {
            "email": email, "prev_status": prev_status,
            "expires": (datetime.now(PHT) + timedelta(seconds=30)).isoformat(),
        }
        await query.message.reply_text(
            f"{icon} {html_module.escape(email)} → {new_status}",
            parse_mode=ParseMode.HTML,
            reply_markup=undo_lead_keyboard(email, prev_status),
        )
        return

    # Undo lead status change
    if data.startswith("undo_lead:"):
        parts = data.split(":", 2)
        if len(parts) < 3:
            await query.answer("Invalid undo data.")
            return
        safe_email, prev_status = parts[1], parts[2]
        email = safe_email.replace("__at__", "@").replace("__dot__", ".")
        # Check expiry
        undo_data = session.get("undo_lead", {})
        if undo_data.get("email") == email:
            expires = datetime.fromisoformat(undo_data["expires"])
            if datetime.now(PHT) > expires:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.answer("Undo window expired (30 sec).")
                return
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        raw = github_read_file("leads.csv")
        if not raw.startswith("Error"):
            rows = list(csv.DictReader(io.StringIO(raw)))
            for row in rows:
                if row.get("email", "").lower() == email.lower():
                    row["status"] = prev_status
                    break
            fieldnames = list(rows[0].keys()) if rows else []
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            github_write_file("leads.csv", out.getvalue(), f"Undo lead: {email} → {prev_status} [skip ci]")
        session.pop("undo_lead", None)
        icon = "🟢" if prev_status == "active" else "🔴"
        await query.message.reply_text(f"↩️ Undone. {icon} {html_module.escape(email)} → {prev_status}", parse_mode=ParseMode.HTML)
        return

    # Undo memory deletion
    if data.startswith("undo_memory:"):
        undo_data = session.get("undo_memory", {})
        expires_str = undo_data.get("expires", "")
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str)
                if datetime.now(PHT) > expires:
                    await query.edit_message_reply_markup(reply_markup=None)
                    await query.answer("Undo window expired (30 sec).")
                    return
            except Exception as e:
                logging.warning(f"[undo_memory] expiry parse: {e}")
        memory = undo_data.get("memory")
        if not memory:
            await query.answer("Nothing to undo.")
            return
        state    = get_user_state(update.effective_user.id)
        memories = state.get("memories", [])
        idx      = undo_data.get("idx", len(memories))
        memories.insert(min(idx, len(memories)), memory)
        state["memories"] = memories[-15:]
        save_bot_state()
        session.pop("undo_memory", None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"↩️ Restored: <i>{html_module.escape(memory['text'])}</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Bulk lead operations
    if data == "blk:count":
        await query.edit_message_text(
            "How many emails sent is the cutoff?\n\nDeactivate all active leads with <b>more than N</b> emails sent.\n\nChoose N:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("5+",  callback_data="blk:count:5"),
                 InlineKeyboardButton("10+", callback_data="blk:count:10")],
                [InlineKeyboardButton("15+", callback_data="blk:count:15"),
                 InlineKeyboardButton("20+", callback_data="blk:count:20")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        return

    if data.startswith("blk:count:"):
        n = int(data.split(":")[-1])
        leads = parse_leads_csv()
        targets = [l for l in leads if l.get("status","").lower()=="active" and
                   (int(l.get("email_count",0) or 0)) > n]
        if not targets:
            await query.edit_message_text(f"No active leads with more than {n} emails sent.")
            return
        session["bulk_undo"] = {"emails": [l["email"] for l in targets], "prev_status": "active",
                                "expires": (datetime.now(PHT)+timedelta(seconds=60)).isoformat()}
        await query.edit_message_text(
            f"Deactivate <b>{len(targets)}</b> leads with {n}+ emails sent?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Deactivate {len(targets)} leads", callback_data=f"blk:do:count:{n}"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        return

    if data.startswith("blk:do:count:"):
        n = int(data.split(":")[-1])
        await query.edit_message_text("⏳ Updating leads…")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        raw = github_read_file("leads.csv")
        if raw.startswith("Error"):
            await query.message.reply_text(f"❌ Could not read leads.csv: {raw}")
            return
        rows = list(csv.DictReader(io.StringIO(raw)))
        changed = 0
        changed_emails = []
        for row in rows:
            if row.get("status","").lower()=="active" and (int(row.get("email_count",0) or 0)) > n:
                row["status"] = "inactive"; changed += 1; changed_emails.append(row["email"])
        fieldnames = list(rows[0].keys()) if rows else []
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(rows)
        result = github_write_file("leads.csv", out.getvalue(), f"Bulk deactivate: {changed} leads >{n} emails [skip ci]")
        if "Error" in result:
            await query.message.reply_text(f"❌ Could not save: {result}")
            return
        session["bulk_undo"] = {"emails": changed_emails, "prev_status": "active",
                                "expires": (datetime.now(PHT)+timedelta(seconds=60)).isoformat()}
        _track_action(session, f"Bulk deactivated {changed} leads (>{n} emails)")
        await query.edit_message_text(
            f"✅ Deactivated {changed} leads with {n}+ emails.\n↩️ Undo available for 60 seconds.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Undo", callback_data="blk:undo")]]),
        )
        return

    if data.startswith("blk:prog:"):
        prog = data[len("blk:prog:"):]
        leads = parse_leads_csv()
        targets = [l for l in leads if l.get("status","").lower()=="active" and l.get("program_interest","")==prog]
        if not targets:
            await query.edit_message_text(f"No active leads for: {prog}")
            return
        await query.edit_message_text(
            f"Deactivate <b>{len(targets)}</b> active leads in <i>{html_module.escape(prog)}</i>?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Deactivate {len(targets)}", callback_data=f"blk:do:prog:{prog}"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
            ]),
        )
        return

    if data.startswith("blk:do:prog:"):
        prog = data[len("blk:do:prog:"):]
        await query.edit_message_text("⏳ Updating leads…")
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        raw = github_read_file("leads.csv")
        if raw.startswith("Error"):
            await query.message.reply_text(f"❌ Could not read leads.csv: {raw}")
            return
        rows = list(csv.DictReader(io.StringIO(raw)))
        changed = 0; changed_emails = []
        for row in rows:
            if row.get("status","").lower()=="active" and row.get("program_interest","")==prog:
                row["status"] = "inactive"; changed += 1; changed_emails.append(row["email"])
        fieldnames = list(rows[0].keys()) if rows else []
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(rows)
        result = github_write_file("leads.csv", out.getvalue(), f"Bulk deactivate: {prog} [skip ci]")
        if "Error" in result:
            await query.message.reply_text(f"❌ Could not save: {result}")
            return
        session["bulk_undo"] = {"emails": changed_emails, "prev_status": "active",
                                "expires": (datetime.now(PHT)+timedelta(seconds=60)).isoformat()}
        _track_action(session, f"Bulk deactivated {changed} leads in {prog}")
        await query.edit_message_text(
            f"✅ Deactivated {changed} leads in {html_module.escape(prog)}.\n↩️ Undo for 60 seconds.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Undo", callback_data="blk:undo")]]),
        )
        return

    if data == "blk:undo":
        undo = session.get("bulk_undo", {})
        try:
            if datetime.now(PHT) > datetime.fromisoformat(undo.get("expires","2000-01-01")):
                await query.answer("Undo window expired (60 sec)."); return
        except Exception:
            await query.answer("Undo window expired."); return
        emails = undo.get("emails", [])
        if not emails:
            await query.answer("Nothing to undo."); return
        await query.edit_message_text("⏳ Restoring leads…")
        raw = github_read_file("leads.csv")
        if not raw.startswith("Error"):
            rows = list(csv.DictReader(io.StringIO(raw)))
            for row in rows:
                if row.get("email","") in emails:
                    row["status"] = undo.get("prev_status","active")
            fieldnames = list(rows[0].keys()) if rows else []
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader(); writer.writerows(rows)
            github_write_file("leads.csv", out.getvalue(), "Undo bulk lead change [skip ci]")
        session.pop("bulk_undo", None)
        await query.edit_message_text(f"↩️ Restored {len(emails)} leads to active.")
        return

    if data == "blk:export":
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        leads = parse_leads_csv()
        active = [l for l in leads if l.get("status","").lower()=="active"]
        prog_counts: dict = {}
        for l in active:
            p = l.get("program_interest","Unknown")
            prog_counts[p] = prog_counts.get(p,0) + 1
        lines = [f"📄 Active Leads Export — {len(active)} leads\n"]
        for p,c in sorted(prog_counts.items(), key=lambda x:-x[1]):
            lines.append(f"  {p}: {c}")
        lines.append(f"\nTop 10 by emails sent:")
        top = sorted(active, key=lambda x: int(x.get("email_count",0) or 0), reverse=True)[:10]
        for l in top:
            lines.append(f"  {l.get('first_name','')} {l.get('last_name','')} — {l.get('program_interest','')} — {l.get('email_count','0')} emails")
        await query.message.reply_text("\n".join(lines))
        return

    # Drive folder upload
    if data.startswith("drive_upload:"):
        parts  = data.split(":", 2)
        folder_id   = parts[1]
        folder_name = parts[2] if len(parts) > 2 else "Drive"
        img_bytes   = session.get("last_photo_bytes")
        if not img_bytes:
            await query.edit_message_text("⚠️ Photo no longer in memory.")
            return
        await query.edit_message_text(f"⏳ Uploading to 📁 {folder_name}…")
        try:
            from workspace_helper import upload_to_drive
            now_str  = datetime.now(PHT).strftime("%Y%m%d_%H%M%S")
            filename = f"eva_upload_{now_str}.jpg"
            file_id  = upload_to_drive(filename, img_bytes, folder_id, "image/jpeg")
            if file_id:
                await query.edit_message_text(
                    f"✅ Saved to Google Drive!\n\n"
                    f"📁 Folder: {folder_name}\n"
                    f"📸 File: {filename}"
                )
            else:
                await query.edit_message_text("❌ Upload failed. Check Drive permissions.")
        except Exception as e:
            await query.edit_message_text(f"❌ Upload error: {e}")
        return

    # Drive folder browse (from /drivelist)
    if data.startswith("drive:folder:"):
        parts = data.split(":", 3)
        folder_id   = parts[2]
        folder_name = parts[3] if len(parts) > 3 else "Folder"
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        try:
            from workspace_helper import list_drive_files
            files = list_drive_files(folder_id, limit=15)
            if not files:
                await query.message.reply_text(f"📁 {folder_name} is empty.")
                return
            lines = [f"📁 <b>{html_module.escape(folder_name)}</b> — {len(files)} file(s)\n"]
            for f in files:
                size = f.get("size", "")
                size_label = f" ({int(size)//1024}KB)" if size else ""
                lines.append(f"📄 {html_module.escape(f['name'])}{size_label}")
            await query.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.message.reply_text(f"❌ Could not list files: {e}")
        return

    # Calendar quick view
    if data.startswith("cal:"):
        sub = data.split(":", 1)[1]
        if sub == "add_prompt":
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "Use <code>/addevent YYYY-MM-DD [HH:MM] Title</code> to add an event.\n\n"
                "Example:\n<code>/addevent 2026-05-15 09:00 Open House</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            days = int(sub) if sub.isdigit() else 7
            await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
            try:
                from workspace_helper import list_calendar_events, format_events_text
                events = list_calendar_events(days=days)
                text   = format_events_text(
                    events, header=f"📅 <b>Calendar — Next {days} Days</b>\n{'─'*28}\n\n"
                )
                await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                              reply_markup=cal_actions_keyboard())
            except Exception as e:
                await query.edit_message_text(f"❌ Calendar error: {e}")
        return

    # Sheets sync via button
    if data.startswith("sheets:"):
        direction = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=None)
        await _do_sheets_sync(update, context, direction)
        return

    # Gmail quick actions
    if data.startswith("mail:"):
        sub = data.split(":", 1)[1]
        if sub == "refresh":
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
            try:
                from workspace_helper import search_gmail, format_emails_text
                emails = search_gmail("is:unread", limit=5)
                text   = format_emails_text(emails, header="📬 <b>Inbox — Unread</b>\n{'─'*28}\n\n")
                await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=inbox_actions_keyboard())
            except Exception as e:
                await query.message.reply_text(f"❌ {e}")
        elif sub == "search_prompt":
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "Use <code>/searchmail [query]</code> to search your inbox.\n\n"
                "Examples:\n"
                "<code>/searchmail from:maria</code>\n"
                "<code>/searchmail subject:enrollment</code>\n"
                "<code>/searchmail WSET</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    # Retry workflow buttons
    if data.startswith("retry:"):
        wf_key = data.split(":", 1)[1]
        wf_map = {
            "social-listening": ("social_listening.yml",  "Social Listening"),
            "analytics-report": ("weekly_analytics.yml",  "Analytics Report"),
            "weekly-preview":   ("weekly_preview.yml",    "Weekly Campaign Preview"),
            "daily-post":       ("daily_post.yml",        "Daily Post"),
        }
        if wf_key in wf_map:
            wf_file, wf_label = wf_map[wf_key]
            await query.edit_message_reply_markup(reply_markup=None)
            await trigger_named_workflow(update, wf_file, wf_label)
        return

    # Auto-agent suggestion response
    if data.startswith("agent_suggest:"):
        choice = data.split(":", 1)[1]
        if choice == "dismiss":
            await query.edit_message_reply_markup(reply_markup=None)
            return
        if choice in list_agents():
            if len(session.get("history", [])) > 2:
                await query.edit_message_text(
                    f"Switch to <b>{html_module.escape(choice)}</b>?",
                    parse_mode=ParseMode.HTML,
                    reply_markup=agent_switch_keyboard(choice),
                )
            else:
                _do_switch_agent(session, choice, update.effective_user.id, clear=True)
                await query.edit_message_text(f"✅ Switched to {choice}. History cleared — ready to go deeper!")
        return

    # Agent switch keyboard callbacks
    if data.startswith("agent_switch_keep:"):
        name = data.split(":", 1)[1]
        if name in list_agents() or name == "general":
            _do_switch_agent(session, name if name != "general" else None, update.effective_user.id, clear=False)
            await query.edit_message_text(f"✅ Switched to: {name}\n📚 History kept — the new agent has full context.")
        return

    if data.startswith("agent_switch_clear:"):
        name = data.split(":", 1)[1]
        if name in list_agents() or name == "general":
            _do_switch_agent(session, name if name != "general" else None, update.effective_user.id, clear=True)
            await query.edit_message_text(f"✅ Switched to: {name}\n🗑️ History cleared.")
        return

    if data == "agent_switch_cancel":
        await query.edit_message_text("👍 Staying with current agent.")
        return

    # Agent switch (from agents keyboard)
    if data.startswith("agent:"):
        name = data.split(":", 1)[1]
        if name == "general":
            if len(session.get("history", [])) > 2:
                await query.edit_message_text(
                    "Switch to <b>General Assistant</b>?",
                    parse_mode=ParseMode.HTML,
                    reply_markup=agent_switch_keyboard("general"),
                )
            else:
                _do_switch_agent(session, None, update.effective_user.id, clear=True)
                await query.edit_message_text("✅ Switched to General Assistant. History cleared.")
        elif name in list_agents():
            if len(session.get("history", [])) > 2:
                await query.edit_message_text(
                    f"Switch to <b>{html_module.escape(name)}</b>?\n\n"
                    f"You have {len(session['history'])} messages in context.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=agent_switch_keyboard(name),
                )
            else:
                _do_switch_agent(session, name, update.effective_user.id, clear=True)
                await query.edit_message_text(f"✅ Switched to: {name}\n🗑️ History cleared.")
        return

# ===========================================================================
# AUTO SIGNAL SCANNER JOB (every 15 minutes, 8AM–10PM PHT)
# ===========================================================================
_scanner_enabled = True   # can be toggled via /scanner stop

async def _auto_signal_scan(context: ContextTypes.DEFAULT_TYPE):
    """Job: scan market every 15 min, notify users when signals fire."""
    if not _scanner_enabled:
        return
    # Only scan during trading hours: 8AM–10PM PHT (00:00–14:00 UTC)
    now_utc = datetime.now(timezone.utc)
    if not (0 <= now_utc.hour < 14):
        return
    try:
        from trading_engine import scan_all, format_signal_message
        signals = scan_all(timeframe="15m")
    except Exception as e:
        logging.warning(f"[auto_scan] scan error: {e}")
        return

    if not signals:
        return

    users = list(_bot_state.get("users", {}).keys())
    if not users:
        return

    for sig in signals[:3]:  # max 3 alerts per scan cycle
        text   = format_signal_message(sig)
        symbol = sig.get("symbol", "")
        action = sig.get("action", "buy")
        sl     = sig.get("sl") or 0
        tp1    = sig.get("tp1") or 0
        tp2    = sig.get("tp2") or 0
        kb     = _paper_exec_keyboard(symbol, action, sl, tp1, tp2)

        for uid_str in users:
            try:
                await context.bot.send_message(
                    chat_id=int(uid_str),
                    text=f"🚨 <b>Auto Signal Detected!</b>\n\n{text}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            except Exception as e:
                logging.warning(f"[auto_scan] send to {uid_str}: {e}")


# ===========================================================================
# MORNING STANDUP JOB — personalized, actionable, 7:30 AM PHT
# ===========================================================================
async def _push_morning_briefing(context: ContextTypes.DEFAULT_TYPE):
    now       = datetime.now(PHT)
    day_label = now.strftime("%A, %B %d")

    leads  = parse_leads_csv()
    active = [l for l in leads if l.get("status","").lower() == "active"]

    # Hot leads — names + program
    hot_leads = [(l.get("name","?"), l.get("program","?"), int(l.get("email_count",0) or 0))
                 for l in active if _score_lead(l)[0] == 3]
    warm_leads_count = sum(1 for l in active if _score_lead(l)[0] == 2)
    cold_leads_count = sum(1 for l in active if _score_lead(l)[0] == 1)

    # New leads since yesterday
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    new_leads = [l for l in leads if l.get("date_added","") >= yesterday]

    # Schedule check
    today_str    = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    today_post   = "(none)"
    tomorrow_gap = False
    try:
        raw   = github_read_file("posting_schedule.json")
        sched = json.loads(raw).get("schedule", {})
        today_post   = sched.get(today_str, "(none scheduled)")
        tomorrow_gap = tomorrow_str not in sched
    except Exception:
        pass

    # Enrollment deadline countdown
    enroll_end = datetime(now.year, 4, 30, tzinfo=PHT) if now.month <= 4 else datetime(now.year + 1, 4, 30, tzinfo=PHT)
    days_left  = (enroll_end.date() - now.date()).days

    # Build message
    lines = [f"☀️ <b>Good morning! {day_label}</b>"]

    # Enrollment urgency
    if days_left <= 7:
        lines.append(f"\n🚨 <b>ENROLLMENT CLOSES IN {days_left} DAYS.</b> Switch all messaging to LAST CHANCE now.")
    elif days_left <= 14:
        lines.append(f"\n⚠️ Enrollment deadline in <b>{days_left} days</b> — use urgency in all captions.")
    elif days_left <= 30:
        lines.append(f"\n📅 <b>{days_left} days</b> to enrollment deadline.")

    # Hot leads — by name
    lines.append(f"\n👥 <b>Leads: {len(active)} active</b>")
    if hot_leads:
        lines.append(f"🔥 <b>{len(hot_leads)} Hot:</b>")
        for name, prog, step in hot_leads[:5]:
            lines.append(f"  • {name} — {prog} (Step {step}) → <b>Follow up today</b>")
        if len(hot_leads) > 5:
            lines.append(f"  + {len(hot_leads)-5} more hot leads")
    else:
        lines.append(f"🔥 Hot: 0  ♨️ Warm: {warm_leads_count}  🧊 Cold: {cold_leads_count}")

    # New leads
    if new_leads:
        lines.append(f"\n✨ <b>{len(new_leads)} new lead(s) since yesterday:</b>")
        for l in new_leads[:3]:
            lines.append(f"  • {l.get('name','?')} — {l.get('program','?')}")

    # Today's post
    lines.append(f"\n📸 <b>Today's post:</b> {today_post}")
    if tomorrow_gap:
        lines.append(f"⚠️ <b>No post scheduled tomorrow</b> — schedule something now.")

    # Priority action
    if hot_leads:
        top = hot_leads[0]
        lines.append(f"\n✅ <b>Priority:</b> Follow up {top[0]} ({top[1]}) — /preview {top[0].split()[0]}")
    elif new_leads:
        lines.append(f"\n✅ <b>Priority:</b> Add {new_leads[0].get('name','new lead')} to drip — /addlead")

    text = "\n".join(lines)
    for uid_str in list(_bot_state.get("users", {})):
        try:
            await context.bot.send_message(chat_id=int(uid_str), text=text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.warning(f"Morning briefing push failed for {uid_str}: {e}")


# ===========================================================================
# HOT LEAD ALERT JOB — fires every 4 hours, alerts on newly hot leads
# ===========================================================================
async def _hot_lead_check_job(context: ContextTypes.DEFAULT_TYPE):
    leads      = parse_leads_csv()
    alerted    = set(_bot_state.get("alerted_hot_leads", []))
    newly_hot  = []

    for l in leads:
        if l.get("status","").lower() != "active":
            continue
        score, _ = _score_lead(l)
        email    = l.get("email","").lower().strip()
        if score == 3 and email and email not in alerted:
            newly_hot.append(l)
            alerted.add(email)

    if not newly_hot:
        return

    _bot_state["alerted_hot_leads"] = list(alerted)
    save_bot_state()

    for l in newly_hot:
        name    = l.get("name", "Unknown")
        prog    = l.get("program", "Unknown")
        step    = l.get("email_count", "?")
        email   = l.get("email", "")
        msg = (
            f"🔥 <b>New Hot Lead!</b>\n\n"
            f"<b>{html_module.escape(name)}</b>\n"
            f"Program: {html_module.escape(prog)}\n"
            f"Drip step: {step} | Email: {html_module.escape(email)}\n\n"
            f"They've engaged with {step} emails — follow up now while they're warm.\n"
            f"→ /preview {html_module.escape(name.split()[0])}"
        )
        for uid_str in list(_bot_state.get("users", {})):
            try:
                await context.bot.send_message(chat_id=int(uid_str), text=msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.warning(f"Hot lead alert failed for {uid_str}: {e}")


# ===========================================================================
# CONTENT GAP ALERT — 9 PM PHT, warns if no post tomorrow
# ===========================================================================
async def _content_gap_alert_job(context: ContextTypes.DEFAULT_TYPE):
    now          = datetime.now(PHT)
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    day_name     = (now + timedelta(days=1)).strftime("%A, %B %d")
    try:
        raw  = github_read_file("posting_schedule.json")
        sched = json.loads(raw).get("schedule", {})
        if tomorrow_str in sched:
            return  # all good
    except Exception:
        return

    msg = (
        f"⚠️ <b>Content Gap Alert</b>\n\n"
        f"No post scheduled for tomorrow (<b>{day_name}</b>).\n\n"
        f"Schedule something tonight so the 8AM auto-post fires correctly.\n"
        f"→ Use /schedule to check the full calendar."
    )
    for uid_str in list(_bot_state.get("users", {})):
        try:
            await context.bot.send_message(chat_id=int(uid_str), text=msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.warning(f"Content gap alert failed for {uid_str}: {e}")


# ===========================================================================
# DRIP COMPLETION ALERT — daily, finds leads who finished the drip sequence
# ===========================================================================
async def _drip_completion_check_job(context: ContextTypes.DEFAULT_TYPE):
    leads     = parse_leads_csv()
    notified  = set(_bot_state.get("drip_completed_notified", []))
    completed = []

    # Determine max drip step from schedule
    try:
        raw = github_read_file("posting_schedule.json")
        max_step = len(json.loads(raw).get("schedule", {}))
    except Exception:
        max_step = 10

    for l in leads:
        if l.get("status","").lower() != "active":
            continue
        try:
            step = int(l.get("email_count", 0) or 0)
        except (ValueError, TypeError):
            continue
        email = l.get("email","").lower().strip()
        if step >= max_step and email and email not in notified:
            completed.append(l)
            notified.add(email)

    if not completed:
        return

    _bot_state["drip_completed_notified"] = list(notified)
    save_bot_state()

    names = "\n".join(
        f"  • {l.get('name','?')} — {l.get('program','?')} (Step {l.get('email_count','?')})"
        for l in completed[:8]
    )
    msg = (
        f"✅ <b>Drip Sequence Complete</b>\n\n"
        f"{len(completed)} lead(s) finished all drip emails:\n{names}\n\n"
        f"<b>Suggested next steps:</b>\n"
        f"• Invite them to a campus tour\n"
        f"• Send a personal WhatsApp message\n"
        f"• Flag for admissions follow-up\n\n"
        f"→ /leads to review their profiles"
    )
    for uid_str in list(_bot_state.get("users", {})):
        try:
            await context.bot.send_message(chat_id=int(uid_str), text=msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.warning(f"Drip completion alert failed for {uid_str}: {e}")


# ===========================================================================
# COLD LEAD CHECK — weekly Monday, summary of disengaged leads
# ===========================================================================
async def _cold_lead_weekly_check_job(context: ContextTypes.DEFAULT_TYPE):
    leads      = parse_leads_csv()
    cold_active = [l for l in leads
                   if l.get("status","").lower() == "active" and _score_lead(l)[0] == 1]
    if not cold_active:
        return

    total  = len(cold_active)
    sample = cold_active[:5]
    names  = "\n".join(
        f"  • {l.get('name','?')} — {l.get('program','?')} (Step {l.get('email_count','0')})"
        for l in sample
    )
    msg = (
        f"🧊 <b>Cold Lead Weekly Check</b>\n\n"
        f"<b>{total} active leads</b> haven't engaged (Step 0-4).\n\n"
        f"Top cold leads:\n{names}"
        + (f"\n  + {total-5} more" if total > 5 else "") +
        f"\n\n<b>Auto re-engagement running now</b> — special email going out to cold leads today.\n"
        f"→ /leads to review and update status"
    )
    for uid_str in list(_bot_state.get("users", {})):
        try:
            await context.bot.send_message(chat_id=int(uid_str), text=msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.warning(f"Cold lead check failed for {uid_str}: {e}")

# ===========================================================================
# TRADINGVIEW WEBHOOK SERVER (Flask — runs in background thread)
# ===========================================================================
TV_WEBHOOK_SECRET = os.environ.get("TV_WEBHOOK_SECRET", "enderun-tv-secret")
_tv_bot_app = None   # set in main() after app is built

def _start_tv_webhook_server():
    """Launch Flask webhook server on PORT (Railway) or 8088 (local)."""
    try:
        from flask import Flask, request as flask_request, jsonify
    except ImportError:
        logging.warning("[TV] Flask not available — webhook server not started")
        return

    flask_app = Flask(__name__)
    port = int(os.environ.get("PORT", 8088))

    @flask_app.route("/tv-alert", methods=["POST"])
    def tv_alert():
        # Validate secret token
        token = flask_request.args.get("secret", "") or flask_request.headers.get("X-TV-Secret", "")
        if token != TV_WEBHOOK_SECRET:
            return jsonify({"error": "unauthorized"}), 401

        try:
            data = flask_request.get_json(force=True, silent=True) or {}
        except Exception:
            data = {}

        # TradingView sends plain text or JSON — handle both
        raw_text = flask_request.get_data(as_text=True)
        if not data:
            data = {"message": raw_text}

        coin     = data.get("coin", data.get("symbol", "BTC")).upper().replace("USDT", "").replace("PERP", "").strip()
        signal   = data.get("signal", data.get("action", data.get("message", "Signal received")))
        price    = data.get("price", data.get("close", ""))
        interval = data.get("interval", data.get("timeframe", ""))
        indicator= data.get("indicator", "")
        exchange = data.get("exchange", "")

        price_str    = f" @ <b>${float(price):,.2f}</b>" if price else ""
        interval_str = f" [{interval}]" if interval else ""
        indicator_str= f"\n📐 <i>{html_module.escape(str(indicator))}</i>" if indicator else ""
        exchange_str = f" · {html_module.escape(str(exchange))}" if exchange else ""

        # Build the AI analysis prompt
        analysis_prompt = (
            f"TradingView alert just fired for {coin}/USDT{interval_str}:\n"
            f"Signal: {signal}\n"
            f"Price: {price or 'not provided'}\n"
            f"Indicator: {indicator or 'not specified'}\n\n"
            f"Give a concise trade assessment (3-5 sentences max):\n"
            f"1. Is this signal reliable? What confirms or weakens it?\n"
            f"2. Suggested entry zone, SL, and TP1 based on this signal\n"
            f"3. Risk level: Low / Medium / High\n"
            f"Keep it short — this is a real-time alert."
        )

        try:
            agent_md = load_agent("crypto-trader")
            claude_md = load_claude_md()
            sys_prompt = f"{claude_md}\n\n{agent_md}"
            tmp = [{"role": "user", "content": analysis_prompt}]
            analysis = call_claude_with_tools(sys_prompt, tmp)
        except Exception as e:
            logging.warning(f"[TV] Claude analysis failed: {e}")
            analysis = "⚠️ Claude analysis unavailable right now."

        signal_emoji = "🟢" if any(w in str(signal).lower() for w in ["buy","long","bullish","oversold","cross up","crossover"]) else \
                       "🔴" if any(w in str(signal).lower() for w in ["sell","short","bearish","overbought","cross down"]) else "⚡"

        msg = (
            f"{signal_emoji} <b>TradingView Alert — {html_module.escape(coin)}/USDT</b>{exchange_str}\n"
            f"📣 {html_module.escape(str(signal))}{price_str}{interval_str}"
            f"{indicator_str}\n\n"
            f"🤖 <b>Eva's Analysis:</b>\n{analysis}\n\n"
            f"<i>⚠️ Not financial advice. Always DYOR.</i>"
        )

        # Send to all registered Telegram users
        if _tv_bot_app:
            loop = asyncio.new_event_loop()
            def _send():
                async def _do():
                    users = list(BOT_STATE.get("users", {}).keys())
                    if not users:
                        users = [str(os.environ.get("TELEGRAM_CHAT_ID", ""))]
                    for uid in users:
                        if not uid:
                            continue
                        try:
                            await _tv_bot_app.bot.send_message(
                                chat_id=int(uid),
                                text=msg,
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception as e:
                            logging.warning(f"[TV] send to {uid}: {e}")
                asyncio.run(_do())
            threading.Thread(target=_send, daemon=True).start()

        logging.info(f"[TV] Alert processed: {coin} — {signal}")
        return jsonify({"ok": True, "coin": coin, "signal": str(signal)}), 200

    @flask_app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "Eva TV Webhook"}), 200

    logging.info(f"[TV] Webhook server starting on port {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set."); sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not set."); sys.exit(1)

    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
    load_bot_state()

    print("=" * 55)
    print("  Eva — Enderun Marketing AI")
    print("=" * 55)
    print(f"  Model    : {CLAUDE_MODEL}")
    print(f"  Agents   : {len(list_agents())} available")
    print(f"  Tools    : read_file · write_file · fetch_url · web_search · browser")
    print(f"  Context  : CLAUDE.md ({len(BRAND_CONTEXT):,} chars)")
    print(f"  Voice    : {'Enabled (Groq Whisper)' if GROQ_API_KEY else 'Disabled — set GROQ_API_KEY'}")
    print(f"  State    : {len(_bot_state.get('users', {}))} known users")
    print("=" * 55)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register bot commands so they appear in the "/" menu on all Telegram clients
    from telegram import BotCommand
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start",       "Say hi to Eva"),
            BotCommand("suggest",     "Eva's proactive recommendations for today"),
            BotCommand("recap",       "End-of-day summary — posts, leads, gaps"),
            BotCommand("voice",       "Toggle Eva's voice replies (English or Filipino)"),
            BotCommand("countdown",   "Days until enrollment deadlines"),
            BotCommand("gaps",        "Detect posting schedule gaps (next 14 days)"),
            BotCommand("tiktok",      "Generate a TikTok video script"),
            BotCommand("comment",     "Draft a reply to a Facebook/IG comment"),
            BotCommand("templates",   "Caption templates per program"),
            BotCommand("briefing",    "Morning briefing summary"),
            BotCommand("today",       "Today's image, leads & drip steps"),
            BotCommand("leads",       "Lead stats"),
            BotCommand("lead",        "Look up a lead by name or email"),
            BotCommand("addlead",     "Add a new lead"),
            BotCommand("reschedule",  "Move a scheduled post to a different date"),
            BotCommand("updatelead",  "Update lead status (active/inactive)"),
            BotCommand("schedule",    "Upcoming posting schedule"),
            BotCommand("lastposts",   "Last 15 generated captions"),
            BotCommand("report",      "Quick marketing snapshot in chat"),
            BotCommand("pdfreport",   "PDF report: /pdfreport | /pdfreport prompts | /pdfreport agents"),
            BotCommand("screenshot",  "Screenshot any URL: /screenshot [url]"),
            BotCommand("generate",    "Generate a social media image from a text prompt"),
            BotCommand("preview",     "Preview drip email for a lead: /preview [name or email]"),
            BotCommand("bulklead",    "Bulk lead operations"),
            BotCommand("retry",       "Retry a failed workflow"),
            BotCommand("remember",    "Save a note for the bot to always remember"),
            BotCommand("forget",      "Remove a saved note"),
            BotCommand("memories",    "View all saved notes"),
            BotCommand("post",        "Demo post to FB/IG/email"),
            BotCommand("agent",       "Switch agent role"),
            BotCommand("summary",     "Recap what happened this session"),
            BotCommand("clear",       "Clear conversation history"),
            BotCommand("status",      "Current agent and session info"),
            BotCommand("cal",          "Google Calendar — upcoming events"),
            BotCommand("addevent",    "Add event to Google Calendar"),
            BotCommand("inbox",       "Gmail inbox — latest unread emails"),
            BotCommand("searchmail",  "Search Gmail inbox"),
            BotCommand("syncsheets",  "Sync leads to/from Google Sheets"),
            BotCommand("drivelist",   "Browse Google Drive folders"),
            BotCommand("ideas",        "5 content ideas for a program or topic"),
            BotCommand("competitor",   "Quick competitor intel via web search"),
            BotCommand("hashtags",     "Hashtag sets for FB, IG, and TikTok"),
            BotCommand("whatsapp",     "Draft a WhatsApp follow-up for a lead"),
            BotCommand("addnote",      "Add a note to a lead"),
            BotCommand("draftemail",   "Draft a custom email for a lead"),
            BotCommand("trade",        "Crypto market analysis and trade setup"),
            BotCommand("scanner",          "Scan market for buy/sell signals"),
            BotCommand("positions",        "View open Bybit positions"),
            BotCommand("balance",          "View Bybit USDT balance"),
            BotCommand("paperscan",        "Paper trade: scan signals with fake money"),
            BotCommand("paperportfolio",   "Paper trade: view portfolio and PnL"),
            BotCommand("paperclose",       "Paper trade: close a position"),
            BotCommand("paperreset",       "Paper trade: reset account to $1000"),
            BotCommand("help",        "All commands"),
        ])
    app.post_init = set_commands

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("suggest",    cmd_suggest))
    app.add_handler(CommandHandler("recap",      cmd_recap))
    app.add_handler(CommandHandler("voice",      cmd_voice))
    app.add_handler(CommandHandler("countdown",  cmd_countdown))
    app.add_handler(CommandHandler("gaps",       cmd_gaps))
    app.add_handler(CommandHandler("tiktok",     cmd_tiktok))
    app.add_handler(CommandHandler("comment",    cmd_comment))
    app.add_handler(CommandHandler("templates",  cmd_templates))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("clear",      cmd_clear))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("chatid",     cmd_chatid))
    app.add_handler(CommandHandler("agent",      cmd_agent))
    app.add_handler(CommandHandler("post",       cmd_post))
    app.add_handler(CommandHandler("leads",      cmd_leads))
    app.add_handler(CommandHandler("lead",       cmd_lead))
    app.add_handler(CommandHandler("addlead",    cmd_add_lead))
    app.add_handler(CommandHandler("reschedule", cmd_reschedule))
    app.add_handler(CommandHandler("updatelead", cmd_updatelead))
    app.add_handler(CommandHandler("schedule",   cmd_schedule))
    app.add_handler(CommandHandler("briefing",   cmd_briefing))
    app.add_handler(CommandHandler("today",      cmd_today))
    app.add_handler(CommandHandler("retry",      cmd_retry))
    app.add_handler(CommandHandler("lastposts",  cmd_lastposts))
    app.add_handler(CommandHandler("remember",   cmd_remember))
    app.add_handler(CommandHandler("forget",     cmd_forget))
    app.add_handler(CommandHandler("memories",   cmd_memories))
    app.add_handler(CommandHandler("summary",    cmd_summary))
    app.add_handler(CommandHandler("report",     cmd_report))
    app.add_handler(CommandHandler("pdfreport",  cmd_pdfreport))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("generate",   cmd_generate))
    app.add_handler(CommandHandler("preview",    cmd_preview))
    app.add_handler(CommandHandler("bulklead",   cmd_bulklead))
    app.add_handler(CommandHandler("cal",          cmd_cal))
    app.add_handler(CommandHandler("addevent",    cmd_addevent))
    app.add_handler(CommandHandler("inbox",       cmd_inbox))
    app.add_handler(CommandHandler("searchmail",  cmd_searchmail))
    app.add_handler(CommandHandler("syncsheets",  cmd_syncsheets))
    app.add_handler(CommandHandler("drivelist",   cmd_drivelist))
    app.add_handler(CommandHandler("ideas",       cmd_ideas))
    app.add_handler(CommandHandler("competitor",  cmd_competitor))
    app.add_handler(CommandHandler("hashtags",    cmd_hashtags))
    app.add_handler(CommandHandler("whatsapp",    cmd_whatsapp))
    app.add_handler(CommandHandler("addnote",     cmd_addnote))
    app.add_handler(CommandHandler("draftemail",  cmd_draftemail))
    app.add_handler(CommandHandler("trade",       cmd_trade))
    app.add_handler(CommandHandler("scanner",        cmd_scanner))
    app.add_handler(CommandHandler("positions",      cmd_positions))
    app.add_handler(CommandHandler("balance",        cmd_balance))
    app.add_handler(CommandHandler("paperscan",      cmd_paperscan))
    app.add_handler(CommandHandler("paperportfolio", cmd_paperportfolio))
    app.add_handler(CommandHandler("paperclose",     cmd_paperclose))
    app.add_handler(CommandHandler("paperreset",     cmd_paperreset))
    app.add_handler(CommandHandler("broadcast",   cmd_broadcast))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Schedule morning briefing push at 7:30 AM PHT (= 23:30 UTC previous day)
    if app.job_queue:
        app.job_queue.run_daily(
            _push_morning_briefing,
            time=dtime(hour=23, minute=30, second=0, tzinfo=timezone.utc),
            name="morning_briefing",
        )
        # Competitor alert at 9:00 AM PHT (= 01:00 UTC)
        app.job_queue.run_daily(
            _competitor_alert_job,
            time=dtime(hour=1, minute=0, second=0, tzinfo=timezone.utc),
            name="competitor_alert",
        )
        # EOD recap at 5:00 PM PHT (= 09:00 UTC)
        app.job_queue.run_daily(
            _push_eod_recap,
            time=dtime(hour=9, minute=0, second=0, tzinfo=timezone.utc),
            name="eod_recap",
        )
        # Auto signal scanner every 15 minutes
        app.job_queue.run_repeating(
            _auto_signal_scan,
            interval=900,
            first=60,
            name="auto_scanner",
        )
        # Hot lead check every 4 hours
        app.job_queue.run_repeating(
            _hot_lead_check_job,
            interval=14400,
            first=120,
            name="hot_lead_check",
        )
        # Content gap alert at 9:00 PM PHT (= 13:00 UTC)
        app.job_queue.run_daily(
            _content_gap_alert_job,
            time=dtime(hour=13, minute=0, second=0, tzinfo=timezone.utc),
            name="content_gap_alert",
        )
        # Drip completion check at 10:00 AM PHT (= 02:00 UTC)
        app.job_queue.run_daily(
            _drip_completion_check_job,
            time=dtime(hour=2, minute=0, second=0, tzinfo=timezone.utc),
            name="drip_completion_check",
        )
        # Cold lead weekly check — Monday 6:00 AM PHT (= Sunday 22:00 UTC)
        app.job_queue.run_daily(
            _cold_lead_weekly_check_job,
            time=dtime(hour=22, minute=0, second=0, tzinfo=timezone.utc),
            days=(6,),   # Sunday UTC = Monday PHT
            name="cold_lead_weekly",
        )

    # Start TradingView webhook server in background thread
    global _tv_bot_app
    _tv_bot_app = app
    tv_thread = threading.Thread(target=_start_tv_webhook_server, daemon=True)
    tv_thread.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
