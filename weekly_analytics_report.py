# -*- coding: utf-8 -*-
"""
Enderun Extension - Weekly Analytics Report
Runs every Monday at 8AM (via Task Scheduler).
Reads leads.csv, post history, and email activity,
then generates a branded HTML + PDF report and emails it to the marketing team.

Run: python weekly_analytics_report.py
Schedule: Mondays 8:00 AM via Task Scheduler (run_weekly_report.bat)

Logo: Place the Enderun Extension logo PNG at:
      assets/logos/enderun_extension_logo.png
"""

import os
import csv
import json
import smtplib
from io import BytesIO
from pathlib import Path
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import anthropic
from notifications_helper import push_notification

# ReportLab imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.platypus import Image as RLImage
from reportlab.lib.utils import ImageReader

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "eva@enderuncolleges.com")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

# Who receives the weekly report
REPORT_RECIPIENTS = [
    "eva@enderuncolleges.com",
    # Add more team emails here, e.g. "marketing@enderuncolleges.com"
]

BASE_DIR       = Path(__file__).parent
LEADS_FILE     = BASE_DIR / "leads.csv"
SCHEDULE_FILE  = BASE_DIR / "posting_schedule.json"
USED_LOG_FILE  = BASE_DIR / "used_images_log.json"
REPORT_DIR     = BASE_DIR / "output" / "reports"
LOGO_PATH      = BASE_DIR / "assets" / "logos" / "enderun_extension_logo.png"
ENDERUN_LINK   = "https://enderunextension.com/"

# Brand colors (ReportLab HexColor)
NAVY   = colors.HexColor("#1A2B4A")
GOLD   = colors.HexColor("#C9A84C")
CREAM  = colors.HexColor("#F8F6F0")
LGRAY  = colors.HexColor("#EEEEEE")
MGRAY  = colors.HexColor("#888888")
WHITE  = colors.white
BLACK  = colors.HexColor("#333333")

# ---------------------------------------------------------------------------
# DATA COLLECTION
# ---------------------------------------------------------------------------

def get_date_range():
    """Return Monday–Sunday of last week."""
    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def load_leads():
    """Load all leads from CSV."""
    leads = []
    if not LEADS_FILE.exists():
        return leads
    with open(LEADS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(row)
    return leads


def count_new_leads_this_week(leads, start_date, end_date):
    active = [l for l in leads if l.get("status", "").strip().lower() == "active"]
    return len(active), len(leads)


def get_program_breakdown(leads):
    """Count leads per program interest."""
    breakdown = {}
    for lead in leads:
        prog = lead.get("program_interest", "Unknown").strip()
        breakdown[prog] = breakdown.get(prog, 0) + 1
    return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))


def get_posts_this_week(start_date, end_date):
    """Get list of posts scheduled/published this past week."""
    posts = []
    if not SCHEDULE_FILE.exists():
        return posts
    with open(SCHEDULE_FILE, "r") as f:
        schedule = json.load(f).get("schedule", {})
    for d in range((end_date - start_date).days + 1):
        day = (start_date + timedelta(days=d)).isoformat()
        if day in schedule:
            posts.append({"date": day, "image": schedule[day]})
    return posts


def generate_ai_insights(leads, program_breakdown, posts, start_date, end_date) -> str:
    """Use Claude to generate executive insights from the data."""
    if not ANTHROPIC_KEY:
        return "- Claude AI insights not available (API key not set)."

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    data_summary = (
        f"Week: {start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}\n"
        f"Total leads in database: {len(leads)}\n"
        f"Active leads: {sum(1 for l in leads if l.get('status','').strip().lower()=='active')}\n"
        f"Program interest breakdown: {json.dumps(program_breakdown, indent=2)}\n"
        f"Facebook posts this week: {len(posts)}\n"
        f"Posts: {', '.join(p['image'] for p in posts) if posts else 'None'}\n"
    )

    prompt = (
        f"You are the Data Analysis Agent for Enderun Extension's marketing department.\n\n"
        f"Here is this week's marketing data:\n{data_summary}\n\n"
        f"Write 3-4 bullet-point insights for the marketing team. Be specific, actionable, "
        f"and focused on what to do next week. Reference the top-performing programs, "
        f"lead growth opportunities, and content strategy. Keep it concise (max 80 words total). "
        f"Format as plain bullet points starting with a dash (-)."
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# PDF REPORT BUILDER
# ---------------------------------------------------------------------------

def build_pdf(start_date, end_date, leads, program_breakdown, posts, insights) -> bytes:
    """Generate a branded PDF report and return as bytes."""
    buffer = BytesIO()
    week_label = f"{start_date.strftime('%B %d')} – {end_date.strftime('%B %d, %Y')}"
    total_leads  = len(leads)
    active_leads = sum(1 for l in leads if l.get("status", "").strip().lower() == "active")
    posts_count  = len(posts)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
        title=f"Weekly Marketing Report — {week_label}",
        author="Enderun Extension Marketing AI",
    )

    page_width = A4[0] - 3.6 * cm  # usable width

    # ── Styles ──────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    s_report_sub = ParagraphStyle(
        "ReportSub", fontSize=8, textColor=NAVY,
        leading=12, alignment=TA_CENTER, spaceAfter=0,
        fontName="Helvetica", letterSpacing=2,
    )
    s_report_title = ParagraphStyle(
        "ReportTitle", fontSize=18, textColor=NAVY,
        leading=24, alignment=TA_CENTER, spaceAfter=0,
        fontName="Helvetica-Bold",
    )
    s_report_week = ParagraphStyle(
        "ReportWeek", fontSize=11, textColor=colors.HexColor("#555577"),
        leading=16, alignment=TA_CENTER, spaceAfter=0,
        fontName="Helvetica",
    )
    s_section = ParagraphStyle(
        "Section", fontSize=11, textColor=NAVY,
        leading=16, spaceBefore=18, spaceAfter=8,
        fontName="Helvetica-Bold", textTransform="uppercase",
        borderPad=0,
    )
    s_body = ParagraphStyle(
        "Body", fontSize=10, textColor=BLACK,
        leading=15, fontName="Helvetica",
    )
    s_insight = ParagraphStyle(
        "Insight", fontSize=10, textColor=colors.HexColor("#444444"),
        leading=16, fontName="Helvetica", leftIndent=10,
        spaceAfter=4,
    )
    s_kpi_num = ParagraphStyle(
        "KpiNum", fontSize=28, textColor=NAVY,
        leading=34, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    s_kpi_num_gold = ParagraphStyle(
        "KpiNumGold", fontSize=28, textColor=GOLD,
        leading=34, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    s_kpi_label = ParagraphStyle(
        "KpiLabel", fontSize=8, textColor=MGRAY,
        leading=12, alignment=TA_CENTER, fontName="Helvetica",
        textTransform="uppercase",
    )
    s_footer = ParagraphStyle(
        "Footer", fontSize=8, textColor=MGRAY,
        leading=12, alignment=TA_CENTER, fontName="Helvetica",
    )
    s_th = ParagraphStyle(
        "TH", fontSize=9, textColor=MGRAY,
        leading=13, fontName="Helvetica-Bold",
        textTransform="uppercase",
    )
    s_td = ParagraphStyle(
        "TD", fontSize=10, textColor=BLACK,
        leading=14, fontName="Helvetica",
    )
    s_td_center = ParagraphStyle(
        "TDCenter", fontSize=10, textColor=NAVY,
        leading=14, fontName="Helvetica-Bold", alignment=TA_CENTER,
    )

    story = []

    # ── HEADER BLOCK ────────────────────────────────────────────────────────
    # Build header as a table (navy background)
    logo_cell = ""
    if LOGO_PATH.exists():
        try:
            logo_img = RLImage(str(LOGO_PATH), width=5.5*cm, height=1.6*cm, kind="proportional")
            logo_cell = logo_img
        except Exception:
            logo_cell = Paragraph("ENDERUN EXTENSION", s_report_sub)
    else:
        logo_cell = Paragraph("ENDERUN EXTENSION", s_report_sub)

    title_block = [
        Paragraph("Weekly Marketing Report", s_report_title),
        Spacer(1, 4),
        Paragraph(week_label, s_report_week),
    ]

    header_table = Table(
        [[logo_cell, title_block]],
        colWidths=[6 * cm, page_width - 6 * cm],
    )
    header_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), WHITE),   # full white header
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",        (0, 0), (0, 0),   "CENTER"),
        ("ALIGN",        (1, 0), (1, 0),   "CENTER"),
        ("LEFTPADDING",  (0, 0), (0, 0),   14),
        ("RIGHTPADDING", (0, 0), (0, 0),   14),
        ("TOPPADDING",   (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 14),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [8, 8, 0, 0]),
        ("BOX",          (0, 0), (-1, -1), 0.5, LGRAY),
    ]))
    story.append(header_table)

    # Gold accent line under header
    story.append(Table(
        [[""]],
        colWidths=[page_width],
        rowHeights=[4],
        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD)]),
    ))
    story.append(Spacer(1, 16))

    # ── REPORT METADATA ──────────────────────────────────────────────────────
    meta = (
        f"<font color='#{MGRAY.hexval()[2:]}'>"
        f"Generated: {date.today().strftime('%B %d, %Y')} &nbsp;|&nbsp; "
        f"Data source: leads.csv + posting_schedule.json &nbsp;|&nbsp; "
        f"Prepared by: Enderun Extension Marketing AI"
        f"</font>"
    )
    story.append(Paragraph(meta, s_footer))
    story.append(Spacer(1, 14))

    # ── KPI CARDS ───────────────────────────────────────────────────────────
    story.append(Paragraph("Key Metrics", s_section))

    kpi_data = [[
        [Paragraph(str(total_leads), s_kpi_num),
         Spacer(1, 2),
         Paragraph("Total Leads", s_kpi_label)],
        [Paragraph(str(active_leads), s_kpi_num_gold),
         Spacer(1, 2),
         Paragraph("Active Leads", s_kpi_label)],
        [Paragraph(str(posts_count), s_kpi_num),
         Spacer(1, 2),
         Paragraph("Posts This Week", s_kpi_label)],
    ]]
    col_w = page_width / 3 - 4
    kpi_table = Table(kpi_data, colWidths=[col_w, col_w, col_w], rowHeights=[80])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), CREAM),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("BOX",           (0, 0), (0, 0),   0.5, LGRAY),
        ("BOX",           (1, 0), (1, 0),   0.5, LGRAY),
        ("BOX",           (2, 0), (2, 0),   0.5, LGRAY),
        ("ROUNDEDCORNERS",(0, 0), (-1, -1), [6, 6, 6, 6]),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 6))

    # Active rate annotation
    active_rate = round(active_leads / total_leads * 100) if total_leads else 0
    story.append(Paragraph(
        f"<font color='#{MGRAY.hexval()[2:]}'>Active rate: {active_rate}% of total leads are currently active in the drip sequence.</font>",
        s_footer
    ))

    # ── AI INSIGHTS ─────────────────────────────────────────────────────────
    story.append(Paragraph("AI-Generated Insights", s_section))

    insight_lines = [
        line.strip().lstrip("- ").strip()
        for line in insights.split("\n")
        if line.strip().startswith("-")
    ]
    if not insight_lines:
        insight_lines = [insights] if insights else ["No insights available."]

    # Gold left-border box
    insight_rows = [[Paragraph(f"• {line}", s_insight)] for line in insight_lines]
    insight_table = Table(insight_rows, colWidths=[page_width - 2])
    insight_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#F5F0E4")),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBEFORE",    (0, 0), (0, -1),  4, GOLD),
    ]))
    story.append(insight_table)

    # ── PROGRAM BREAKDOWN TABLE ─────────────────────────────────────────────
    story.append(Paragraph("Leads by Program", s_section))

    prog_header = [
        Paragraph("Program", s_th),
        Paragraph("Leads", s_th),
        Paragraph("Share", s_th),
    ]
    prog_rows_data = [prog_header]
    for prog, count in program_breakdown.items():
        pct = round((count / total_leads * 100) if total_leads else 0)
        prog_rows_data.append([
            Paragraph(prog, s_td),
            Paragraph(str(count), s_td_center),
            Paragraph(f"{pct}%", s_td_center),
        ])
    if len(prog_rows_data) == 1:
        prog_rows_data.append([Paragraph("No leads yet", s_td), Paragraph("—", s_td_center), Paragraph("—", s_td_center)])

    col_widths_prog = [page_width * 0.60, page_width * 0.20, page_width * 0.20]
    prog_table = Table(prog_rows_data, colWidths=col_widths_prog, repeatRows=1)
    prog_style = [
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0),  CREAM),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  MGRAY),
        ("TOPPADDING",    (0, 0), (-1, 0),  8),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  8),
        # Data rows
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 10),
        ("TOPPADDING",    (0, 1), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        # Alternating rows
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, CREAM]),
        # Grid
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, LGRAY),
        ("BOX",           (0, 0), (-1, -1), 0.5, LGRAY),
        ("ALIGN",         (1, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]
    prog_table.setStyle(TableStyle(prog_style))
    story.append(prog_table)

    # ── FACEBOOK POSTS TABLE ────────────────────────────────────────────────
    story.append(Paragraph("Facebook Posts This Week", s_section))

    post_header = [Paragraph("Date", s_th), Paragraph("Image / Content", s_th)]
    post_rows_data = [post_header]
    for p in posts:
        post_rows_data.append([
            Paragraph(p["date"], s_td),
            Paragraph(p["image"], s_td),
        ])
    if len(post_rows_data) == 1:
        post_rows_data.append([Paragraph("No posts this week", s_td), Paragraph("—", s_td)])

    col_widths_posts = [page_width * 0.28, page_width * 0.72]
    post_table = Table(post_rows_data, colWidths=col_widths_posts, repeatRows=1)
    post_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  CREAM),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  MGRAY),
        ("TOPPADDING",    (0, 0), (-1, 0),  8),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  8),
        ("TOPPADDING",    (0, 1), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, CREAM]),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, LGRAY),
        ("BOX",           (0, 0), (-1, -1), 0.5, LGRAY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(post_table)
    story.append(Spacer(1, 24))

    # ── FOOTER ──────────────────────────────────────────────────────────────
    story.append(HRFlowable(width=page_width, thickness=0.5, color=LGRAY))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Auto-generated by Enderun Extension Marketing AI &nbsp;·&nbsp; "
        f"<a href='{ENDERUN_LINK}'><font color='#{GOLD.hexval()[2:]}'>enderunextension.com</font></a> &nbsp;·&nbsp; "
        f"Confidential — for internal use only",
        s_footer
    ))

    # ── BUILD PDF ───────────────────────────────────────────────────────────
    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# HTML REPORT BUILDER (unchanged, kept for email body)
# ---------------------------------------------------------------------------

def build_report_html(start_date, end_date, leads, program_breakdown, posts, insights) -> str:
    total_leads  = len(leads)
    active_leads = sum(1 for l in leads if l.get("status", "").strip().lower() == "active")
    posts_count  = len(posts)

    # Program breakdown rows
    prog_rows = ""
    for prog, count in program_breakdown.items():
        pct = round((count / total_leads * 100) if total_leads else 0)
        prog_rows += f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #EEEEEE;color:#333;">{prog}</td>
          <td style="padding:10px 16px;border-bottom:1px solid #EEEEEE;text-align:center;font-weight:700;color:#1A2B4A;">{count}</td>
          <td style="padding:10px 16px;border-bottom:1px solid #EEEEEE;text-align:center;color:#888;">{pct}%</td>
        </tr>"""

    # Posts this week rows
    post_rows = ""
    for p in posts:
        post_rows += f"""
        <tr>
          <td style="padding:8px 16px;border-bottom:1px solid #EEEEEE;color:#888;">{p['date']}</td>
          <td style="padding:8px 16px;border-bottom:1px solid #EEEEEE;color:#333;">{p['image']}</td>
        </tr>"""
    if not post_rows:
        post_rows = '<tr><td colspan="2" style="padding:12px 16px;color:#aaa;text-align:center;">No posts scheduled this week</td></tr>'

    # AI insights as HTML list
    insight_lines = [line.strip("- ").strip() for line in insights.split("\n") if line.strip().startswith("-")]
    insights_html = "".join(f"<li style='margin-bottom:10px;'>{line}</li>" for line in insight_lines) or f"<li>{insights}</li>"

    week_label = f"{start_date.strftime('%B %d')} &ndash; {end_date.strftime('%B %d, %Y')}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Marketing Report — {week_label}</title>
</head>
<body style="margin:0;padding:0;background-color:#F4F4F4;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#F4F4F4;padding:30px 0;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background-color:#1A2B4A;padding:28px 40px;text-align:center;">
              <p style="margin:0;font-size:11px;letter-spacing:3px;color:#C9A84C;text-transform:uppercase;font-weight:600;">Enderun Extension</p>
              <p style="margin:6px 0 0;font-size:20px;color:#ffffff;font-weight:700;">Weekly Marketing Report</p>
              <p style="margin:6px 0 0;font-size:14px;color:#aaaacc;">{week_label}</p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#C9A84C;height:4px;font-size:0;line-height:0;">&nbsp;</td>
          </tr>

          <!-- PDF notice -->
          <tr>
            <td style="padding:12px 40px 0;text-align:center;">
              <p style="margin:0;font-size:12px;color:#aaa;">📎 Full branded PDF report attached to this email.</p>
            </td>
          </tr>

          <!-- KPI Cards -->
          <tr>
            <td style="padding:24px 40px 16px;">
              <h2 style="margin:0 0 20px;font-size:16px;font-weight:700;color:#1A2B4A;text-transform:uppercase;letter-spacing:1px;">Key Metrics</h2>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="33%" style="text-align:center;padding:20px 10px;background:#F8F6F0;border-radius:8px;margin:0 8px;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#1A2B4A;">{total_leads}</p>
                    <p style="margin:4px 0 0;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Total Leads</p>
                  </td>
                  <td width="4%"></td>
                  <td width="33%" style="text-align:center;padding:20px 10px;background:#F8F6F0;border-radius:8px;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#C9A84C;">{active_leads}</p>
                    <p style="margin:4px 0 0;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Active Leads</p>
                  </td>
                  <td width="4%"></td>
                  <td width="33%" style="text-align:center;padding:20px 10px;background:#F8F6F0;border-radius:8px;">
                    <p style="margin:0;font-size:36px;font-weight:700;color:#1A2B4A;">{posts_count}</p>
                    <p style="margin:4px 0 0;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Posts This Week</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- AI Insights -->
          <tr>
            <td style="padding:16px 40px;">
              <h2 style="margin:0 0 16px;font-size:16px;font-weight:700;color:#1A2B4A;text-transform:uppercase;letter-spacing:1px;">AI Insights</h2>
              <div style="background:#F0EDE4;border-left:4px solid #C9A84C;padding:20px 24px;border-radius:0 8px 8px 0;">
                <ul style="margin:0;padding-left:20px;font-size:15px;line-height:1.8;color:#444;">
                  {insights_html}
                </ul>
              </div>
            </td>
          </tr>

          <!-- Program Breakdown -->
          <tr>
            <td style="padding:16px 40px;">
              <h2 style="margin:0 0 16px;font-size:16px;font-weight:700;color:#1A2B4A;text-transform:uppercase;letter-spacing:1px;">Leads by Program</h2>
              <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #EEEEEE;border-radius:8px;overflow:hidden;">
                <tr style="background:#F8F6F0;">
                  <th style="padding:10px 16px;text-align:left;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Program</th>
                  <th style="padding:10px 16px;text-align:center;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Leads</th>
                  <th style="padding:10px 16px;text-align:center;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Share</th>
                </tr>
                {prog_rows if prog_rows else '<tr><td colspan="3" style="padding:12px 16px;color:#aaa;text-align:center;">No leads yet</td></tr>'}
              </table>
            </td>
          </tr>

          <!-- Facebook Posts -->
          <tr>
            <td style="padding:16px 40px 32px;">
              <h2 style="margin:0 0 16px;font-size:16px;font-weight:700;color:#1A2B4A;text-transform:uppercase;letter-spacing:1px;">Facebook Posts This Week</h2>
              <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #EEEEEE;border-radius:8px;overflow:hidden;">
                <tr style="background:#F8F6F0;">
                  <th style="padding:10px 16px;text-align:left;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Date</th>
                  <th style="padding:10px 16px;text-align:left;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;">Image / Content</th>
                </tr>
                {post_rows}
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#F8F6F0;padding:20px 40px;text-align:center;border-top:1px solid #EEEEEE;">
              <p style="margin:0;font-size:12px;color:#aaa;">
                Auto-generated by Enderun Extension Marketing AI &bull;
                <a href="{ENDERUN_LINK}" style="color:#C9A84C;text-decoration:none;">enderunextension.com</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""


# ---------------------------------------------------------------------------
# SAVE & EMAIL
# ---------------------------------------------------------------------------

def save_report(html: str, pdf_bytes: bytes, start_date: date) -> tuple:
    """Save HTML and PDF reports to output/reports/. Returns (html_path, pdf_path)."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    base_name = f"{start_date.isoformat()}_weekly_marketing_report"

    html_path = REPORT_DIR / f"{base_name}.html"
    html_path.write_text(html, encoding="utf-8")

    pdf_path = REPORT_DIR / f"{base_name}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    return html_path, pdf_path


def send_report_email(html: str, pdf_bytes: bytes, start_date: date, end_date: date):
    """Email the weekly report with HTML body and PDF attachment."""
    week_label  = f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
    subject     = f"Weekly Marketing Report | Enderun Extension | {week_label}"
    pdf_filename = f"{start_date.isoformat()}_weekly_marketing_report.pdf"

    for recipient in REPORT_RECIPIENTS:
        msg = MIMEMultipart("mixed")
        msg["From"]    = f"Enderun Extension Marketing <{GMAIL_ADDRESS}>"
        msg["To"]      = recipient
        msg["Subject"] = subject

        # HTML body
        msg.attach(MIMEText(html, "html"))

        # PDF attachment
        pdf_part = MIMEBase("application", "pdf")
        pdf_part.set_payload(pdf_bytes)
        encoders.encode_base64(pdf_part)
        pdf_part.add_header(
            "Content-Disposition",
            f'attachment; filename="{pdf_filename}"',
        )
        msg.attach(pdf_part)

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
                server.sendmail(GMAIL_ADDRESS, recipient, msg.as_string())
            print(f"  Report + PDF sent to {recipient}")
        except Exception as e:
            print(f"  Failed to send to {recipient}: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Enderun Extension - Weekly Analytics Report")
    print("=" * 60)

    start_date, end_date = get_date_range()
    print(f"Reporting period: {start_date} to {end_date}")

    # Check logo
    if LOGO_PATH.exists():
        print(f"  Logo found: {LOGO_PATH.name}")
    else:
        print(f"  Logo not found — place logo at: assets/logos/enderun_extension_logo.png")
        print(f"  (Report will generate without logo)")

    # Collect data
    leads             = load_leads()
    program_breakdown = get_program_breakdown(leads)
    posts             = get_posts_this_week(start_date, end_date)

    print(f"Total leads: {len(leads)}")
    print(f"Posts this week: {len(posts)}")
    print("Generating AI insights...")

    insights = generate_ai_insights(leads, program_breakdown, posts, start_date, end_date)
    print(f"Insights ready.")

    # Build HTML
    print("Building HTML report...")
    html = build_report_html(start_date, end_date, leads, program_breakdown, posts, insights)

    # Build PDF
    print("Building PDF report...")
    try:
        pdf_bytes = build_pdf(start_date, end_date, leads, program_breakdown, posts, insights)
        print(f"  PDF generated ({len(pdf_bytes):,} bytes)")
    except Exception as e:
        print(f"  PDF generation failed: {e}")
        pdf_bytes = b""

    # Save both
    html_path, pdf_path = save_report(html, pdf_bytes, start_date)
    print(f"HTML saved: {html_path.name}")
    if pdf_bytes:
        print(f"PDF saved:  {pdf_path.name}")

    # Send email with attachment
    if GMAIL_ADDRESS and GMAIL_APP_PASS:
        print("Sending email...")
        send_report_email(html, pdf_bytes, start_date, end_date)
    else:
        print("Gmail not configured — report saved locally only.")

    push_notification(
        agent_id="weekly-analytics",
        level="info",
        title=f"Weekly analytics report ready",
        message=f"{len(leads)} total leads · {len(posts)} posts this week · {start_date} to {end_date}. PDF attached to email.",
        report_path=str(pdf_path.relative_to(Path(__file__).parent)) if pdf_bytes else None,
    )
    print("=" * 60)
    print("  Weekly report done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
