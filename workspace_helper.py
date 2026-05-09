# -*- coding: utf-8 -*-
"""
Google Workspace Helper for Eva — Calendar, Sheets, Gmail IMAP, Drive
Uses the same GOOGLE_DRIVE_CREDENTIALS service account as drive_helper.py.

Setup per integration:
  Calendar : Share the calendar with the service account email (Editor role)
             Set GOOGLE_CALENDAR_ID in Railway env vars
  Sheets   : Share the Google Sheet with the service account email (Editor role)
             Set GOOGLE_LEADS_SHEET_ID in Railway env vars
  Gmail    : Uses IMAP — existing GMAIL_ADDRESS + GMAIL_APP_PASS env vars
  Drive    : Uses same GOOGLE_DRIVE_CREDENTIALS — no extra setup needed
"""

import os
import json
import io
import imaplib
import email as email_lib
import logging
from datetime import datetime, timedelta, timezone

PHT = timezone(timedelta(hours=8))

CREDS_ENV             = "GOOGLE_DRIVE_CREDENTIALS"
GOOGLE_CALENDAR_ID    = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_LEADS_SHEET_ID = os.environ.get("GOOGLE_LEADS_SHEET_ID", "")
GMAIL_ADDRESS         = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS        = os.environ.get("GMAIL_APP_PASS", "")


def _get_creds(scopes: list):
    """Return Google service account credentials with the given scopes."""
    from google.oauth2 import service_account
    creds_json = os.environ.get(CREDS_ENV)
    if not creds_json:
        creds_file = os.path.join(os.path.dirname(__file__), "google_credentials.json")
        with open(creds_file) as f:
            creds_json = f.read()
    info = json.loads(creds_json)
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)


# =============================================================================
# GOOGLE CALENDAR
# =============================================================================

def list_calendar_events(days: int = 7) -> list:
    """Return upcoming calendar events for the next N days (PHT)."""
    try:
        from googleapiclient.discovery import build
        creds   = _get_creds(["https://www.googleapis.com/auth/calendar.readonly"])
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now     = datetime.now(PHT)
        result  = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days)).isoformat(),
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])
    except Exception as e:
        logging.warning(f"[calendar] list_events: {e}")
        return []


def add_calendar_event(title: str, date_str: str, time_str: str = "",
                       description: str = "", duration_hours: int = 1) -> dict:
    """
    Add an event to Google Calendar.
    date_str : YYYY-MM-DD
    time_str : HH:MM  (24h, optional — all-day if omitted)
    Returns the created event dict, or {} on failure.
    """
    try:
        from googleapiclient.discovery import build
        creds   = _get_creds(["https://www.googleapis.com/auth/calendar"])
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        if time_str:
            start_iso = f"{date_str}T{time_str}:00+08:00"
            start_dt  = datetime.fromisoformat(start_iso)
            end_dt    = start_dt + timedelta(hours=duration_hours)
            end_iso   = end_dt.isoformat()
            start = {"dateTime": start_iso, "timeZone": "Asia/Manila"}
            end   = {"dateTime": end_iso,   "timeZone": "Asia/Manila"}
        else:
            start = {"date": date_str}
            end   = {"date": date_str}
        body = {"summary": title, "description": description, "start": start, "end": end}
        return service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()
    except Exception as e:
        logging.warning(f"[calendar] add_event: {e}")
        return {}


def format_events_text(events: list, header: str = "") -> str:
    """Format event list as plain text for Telegram."""
    if not events:
        return (header or "") + "No events scheduled."
    lines = [header] if header else []
    for ev in events:
        start = ev.get("start", {})
        if "dateTime" in start:
            dt  = datetime.fromisoformat(start["dateTime"])
            lbl = dt.strftime("%a %b %d · %I:%M %p")
        else:
            dt  = datetime.fromisoformat(start.get("date", "2026-01-01"))
            lbl = dt.strftime("%a %b %d · All day")
        title = ev.get("summary", "(no title)")
        lines.append(f"📅 {lbl}\n   {title}")
    return "\n\n".join(lines)


# =============================================================================
# GOOGLE SHEETS — LEADS
# =============================================================================

def read_leads_from_sheet() -> list:
    """Read all leads from the Google Sheet. Returns list of dicts."""
    if not GOOGLE_LEADS_SHEET_ID:
        return []
    try:
        from googleapiclient.discovery import build
        creds   = _get_creds(["https://www.googleapis.com/auth/spreadsheets.readonly"])
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result  = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_LEADS_SHEET_ID,
            range="Sheet1!A:Z",
        ).execute()
        values = result.get("values", [])
        if not values:
            return []
        headers = values[0]
        rows = []
        for row in values[1:]:
            padded = row + [""] * (len(headers) - len(row))
            rows.append(dict(zip(headers, padded)))
        return rows
    except Exception as e:
        logging.warning(f"[sheets] read_leads: {e}")
        return []


def write_leads_to_sheet(rows: list, headers: list) -> bool:
    """Write all leads to Google Sheet (full overwrite starting at A1)."""
    if not GOOGLE_LEADS_SHEET_ID:
        return False
    try:
        from googleapiclient.discovery import build
        creds   = _get_creds(["https://www.googleapis.com/auth/spreadsheets"])
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        values  = [headers] + [[row.get(h, "") for h in headers] for row in rows]
        service.spreadsheets().values().update(
            spreadsheetId=GOOGLE_LEADS_SHEET_ID,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        return True
    except Exception as e:
        logging.warning(f"[sheets] write_leads: {e}")
        return False


def get_sheet_url() -> str:
    """Return the Google Sheet browser URL."""
    if not GOOGLE_LEADS_SHEET_ID:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{GOOGLE_LEADS_SHEET_ID}/edit"


# =============================================================================
# GMAIL — IMAP READ
# =============================================================================

def search_gmail(query: str = "is:unread", limit: int = 5) -> list:
    """
    Search Gmail inbox via IMAP.
    query examples: "is:unread", "from:maria", "subject:enrollment"
    Returns list of {subject, sender, date, snippet}.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
        return [{"subject": "Gmail not configured", "sender": "",
                 "date": "", "snippet": "Set GMAIL_ADDRESS and GMAIL_APP_PASS in Railway."}]
    results = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        mail.select("inbox")

        # Build IMAP search string from Gmail-style query
        imap_q = _gmail_query_to_imap(query)
        _, data = mail.search(None, imap_q)
        ids = [x for x in data[0].split() if x]
        for uid in reversed(ids[-limit:]):
            try:
                _, msg_data = mail.fetch(uid, "(RFC822)")
                msg     = email_lib.message_from_bytes(msg_data[0][1])
                subject = _decode_header(msg.get("Subject", "(no subject)"))
                sender  = _decode_header(msg.get("From", ""))
                date    = msg.get("Date", "")
                snippet = _get_text_snippet(msg, 300)
                results.append({"subject": subject, "sender": sender,
                                 "date": date, "snippet": snippet})
            except Exception as e:
                logging.warning(f"[gmail] fetch msg: {e}")
        mail.logout()
    except Exception as e:
        results = [{"subject": f"IMAP error: {e}", "sender": "", "date": "", "snippet": ""}]
    return results


def _gmail_query_to_imap(query: str) -> str:
    q = query.strip().lower()
    if q in ("is:unread", "unread"):
        return "UNSEEN"
    if q.startswith("from:"):
        return f'FROM "{q[5:].strip()}"'
    if q.startswith("subject:"):
        return f'SUBJECT "{q[8:].strip()}"'
    if q.startswith("to:"):
        return f'TO "{q[3:].strip()}"'
    # Free text search
    clean = q.replace("is:unread", "").strip()
    return f'TEXT "{clean}"' if clean else "ALL"


def _decode_header(value: str) -> str:
    import email.header
    parts = email.header.decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _get_text_snippet(msg, max_chars: int = 300) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")[:max_chars].strip()
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8", errors="replace")[:max_chars].strip()
        except Exception:
            pass
    return ""


def format_emails_text(emails: list, header: str = "") -> str:
    """Format email list as plain text for Telegram."""
    if not emails:
        return (header or "") + "No emails found."
    lines = [header] if header else []
    for em in emails:
        lines.append(
            f"📧 <b>{em['subject'][:60]}</b>\n"
            f"   From: {em['sender'][:50]}\n"
            f"   {em['date'][:30]}\n"
            + (f"   <i>{em['snippet'][:150]}…</i>" if em['snippet'] else "")
        )
    return "\n\n".join(lines)


# =============================================================================
# GOOGLE DRIVE — EXPANDED
# =============================================================================

def list_drive_folders(parent_id: str = None) -> list:
    """List all folders visible to the service account (optional: inside parent_id)."""
    try:
        from googleapiclient.discovery import build
        creds   = _get_creds(["https://www.googleapis.com/auth/drive.readonly"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        result = service.files().list(
            q=q,
            fields="files(id, name)",
            pageSize=50,
            orderBy="name",
        ).execute()
        return result.get("files", [])
    except Exception as e:
        logging.warning(f"[drive] list_folders: {e}")
        return []


def list_drive_files(folder_id: str, limit: int = 15) -> list:
    """List files inside a Drive folder, newest first."""
    try:
        from googleapiclient.discovery import build
        creds   = _get_creds(["https://www.googleapis.com/auth/drive.readonly"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        result  = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
            fields="files(id, name, mimeType, modifiedTime, size)",
            pageSize=limit,
            orderBy="modifiedTime desc",
        ).execute()
        return result.get("files", [])
    except Exception as e:
        logging.warning(f"[drive] list_files: {e}")
        return []


def upload_to_drive(filename: str, file_bytes: bytes,
                    folder_id: str, mime_type: str = "image/jpeg") -> str:
    """Upload a file to a specific Drive folder. Returns file ID or ''."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        creds    = _get_creds(["https://www.googleapis.com/auth/drive.file"])
        service  = build("drive", "v3", credentials=creds, cache_discovery=False)
        metadata = {"name": filename, "parents": [folder_id]}
        media    = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type)
        f        = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return f.get("id", "")
    except Exception as e:
        logging.warning(f"[drive] upload: {e}")
        return ""
