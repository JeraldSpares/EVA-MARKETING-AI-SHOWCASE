# -*- coding: utf-8 -*-
"""
Enderun Extension - Weekly Campaign Preview
Generates a branded PDF showing next week's Facebook & Instagram posts + drip email schedule.
Light brown professional theme. Emails PDF every Sunday at 5PM.

Run manually : python weekly_campaign_preview.py
Auto schedule : GitHub Actions — every Sunday 5:00 PM PHT
"""

import os
import sys
import csv
import json
import smtplib
import uuid
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from io import BytesIO
from urllib.parse import quote

import anthropic
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image as RLImage, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from notifications_helper import push_notification

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

BASE_DIR       = Path(__file__).parent
SCHEDULE_FILE  = BASE_DIR / "posting_schedule.json"
LEADS_FILE     = BASE_DIR / "leads.csv"
LOGO_PATH      = BASE_DIR / "assets" / "logos" / "enderun_extension_logo.png"
FB_ICON_PATH     = BASE_DIR / "assets" / "icons" / "fb.png"
IG_ICON_PATH     = BASE_DIR / "assets" / "icons" / "Instagram.png"
GMAIL_ICON_PATH  = BASE_DIR / "assets" / "icons" / "gmail.png"
OUTPUT_DIR     = BASE_DIR / "output" / "reports" / "weekly_preview"
STATE_FILE     = BASE_DIR / "preview_state.json"
RECIPIENTS     = ["eva@enderuncolleges.com"]

# ---------------------------------------------------------------------------
# BRAND COLORS — Light Brown Professional Theme
# ---------------------------------------------------------------------------

BROWN_DARK  = colors.HexColor("#5C3D2E")   # Dark brown — headers, titles
BROWN_MED   = colors.HexColor("#8B6349")   # Medium brown — subheadings
BROWN_LIGHT = colors.HexColor("#C4A882")   # Light brown — accents
GOLD        = colors.HexColor("#C9A84C")   # Gold — highlight accents
CREAM_BG    = colors.HexColor("#FAF7F2")   # Warm cream — backgrounds
CREAM_ROW   = colors.HexColor("#F5EDE0")   # Slightly darker cream — alt rows
BEIGE       = colors.HexColor("#E8DDD0")   # Beige — borders, dividers
WHITE       = colors.white
TEXT_DARK   = colors.HexColor("#2C1810")   # Very dark brown — body text
TEXT_MED    = colors.HexColor("#5C3D2E")   # Medium dark — secondary text
TEXT_LIGHT  = colors.HexColor("#8B6349")   # Light brown — captions, labels
CORAL       = colors.HexColor("#E8603C")   # Coral — alerts

FB_HASHTAGS = (
    "#EnderunExtension #EnderunColleges #BGC #McKinleyHill "
    "#ProfessionalDevelopment #LifelongLearning #UpskillPH "
    "#CulinaryArts #HospitalityPH #LearnWithEnderun"
)

IG_HASHTAGS = (
    "#EnderunExtension #EnderunColleges #BGC #McKinleyHill "
    "#ProfessionalDevelopment #LifelongLearning #UpskillPH "
    "#CulinaryArts #HospitalityPH #LearnWithEnderun "
    "#ContinuingEducation #CareerGrowth #ManilaPH "
    "#FoodEducation #HospitalityEducation #WineEducation "
    "#ServSafe #WSET #TESDA #ProfessionalCertification "
    "#CulinarySchoolPH #HospitalitySchool #BGCManila "
    "#SkillsForLife #CareerShift #UpgradeYourself "
    "#PhilippinesEducation #LearnMoreEarnMore"
)

# ---------------------------------------------------------------------------
# DATA HELPERS
# ---------------------------------------------------------------------------

def get_upcoming_week() -> list:
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days_until_monday)
    return [(next_monday + timedelta(days=i), (next_monday + timedelta(days=i)).strftime("%A"))
            for i in range(7)]


def load_schedule() -> dict:
    if not SCHEDULE_FILE.exists():
        return {}
    with open(SCHEDULE_FILE, "r") as f:
        return json.load(f).get("schedule", {})


def load_leads() -> list:
    leads = []
    if not LEADS_FILE.exists():
        return leads
    with open(LEADS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "").strip().lower() == "active":
                if not row.get("email_count"):
                    row["email_count"] = "0"
                leads.append(row)
    return leads


def get_all_sequence_images(schedule: dict) -> list:
    return [schedule[k] for k in sorted(schedule.keys())]


def get_drip_image_for(email_count: int, all_images: list) -> str:
    if not all_images:
        return "No images"
    return all_images[email_count % len(all_images)]


def shorten(text: str, max_len: int = 28) -> str:
    name = Path(text).stem
    return name if len(name) <= max_len else name[:max_len - 1] + "…"


def generate_caption_preview(image_filename: str) -> str:
    """Generate a short FB caption preview based on the image filename."""
    stem = Path(image_filename).stem.replace("-", " ").replace("_", " ")
    if not ANTHROPIC_KEY:
        return f"Engaging post about {stem[:40]}..."

    extra_context = os.environ.get("CAPTION_CONTEXT", "").strip()
    context_note  = f" Incorporate this feedback from the marketing manager: {extra_context}" if extra_context else ""

    prompt = (
        f'You are Enderun Extension\'s social media manager in BGC, Philippines. '
        f'Based on the image filename "{stem}", write a 1-2 sentence Facebook caption preview '
        f'(max 30 words). Be specific, aspirational, and warm. No hashtags. No quotes.'
        f'{context_note}'
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception:
        return stem[:60]

# ---------------------------------------------------------------------------
# PDF STYLES
# ---------------------------------------------------------------------------

def make_styles():
    return {
        "title": ParagraphStyle("title",
            fontSize=20, textColor=BROWN_DARK, fontName="Helvetica-Bold",
            spaceAfter=2, leading=24),
        "subtitle": ParagraphStyle("subtitle",
            fontSize=10, textColor=TEXT_LIGHT, fontName="Helvetica",
            spaceAfter=0, leading=14),
        "hdr_date": ParagraphStyle("hdr_date",
            fontSize=9, textColor=BROWN_DARK, fontName="Helvetica-Bold",
            alignment=TA_RIGHT, leading=13),
        "hdr_sub": ParagraphStyle("hdr_sub",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica",
            alignment=TA_RIGHT, leading=11),
        "section_hdr": ParagraphStyle("section_hdr",
            fontSize=9.5, textColor=WHITE, fontName="Helvetica-Bold", leading=13),
        "section_note": ParagraphStyle("section_note",
            fontSize=8, textColor=TEXT_LIGHT, fontName="Helvetica",
            leading=11, spaceAfter=4),
        "th": ParagraphStyle("th",
            fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", leading=11),
        "th_center": ParagraphStyle("th_center",
            fontSize=8, textColor=WHITE, fontName="Helvetica-Bold",
            leading=11, alignment=TA_CENTER),
        "cell_day": ParagraphStyle("cell_day",
            fontSize=9, textColor=BROWN_DARK, fontName="Helvetica-Bold", leading=12),
        "cell_date": ParagraphStyle("cell_date",
            fontSize=8.5, textColor=TEXT_MED, fontName="Helvetica", leading=11),
        "cell_img": ParagraphStyle("cell_img",
            fontSize=8, textColor=TEXT_MED, fontName="Helvetica", leading=11),
        "cell_caption": ParagraphStyle("cell_caption",
            fontSize=8, textColor=TEXT_DARK, fontName="Helvetica",
            leading=12, alignment=TA_JUSTIFY),
        "cell_status_ok": ParagraphStyle("cell_status_ok",
            fontSize=7.5, textColor=colors.HexColor("#2D6A4F"),
            fontName="Helvetica-Bold", leading=10, alignment=TA_CENTER),
        "cell_status_none": ParagraphStyle("cell_status_none",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica",
            leading=10, alignment=TA_CENTER),
        "cell_bold": ParagraphStyle("cell_bold",
            fontSize=8.5, textColor=BROWN_DARK, fontName="Helvetica-Bold", leading=11),
        "cell_normal": ParagraphStyle("cell_normal",
            fontSize=8, textColor=TEXT_DARK, fontName="Helvetica", leading=11),
        "cell_gold": ParagraphStyle("cell_gold",
            fontSize=7.5, textColor=GOLD, fontName="Helvetica-Bold", leading=10),
        "cell_light": ParagraphStyle("cell_light",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica", leading=10),
        "hashtag_title": ParagraphStyle("hashtag_title",
            fontSize=8.5, textColor=BROWN_DARK, fontName="Helvetica-Bold",
            leading=12, spaceAfter=3),
        "hashtag_text": ParagraphStyle("hashtag_text",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica",
            leading=12, alignment=TA_JUSTIFY),
        "kpi_num": ParagraphStyle("kpi_num",
            fontSize=24, textColor=BROWN_DARK, fontName="Helvetica-Bold",
            alignment=TA_CENTER, leading=28),
        "kpi_num_gold": ParagraphStyle("kpi_num_gold",
            fontSize=24, textColor=GOLD, fontName="Helvetica-Bold",
            alignment=TA_CENTER, leading=28),
        "kpi_label": ParagraphStyle("kpi_label",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica",
            alignment=TA_CENTER, leading=10),
        "legend": ParagraphStyle("legend",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica", leading=11),
        "footer": ParagraphStyle("footer",
            fontSize=7.5, textColor=TEXT_LIGHT, fontName="Helvetica",
            alignment=TA_CENTER, leading=10),
    }

# ---------------------------------------------------------------------------
# BUILD PDF
# ---------------------------------------------------------------------------

def build_pdf(week_dates: list, schedule: dict, leads: list) -> bytes:
    S = make_styles()
    all_images = get_all_sequence_images(schedule)
    buf = BytesIO()

    W, H = A4
    margin = 18 * mm
    usable_w = W - 2 * margin

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=14 * mm, bottomMargin=16 * mm
    )

    story = []
    week_start  = week_dates[0][0].strftime("%B %d")
    week_end    = week_dates[-1][0].strftime("%B %d, %Y")
    week_label  = f"Week of {week_start} – {week_end}"
    generated   = date.today().strftime("%B %d, %Y")

    # ── GOLD TOP BAR ─────────────────────────────────────────────────────────
    story.append(Table([[""]], colWidths=[usable_w], rowHeights=[4],
        style=TableStyle([("BACKGROUND", (0,0), (-1,-1), GOLD)])))

    # ── HEADER ───────────────────────────────────────────────────────────────
    logo_cell = RLImage(str(LOGO_PATH), width=160, height=44) \
                if LOGO_PATH.exists() \
                else Paragraph("<b>ENDERUN EXTENSION</b>", S["title"])

    title_block = [
        Paragraph("Weekly Campaign Preview", S["title"]),
        Paragraph(week_label, S["subtitle"]),
    ]
    right_block = [
        Paragraph(generated, S["hdr_date"]),
        Spacer(1, 2),
        Paragraph("FACEBOOK  &amp;  INSTAGRAM  &amp;  DRIP EMAIL", S["hdr_sub"]),
    ]

    hdr = Table([[logo_cell, title_block, right_block]],
                colWidths=[170, usable_w - 280, 100])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), WHITE),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",         (2,0), (2,0),   "RIGHT"),
        ("LEFTPADDING",   (0,0), (0,0),   12),
        ("LEFTPADDING",   (1,0), (1,0),   10),
        ("RIGHTPADDING",  (2,0), (2,0),   12),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
    ]))
    story.append(hdr)

    # ── BROWN ACCENT LINE ────────────────────────────────────────────────────
    story.append(Table([[""]], colWidths=[usable_w], rowHeights=[3],
        style=TableStyle([("BACKGROUND", (0,0), (-1,-1), BROWN_MED)])))
    story.append(Spacer(1, 10))

    # ── META LINE ────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"Generated: {generated}  •  Auto-run every Sunday 5:00 PM PHT  •  Enderun Marketing AI",
        S["footer"]
    ))
    story.append(Spacer(1, 12))

    # ── KPI CARDS ────────────────────────────────────────────────────────────
    fb_count     = sum(1 for d, _ in week_dates if d.strftime("%Y-%m-%d") in schedule)
    active_leads = len(leads)
    total_emails = active_leads * 7

    kpi_data = [[
        [Paragraph(str(fb_count),    S["kpi_num"]),      Spacer(1,2), Paragraph("FB + IG Posts",    S["kpi_label"])],
        [Paragraph(str(active_leads),S["kpi_num_gold"]), Spacer(1,2), Paragraph("Active Leads",     S["kpi_label"])],
        [Paragraph(str(total_emails),S["kpi_num"]),      Spacer(1,2), Paragraph("Drip Emails",      S["kpi_label"])],
        [Paragraph("7",              S["kpi_num_gold"]), Spacer(1,2), Paragraph("Days Scheduled",   S["kpi_label"])],
    ]]
    cw = usable_w / 4
    kpi_t = Table(kpi_data, colWidths=[cw]*4, rowHeights=[62])
    kpi_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,0), colors.HexColor("#FDF8F0")),
        ("BACKGROUND",    (1,0), (1,0), colors.HexColor("#FAF4E8")),
        ("BACKGROUND",    (2,0), (2,0), colors.HexColor("#FDF8F0")),
        ("BACKGROUND",    (3,0), (3,0), colors.HexColor("#FAF4E8")),
        ("BOX",           (0,0), (-1,-1), 0.5, BEIGE),
        ("LINEAFTER",     (0,0), (2,0),   0.5, BEIGE),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(kpi_t)
    story.append(Spacer(1, 14))

    # ── SECTION 1: FACEBOOK & INSTAGRAM POST SCHEDULE ────────────────────────
    sec1_hdr = Table(
        [[Paragraph("  Facebook & Instagram Post Schedule — Upcoming Week", S["section_hdr"])]],
        colWidths=[usable_w]
    )
    sec1_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), BROWN_DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ]))
    story.append(sec1_hdr)
    story.append(Spacer(1, 1))
    story.append(Paragraph(
        "Both Facebook and Instagram are posted daily at 8:00 AM PHT with platform-optimized AI captions. "
        "Caption preview below is Facebook-style; Instagram receives a shorter, lifestyle-forward version automatically.",
        S["section_note"]
    ))

    # Generate caption previews for scheduled images
    print("  Generating caption previews...")
    caption_cache = {}
    for d, _ in week_dates:
        date_key = d.strftime("%Y-%m-%d")
        img = schedule.get(date_key)
        if img and img not in caption_cache:
            caption_cache[img] = generate_caption_preview(img)

    # Columns: Day | Date | Image Filename | Caption Preview | Status
    col_w = [74, 44, 90, usable_w - 74 - 44 - 90 - 70, 70]

    fb_header = [
        Paragraph("DAY",            S["th"]),
        Paragraph("DATE",           S["th"]),
        Paragraph("IMAGE FILE",     S["th"]),
        Paragraph("CAPTION PREVIEW (FB)", S["th"]),
        Paragraph("PLATFORMS",      S["th_center"]),
    ]
    fb_rows = [fb_header]

    for d, day_name in week_dates:
        date_key = d.strftime("%Y-%m-%d")
        img_file = schedule.get(date_key)
        if img_file:
            caption    = caption_cache.get(img_file, "—")
            img_cell   = Paragraph(shorten(img_file, 30), S["cell_img"])
            cap_cell   = Paragraph(caption, S["cell_caption"])
            # Platform cell: FB icon + IG icon stacked
            fb_icon = RLImage(str(FB_ICON_PATH), width=13, height=13) if FB_ICON_PATH.exists() else Paragraph("FB", S["cell_status_ok"])
            ig_icon = RLImage(str(IG_ICON_PATH), width=13, height=13) if IG_ICON_PATH.exists() else Paragraph("IG", S["cell_status_ok"])
            plat_inner = Table([[fb_icon, ig_icon]], colWidths=[20, 20])
            plat_inner.setStyle(TableStyle([
                ("ALIGN",        (0,0), (-1,-1), "CENTER"),
                ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
                ("LEFTPADDING",  (0,0), (-1,-1), 2),
                ("RIGHTPADDING", (0,0), (-1,-1), 2),
                ("TOPPADDING",   (0,0), (-1,-1), 0),
                ("BOTTOMPADDING",(0,0), (-1,-1), 0),
            ]))
            plat_cell  = plat_inner
            row_bg     = CREAM_ROW
        else:
            img_cell   = Paragraph("— No post scheduled —", S["cell_light"])
            cap_cell   = Paragraph("—", S["cell_light"])
            plat_cell  = Paragraph("—", S["cell_status_none"])
            row_bg     = WHITE

        fb_rows.append([
            Paragraph(day_name,            S["cell_day"]),
            Paragraph(d.strftime("%b %d"), S["cell_date"]),
            img_cell,
            cap_cell,
            plat_cell,
        ])

    fb_table = Table(fb_rows, colWidths=col_w, repeatRows=1)
    fb_style = [
        ("BACKGROUND",    (0,0), (-1,0),  BROWN_DARK),
        ("LINEBELOW",     (0,0), (-1,0),  1.5, GOLD),
        ("GRID",          (0,0), (-1,-1), 0.4, BEIGE),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 7),
        ("ALIGN",         (4,0), (4,-1),  "CENTER"),
    ]
    for i, (d, _) in enumerate(week_dates, start=1):
        bg = CREAM_ROW if schedule.get(d.strftime("%Y-%m-%d")) else WHITE
        fb_style.append(("BACKGROUND", (0,i), (-1,i), bg))

    fb_table.setStyle(TableStyle(fb_style))
    story.append(fb_table)

    # ── SECTION 2: DRIP EMAIL SCHEDULE (starts on page 2) ────────────────────
    from reportlab.platypus import PageBreak
    story.append(PageBreak())
    gmail_icon = RLImage(str(GMAIL_ICON_PATH), width=14, height=10) if GMAIL_ICON_PATH.exists() else None
    sec2_hdr_content = [gmail_icon, Paragraph("  Drip Email Schedule — Per Lead, Per Day", S["section_hdr"])] \
                       if gmail_icon else [Paragraph("  Drip Email Schedule — Per Lead, Per Day", S["section_hdr"])]
    sec2_hdr_row = Table([sec2_hdr_content], colWidths=[24, usable_w - 24] if gmail_icon else [usable_w])
    sec2_hdr_row.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))
    sec2_hdr = Table([[sec2_hdr_row]], colWidths=[usable_w])
    sec2_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), BROWN_MED),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
    ]))
    story.append(sec2_hdr)
    story.append(Spacer(1, 1))

    day_abbr    = [d.strftime("%a %d") for d, _ in week_dates]
    lead_col_w  = 100
    drip_col_w  = (usable_w - lead_col_w) / 7

    drip_header = [Paragraph("LEAD / PROGRAM", S["th"])] + \
                  [Paragraph(da, S["th_center"]) for da in day_abbr]
    drip_rows   = [drip_header]

    for lead in leads:
        name    = f"{lead['first_name']} {lead['last_name']}"
        program = lead.get("program_interest", "")
        ec      = int(lead.get("email_count", 0))

        lead_cell = [
            Paragraph(name,    S["cell_bold"]),
            Paragraph(program, S["cell_light"]),
        ]
        day_cells = []
        for offset in range(7):
            this_count = ec + offset
            img        = get_drip_image_for(this_count, all_images)
            email_num  = this_count + 1
            day_cells.append([
                Paragraph(f"Email #{email_num}", S["cell_gold"]),
                Paragraph(shorten(img, 16),      S["cell_light"]),
            ])
        drip_rows.append([lead_cell] + day_cells)

    drip_t = Table(drip_rows,
                   colWidths=[lead_col_w] + [drip_col_w] * 7,
                   repeatRows=1)
    drip_style = [
        ("BACKGROUND",    (0,0), (-1,0),  BROWN_MED),
        ("LINEBELOW",     (0,0), (-1,0),  1.5, GOLD),
        ("GRID",          (0,0), (-1,-1), 0.4, BEIGE),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
    ]
    for i in range(1, len(leads) + 1):
        bg = CREAM_ROW if i % 2 == 0 else WHITE
        drip_style.append(("BACKGROUND", (0,i), (-1,i), bg))

    drip_t.setStyle(TableStyle(drip_style))
    story.append(drip_t)
    story.append(Spacer(1, 14))

    # ── SECTION 3: HASHTAGS ───────────────────────────────────────────────────
    sec3_hdr = Table(
        [[Paragraph("  Standard Hashtag Sets", S["section_hdr"])]],
        colWidths=[usable_w]
    )
    sec3_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), BROWN_LIGHT),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ]))
    story.append(sec3_hdr)
    story.append(Spacer(1, 6))

    half_w = (usable_w - 8) / 2
    def _icon_title(icon_path, label):
        """Return a small table: [icon | title text] for hashtag section headers."""
        if icon_path.exists():
            icon = RLImage(str(icon_path), width=11, height=11)
            t = Table([[icon, Paragraph(f"  {label}", S["hashtag_title"])]], colWidths=[18, half_w - 28])
            t.setStyle(TableStyle([
                ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
                ("LEFTPADDING",  (0,0), (-1,-1), 0),
                ("RIGHTPADDING", (0,0), (-1,-1), 0),
                ("TOPPADDING",   (0,0), (-1,-1), 0),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ]))
            return t
        return Paragraph(label, S["hashtag_title"])

    hashtag_data = [[
        [
            _icon_title(FB_ICON_PATH, "Facebook Hashtags"),
            Paragraph(FB_HASHTAGS, S["hashtag_text"]),
        ],
        [
            _icon_title(IG_ICON_PATH, "Instagram Hashtags"),
            Paragraph(IG_HASHTAGS, S["hashtag_text"]),
        ],
    ]]
    ht = Table(hashtag_data, colWidths=[half_w, half_w])
    ht.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), CREAM_BG),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("BOX",           (0,0), (-1,-1), 0.5, BEIGE),
        ("LINEAFTER",     (0,0), (0,-1),  0.5, BEIGE),
    ]))
    story.append(ht)
    story.append(Spacer(1, 10))

    # ── LEGEND ───────────────────────────────────────────────────────────────
    if all_images:
        story.append(Paragraph(
            f"Drip Sequence: Each lead rotates through {len(all_images)} scheduled images. "
            f"Sequence resets automatically after {len(all_images)} emails.",
            S["legend"]
        ))

    # ── PAGE FOOTER FUNCTION ──────────────────────────────────────────────────
    def add_footer(canvas, doc):
        canvas.saveState()
        pw, ph = A4
        mg = 18 * mm
        canvas.setFillColor(BROWN_MED)
        canvas.rect(0, 0, pw, 4, fill=1, stroke=0)
        canvas.setFillColor(TEXT_LIGHT)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(mg, 9, "Enderun Colleges  •  Enderun Extension  •  enderunextension.com")
        canvas.drawRightString(pw - mg, 9, f"Page {doc.page}  |  Weekly Campaign Preview")
        canvas.restoreState()

    frame = Frame(margin, 16 * mm, usable_w, H - 30 * mm, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=add_footer)])
    doc.build(story)
    return buf.getvalue()

# ---------------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------------

def send_preview_email(pdf_bytes: bytes, week_dates: list) -> str:
    """Send the weekly preview email. Returns the Message-ID string."""
    week_label    = f"{week_dates[0][0].strftime('%B %d')} – {week_dates[-1][0].strftime('%B %d, %Y')}"
    subject       = f"Weekly Campaign Preview — {week_label}"
    filename      = f"weekly_preview_{week_dates[0][0].strftime('%Y-%m-%d')}.pdf"
    msg_id        = make_msgid(domain="enderun.ai")

    reply_subject = quote(f"Re: {subject}")
    approve_href  = f"mailto:{GMAIL_ADDRESS}?subject={reply_subject}&body=approved"
    changes_href  = (
        f"mailto:{GMAIL_ADDRESS}?subject={reply_subject}"
        f"&body={quote('Please make these changes:%0A%0A- ')}"
    )

    body_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F4F0EB;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F0EB;padding:24px 0;">
  <tr><td align="center">
    <table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>
      <tr>
        <td style="background:#5C3D2E;padding:20px 36px;">
          <table width="100%"><tr>
            <td>
              <p style="margin:0;font-size:10px;letter-spacing:3px;color:#C9A84C;text-transform:uppercase;font-weight:700;">Enderun Marketing Intelligence</p>
              <p style="margin:4px 0 0;font-size:17px;color:#fff;font-weight:700;">Weekly Campaign Preview</p>
            </td>
            <td align="right" style="vertical-align:middle;">
              <p style="margin:0;font-size:11px;color:#C4A882;">{week_label}</p>
              <p style="margin:2px 0 0;font-size:10px;color:#8B6349;">Sunday 5:00 PM Auto-Report</p>
            </td>
          </tr></table>
        </td>
      </tr>
      <tr><td style="background:#C9A84C;height:3px;font-size:0;">&nbsp;</td></tr>
      <tr>
        <td style="padding:28px 36px;">
          <p style="margin:0 0 16px;font-size:14px;color:#2C1810;line-height:1.7;text-align:justify;">
            Your weekly campaign preview PDF is attached. It covers <strong>Facebook posts</strong>,
            <strong>Instagram posts</strong>, and the <strong>drip email sequence</strong> for the coming week — including
            caption previews and hashtag sets for each platform.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;">
            <tr>
              <td width="25%" style="background:#FAF7F2;border:1px solid #E8DDD0;border-radius:6px;padding:14px;text-align:center;">
                <p style="margin:0;font-size:22px;font-weight:700;color:#5C3D2E;">FB+IG</p>
                <p style="margin:4px 0 0;font-size:10px;color:#8B6349;text-transform:uppercase;">Daily Posts</p>
              </td>
              <td width="4%"></td>
              <td width="25%" style="background:#FAF7F2;border:1px solid #E8DDD0;border-radius:6px;padding:14px;text-align:center;">
                <p style="margin:0;font-size:22px;font-weight:700;color:#C9A84C;">7</p>
                <p style="margin:4px 0 0;font-size:10px;color:#8B6349;text-transform:uppercase;">Days Covered</p>
              </td>
              <td width="4%"></td>
              <td width="25%" style="background:#FAF7F2;border:1px solid #E8DDD0;border-radius:6px;padding:14px;text-align:center;">
                <p style="margin:0;font-size:22px;font-weight:700;color:#5C3D2E;">8AM</p>
                <p style="margin:4px 0 0;font-size:10px;color:#8B6349;text-transform:uppercase;">Auto-Runs PHT</p>
              </td>
              <td width="4%"></td>
              <td width="25%" style="background:#FAF7F2;border:1px solid #E8DDD0;border-radius:6px;padding:14px;text-align:center;">
                <p style="margin:0;font-size:22px;font-weight:700;color:#C9A84C;">AI</p>
                <p style="margin:4px 0 0;font-size:10px;color:#8B6349;text-transform:uppercase;">Generated</p>
              </td>
            </tr>
          </table>
          <p style="margin:16px 0 0;font-size:13px;color:#8B6349;line-height:1.6;text-align:justify;">
            Review the attached PDF. Reply <strong>approved</strong> or suggest changes — the AI will regenerate the PDF automatically.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0 4px;">
            <tr>
              <td width="48%" align="center">
                <a href="{approve_href}"
                   style="display:inline-block;width:100%;padding:13px 0;background:#2D6A4F;
                          color:#fff;font-size:13px;font-weight:700;text-decoration:none;
                          border-radius:6px;text-align:center;box-sizing:border-box;">
                  ✅ Approve Campaign
                </a>
              </td>
              <td width="4%"></td>
              <td width="48%" align="center">
                <a href="{changes_href}"
                   style="display:inline-block;width:100%;padding:13px 0;background:#5C3D2E;
                          color:#fff;font-size:13px;font-weight:700;text-decoration:none;
                          border-radius:6px;text-align:center;box-sizing:border-box;">
                  📝 Suggest Changes
                </a>
              </td>
            </tr>
          </table>
          <p style="margin:6px 0 0;font-size:11px;color:#8B6349;text-align:center;line-height:1.5;">
            Clicking a button opens your email client with the reply pre-filled.
          </p>
        </td>
      </tr>
      <tr>
        <td style="background:#FAF7F2;padding:14px 36px;border-top:1px solid #E8DDD0;text-align:center;">
          <p style="margin:0;font-size:11px;color:#8B6349;">
            Auto-generated by Enderun Marketing AI &bull;
            <a href="https://enderunextension.com" style="color:#C9A84C;text-decoration:none;">enderunextension.com</a>
          </p>
        </td>
      </tr>
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

    msg = MIMEMultipart("mixed")
    msg["From"]       = f"Enderun Marketing AI <{GMAIL_ADDRESS}>"
    msg["To"]         = ", ".join(RECIPIENTS)
    msg["Subject"]    = subject
    msg["Message-ID"] = msg_id
    msg.attach(MIMEText(body_html, "html"))

    pdf_part = MIMEBase("application", "pdf")
    pdf_part.set_payload(pdf_bytes)
    encoders.encode_base64(pdf_part)
    pdf_part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(pdf_part)

    try:
        print(f"  GMAIL_ADDRESS : {'SET (' + GMAIL_ADDRESS + ')' if GMAIL_ADDRESS else 'NOT SET'}")
        print(f"  GMAIL_APP_PASS: {'SET' if GMAIL_APP_PASS else 'NOT SET'}")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            for recipient in RECIPIENTS:
                server.sendmail(GMAIL_ADDRESS, recipient, msg.as_string())
                print(f"  Sent to: {recipient}")
        print(f"  Preview email sent to: {', '.join(RECIPIENTS)}")
    except Exception as e:
        print(f"  ERROR sending email: {e}")
        raise

    # Save state so check_preview_reply.py can track approval
    state = {
        "status":     "pending",
        "message_id": msg_id,
        "subject":    subject,
        "week_label": week_label,
        "week_start": week_dates[0][0].strftime("%Y-%m-%d"),
        "sent_at":    datetime.now(timezone.utc).isoformat(),
        "version":    1,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  Preview state saved → {STATE_FILE.name}")

    return msg_id

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Enderun Extension - Weekly Campaign Preview")
    print("=" * 60)

    print(f"  GMAIL_ADDRESS : {'SET' if GMAIL_ADDRESS else 'NOT SET'}")
    print(f"  GMAIL_APP_PASS: {'SET' if GMAIL_APP_PASS else 'NOT SET'}")
    print(f"  ANTHROPIC_KEY : {'SET' if ANTHROPIC_KEY else 'NOT SET (captions will be filename-based)'}")

    if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
        print("ERROR: GMAIL_ADDRESS or GMAIL_APP_PASS not set.")
        raise EnvironmentError("Missing GMAIL_ADDRESS or GMAIL_APP_PASS")

    week_dates = get_upcoming_week()
    schedule   = load_schedule()
    leads      = load_leads()

    week_label = f"{week_dates[0][0].strftime('%B %d')} – {week_dates[-1][0].strftime('%B %d, %Y')}"
    fb_count   = sum(1 for d, _ in week_dates if d.strftime("%Y-%m-%d") in schedule)
    print(f"\n  Week       : {week_label}")
    print(f"  Active leads: {len(leads)}")
    print(f"  FB+IG posts : {fb_count} / 7 days scheduled")

    print("\nBuilding PDF...")
    pdf_bytes = build_pdf(week_dates, schedule, leads)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / f"weekly_preview_{week_dates[0][0].strftime('%Y-%m-%d')}.pdf"
    out_file.write_bytes(pdf_bytes)
    print(f"  Saved: {out_file}")

    print("\nSending preview email...")
    send_preview_email(pdf_bytes, week_dates)

    push_notification(
        agent_id="campaign-preview",
        level="info",
        title=f"Campaign preview ready — {week_label}",
        message=f"FB+IG: {fb_count} posts · Drip: {len(leads)*7} emails across {len(leads)} leads. PDF sent.",
        report_path=str(out_file.relative_to(BASE_DIR)),
    )

    print("\n" + "=" * 60)
    print("  Done! Weekly preview sent.")
    print("=" * 60)


if __name__ == "__main__":
    main()
