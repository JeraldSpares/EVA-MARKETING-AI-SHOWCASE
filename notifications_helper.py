# -*- coding: utf-8 -*-
"""
Enderun Marketing Hub - Notifications Helper
All automation scripts import push_notification() from here.
Writes to notifications.json which the dashboard polls every 30 seconds.
"""

import json
import os
import uuid
from pathlib import Path
from datetime import datetime

NOTIFICATIONS_FILE = Path(__file__).parent / "notifications.json"

AGENT_LABELS = {
    "social-listening":    "Social Listening",
    "drip-email":          "Drip Email",
    "facebook-post":       "Facebook Post",
    "weekly-analytics":    "Weekly Analytics",
    "campaign-preview":    "Campaign Preview",
    "competitor-analysis": "Competitor Intel",
    "webhook":             "Lead Capture",
}

AGENT_EMOJI = {
    "social-listening":    "🔍",
    "drip-email":          "📧",
    "facebook-post":       "📘",
    "weekly-analytics":    "📊",
    "campaign-preview":    "📅",
    "competitor-analysis": "🔬",
    "webhook":             "🎯",
}


def _load() -> dict:
    if NOTIFICATIONS_FILE.exists():
        try:
            with open(NOTIFICATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"notifications": []}


def _is_cloud() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS"))

def _save(data: dict):
    if _is_cloud():
        return  # No persistent file in GitHub Actions
    with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def push_notification(
    agent_id: str,
    level: str,
    title: str,
    message: str,
    report_path: str = None,
):
    """
    Push a notification to the shared store.

    agent_id   : one of the keys in AGENT_LABELS
    level      : "critical" | "warning" | "success" | "info"
    title      : short headline (max ~60 chars)
    message    : supporting detail (1–2 sentences)
    report_path: optional relative path to the saved report file
    """
    data = _load()

    notif = {
        "id":          str(uuid.uuid4()),
        "agent_id":    agent_id,
        "agent_label": AGENT_LABELS.get(agent_id, agent_id.replace("-", " ").title()),
        "agent_emoji": AGENT_EMOJI.get(agent_id, "🤖"),
        "level":       level,
        "title":       title,
        "message":     message,
        "timestamp":   datetime.now().isoformat(),
        "read":        False,
        "report_path": report_path,
    }

    data["notifications"].insert(0, notif)

    # Keep only the latest 100 notifications
    data["notifications"] = data["notifications"][:100]

    _save(data)
    return notif["id"]


def mark_read(notification_id: str):
    data = _load()
    for n in data["notifications"]:
        if n["id"] == notification_id:
            n["read"] = True
            break
    _save(data)


def mark_all_read():
    data = _load()
    for n in data["notifications"]:
        n["read"] = True
    _save(data)


def clear_all():
    _save({"notifications": []})


def get_all() -> list:
    return _load().get("notifications", [])


def unread_count() -> int:
    return sum(1 for n in get_all() if not n.get("read"))
