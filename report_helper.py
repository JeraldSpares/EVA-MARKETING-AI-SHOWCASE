# -*- coding: utf-8 -*-
"""
Enderun Marketing Department — Reusable PDF Report Builder
===========================================================
Any agent can use this to generate a branded PDF report saved to
output/<agent_id>/YYYY-MM-DD_<report_slug>.pdf

Usage:
    from report_helper import ReportBuilder

    rb = ReportBuilder(
        agent_id="data-analysis",
        report_title="Lead Funnel Analysis",
        subtitle="Q2 2026 Deep Dive",
    )
    rb.add_section("Executive Summary")
    rb.add_paragraph("This report covers the full lead funnel for Q2 2026...")
    rb.add_kpi_row([("Total Leads", "142", False), ("Active", "89", True), ("Rate", "63%", False)])
    rb.add_table(
        headers=["Program", "Leads", "Status"],
        rows=[["BS Hospitality", "54", "Active"], ["BS Culinary", "30", "Active"]],
    )
    rb.add_bullets(["Insight one", "Insight two", "Insight three"])
    path = rb.save()
    print(f"Report saved to: {path}")
"""

import re
from io import BytesIO
import os
from pathlib import Path
from datetime import date

import matplotlib
matplotlib.use("Agg")   # non-interactive backend — safe for scripts and cloud
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak,
)
from reportlab.platypus import Image as RLImage

# ---------------------------------------------------------------------------
# BRAND CONSTANTS — Light Brown Professional Theme
# ---------------------------------------------------------------------------

NAVY        = colors.HexColor("#5C3D2E")   # Re-mapped: dark brown (replaces old navy)
BROWN_DARK  = colors.HexColor("#5C3D2E")
BROWN_MED   = colors.HexColor("#8B6349")
BROWN_LIGHT = colors.HexColor("#C4A882")
GOLD        = colors.HexColor("#C9A84C")
CREAM       = colors.HexColor("#FAF7F2")   # Warm cream background
CREAM_ROW   = colors.HexColor("#F5EDE0")   # Alternate row cream
BEIGE       = colors.HexColor("#E8DDD0")   # Borders / dividers
LGRAY       = colors.HexColor("#E8DDD0")   # Re-mapped to beige
MGRAY       = colors.HexColor("#8B6349")   # Re-mapped to medium brown
DGRAY       = colors.HexColor("#5C3D2E")   # Re-mapped to dark brown
WHITE       = colors.white
BLACK       = colors.HexColor("#2C1810")   # Very dark brown for body text
CORAL       = colors.HexColor("#E8603C")
GREEN       = colors.HexColor("#2D6A4F")

# Hex strings for matplotlib (same palette as above)
MPL_BROWN_DARK  = "#5C3D2E"
MPL_BROWN_MED   = "#8B6349"
MPL_BROWN_LIGHT = "#C4A882"
MPL_GOLD        = "#C9A84C"
MPL_CREAM       = "#FAF7F2"
MPL_CREAM_ROW   = "#F5EDE0"
MPL_CORAL       = "#E8603C"
MPL_GREEN       = "#2D6A4F"
MPL_BLACK       = "#2C1810"

# Multi-color cycle for charts with multiple series / slices
MPL_PALETTE = [
    MPL_BROWN_DARK, MPL_GOLD, MPL_BROWN_MED,
    MPL_CORAL,      MPL_GREEN, MPL_BROWN_LIGHT,
]

BASE_DIR  = Path(__file__).parent
LOGO_PATH = BASE_DIR / "assets" / "logos" / "enderun_extension_logo.png"
OUTPUT_DIR = BASE_DIR / "output"

# ---------------------------------------------------------------------------
# AGENT → FOLDER MAPPING
# Agent ID maps to a human-readable output subfolder name
# ---------------------------------------------------------------------------

AGENT_FOLDERS = {
    "marketing-manager":    "marketing-manager",
    "social-media":         "social-media",
    "admissions":           "admissions",
    "competitor-analysis":  "competitor-analysis",
    "drip-campaign":        "drip-campaign",
    "content-strategy":     "content-strategy",
    "pr":                   "pr",
    "designer":             "designer",
    "data-analysis":        "data-analysis",
    "seo-digital":          "seo-digital",
    "marketing-analysis":   "marketing-analysis",
    "business-analyst":     "business-analyst",
    "video-multimedia":     "video-multimedia",
    "events-banquetes":     "events-banquetes",
    "influencer-kol":       "influencer-kol",
    "researcher":           "researcher",
    "alumni-relations":     "alumni-relations",
    "events-activations":   "events-activations",
    "chief-strategist":     "chief-strategist",
    # Automation scripts
    "social-listening":     "reports/social_listening",
    "weekly-analytics":     "reports/analytics",
    "campaign-preview":     "reports/weekly_preview",
    "drip-email":           "reports/drip-email",
    "facebook-post":        "reports/facebook",
    "instagram-post":       "reports/instagram",
}

# ---------------------------------------------------------------------------
# REPORT BUILDER CLASS
# ---------------------------------------------------------------------------

class ReportBuilder:
    """
    Fluent builder for branded Enderun PDF reports.

    Parameters
    ----------
    agent_id : str
        The agent generating this report (e.g. "data-analysis").
        Determines the output subfolder.
    report_title : str
        Main title shown in the header (e.g. "Lead Funnel Analysis").
    subtitle : str, optional
        Subtitle shown below the title (e.g. "April 2026").
    filename : str, optional
        Custom filename (without .pdf). Defaults to YYYY-MM-DD_<slugified-title>.
    """

    def __init__(
        self,
        agent_id: str,
        report_title: str,
        subtitle: str = "",
        filename: str = "",
    ):
        self.agent_id     = agent_id
        self.report_title = report_title
        self.subtitle     = subtitle or date.today().strftime("%B %d, %Y")
        self.today        = date.today()

        # Resolve output folder
        folder_name = AGENT_FOLDERS.get(agent_id, agent_id)
        self.output_dir = OUTPUT_DIR / folder_name
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve filename
        if filename:
            self.filename = filename if filename.endswith(".pdf") else filename + ".pdf"
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", report_title.lower()).strip("-")
            self.filename = f"{self.today.isoformat()}_{slug}.pdf"

        self.filepath = self.output_dir / self.filename
        self._story   = []
        self._styles  = self._build_styles()
        self._sources = []   # collects data source citations → auto-appended before save

    # ------------------------------------------------------------------
    # STYLES
    # ------------------------------------------------------------------

    def _build_styles(self) -> dict:
        return {
            "label": ParagraphStyle(
                "Label", fontSize=8, textColor=GOLD,
                leading=12, fontName="Helvetica-Bold",
                letterSpacing=2, spaceAfter=2,
            ),
            "title": ParagraphStyle(
                "Title", fontSize=18, textColor=BROWN_DARK,
                leading=24, fontName="Helvetica-Bold", spaceAfter=2,
            ),
            "subtitle": ParagraphStyle(
                "Subtitle", fontSize=11, textColor=BROWN_MED,
                leading=16, fontName="Helvetica",
            ),
            "section": ParagraphStyle(
                "Section", fontSize=11, textColor=BROWN_DARK,
                leading=16, spaceBefore=18, spaceAfter=8,
                fontName="Helvetica-Bold",
            ),
            "body": ParagraphStyle(
                "Body", fontSize=10, textColor=BLACK,
                leading=16, fontName="Helvetica",
                alignment=TA_JUSTIFY, spaceAfter=6,
            ),
            "body_left": ParagraphStyle(
                "BodyLeft", fontSize=10, textColor=BLACK,
                leading=16, fontName="Helvetica",
                alignment=TA_LEFT, spaceAfter=6,
            ),
            "bullet": ParagraphStyle(
                "Bullet", fontSize=10, textColor=BLACK,
                leading=16, fontName="Helvetica",
                leftIndent=12, spaceAfter=4,
                alignment=TA_JUSTIFY,
            ),
            "caption": ParagraphStyle(
                "Caption", fontSize=8, textColor=BROWN_MED,
                leading=12, fontName="Helvetica",
                alignment=TA_CENTER,
            ),
            "footer": ParagraphStyle(
                "Footer", fontSize=8, textColor=BROWN_MED,
                leading=12, fontName="Helvetica",
                alignment=TA_CENTER,
            ),
            "kpi_num": ParagraphStyle(
                "KpiNum", fontSize=26, textColor=BROWN_DARK,
                leading=32, alignment=TA_CENTER, fontName="Helvetica-Bold",
            ),
            "kpi_num_gold": ParagraphStyle(
                "KpiNumGold", fontSize=26, textColor=GOLD,
                leading=32, alignment=TA_CENTER, fontName="Helvetica-Bold",
            ),
            "kpi_label": ParagraphStyle(
                "KpiLabel", fontSize=8, textColor=BROWN_MED,
                leading=12, alignment=TA_CENTER, fontName="Helvetica",
            ),
            "th": ParagraphStyle(
                "TH", fontSize=9, textColor=WHITE,
                leading=13, fontName="Helvetica-Bold",
                alignment=TA_LEFT,
            ),
            "th_center": ParagraphStyle(
                "THCenter", fontSize=9, textColor=WHITE,
                leading=13, fontName="Helvetica-Bold",
                alignment=TA_CENTER,
            ),
            "td": ParagraphStyle(
                "TD", fontSize=10, textColor=BLACK,
                leading=14, fontName="Helvetica",
            ),
            "td_center": ParagraphStyle(
                "TDCenter", fontSize=10, textColor=BROWN_DARK,
                leading=14, fontName="Helvetica-Bold",
                alignment=TA_CENTER,
            ),
            "verdict": ParagraphStyle(
                "Verdict", fontSize=11, textColor=BROWN_DARK,
                leading=16, fontName="Helvetica-Bold",
                spaceAfter=4,
            ),
        }

    # ------------------------------------------------------------------
    # CONTENT METHODS
    # ------------------------------------------------------------------

    def add_spacer(self, height_mm: float = 6):
        """Add vertical whitespace."""
        self._story.append(Spacer(1, height_mm * 0.354330708))  # mm to pt approx
        return self

    def add_section(self, title: str):
        """Add a section heading — dark brown bar, white text, gold left accent."""
        pw = self._page_width()
        s = ParagraphStyle(
            "SectionBar", fontSize=10, textColor=WHITE,
            fontName="Helvetica-Bold", leading=14, spaceAfter=0,
        )
        t = Table([[Paragraph(title.upper(), s)]], colWidths=[pw])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), BROWN_DARK),
            ("LEFTPADDING",   (0, 0), (-1, -1), 16),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LINEBEFORE",    (0, 0), (0, -1),  5, GOLD),
        ]))
        self._story.append(Spacer(1, 12))
        self._story.append(t)
        self._story.append(Spacer(1, 9))
        return self

    def add_paragraph(self, text: str, justify: bool = True):
        """Add a body paragraph. Supports **bold** markdown inline."""
        style = self._styles["body"] if justify else self._styles["body_left"]
        self._story.append(Paragraph(self._md(text), style))
        return self

    def add_bullets(self, items: list, intro: str = ""):
        """Add a bulleted list — gold diamond markers, alternating row shading."""
        if intro:
            self._story.append(Paragraph(self._md(intro), self._styles["body"]))
        dot_s = ParagraphStyle(
            "BulletDot", fontSize=9, textColor=GOLD,
            fontName="Helvetica-Bold", leading=15, alignment=TA_CENTER,
        )
        txt_s = ParagraphStyle(
            "BulletTxt", fontSize=10, textColor=BLACK,
            fontName="Helvetica", leading=15, alignment=TA_LEFT,
        )
        pw = self._page_width()
        dot_w, txt_w = 18, pw - 18
        rows = [
            [Paragraph("◆", dot_s), Paragraph(self._md(item), txt_s)]
            for item in items
        ]
        t = Table(rows, colWidths=[dot_w, txt_w])
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [CREAM_ROW, WHITE]),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",          (0, 0), (0, -1),  "CENTER"),
            ("LEFTPADDING",    (0, 0), (0, -1),  4),
            ("LEFTPADDING",    (1, 0), (1, -1),  10),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
            ("TOPPADDING",     (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
            ("LINEBEFORE",     (0, 0), (0, -1),  3, GOLD),
            ("LINEBELOW",      (0, 0), (-1, -1), 0.3, BEIGE),
        ]))
        self._story.append(t)
        self._story.append(Spacer(1, 7))
        return self

    def add_kpi_row(self, kpis: list):
        """
        Add a row of KPI cards with colored top accent, white background.
        kpis: list of (label, value, gold=False) tuples
        """
        pw   = self._page_width()
        n    = len(kpis)
        gap  = 5
        col_w = (pw - gap * (n - 1)) / n

        num_s = ParagraphStyle(
            "KpiN", fontSize=30, textColor=BROWN_DARK,
            leading=36, alignment=TA_CENTER, fontName="Helvetica-Bold",
        )
        num_g = ParagraphStyle(
            "KpiNG", fontSize=30, textColor=GOLD,
            leading=36, alignment=TA_CENTER, fontName="Helvetica-Bold",
        )
        lbl_s = ParagraphStyle(
            "KpiL2", fontSize=7.5, textColor=BROWN_MED,
            leading=11, alignment=TA_CENTER, fontName="Helvetica-Bold",
            letterSpacing=1.2,
        )

        cells = []
        for label, value, gold in kpis:
            ns = num_g if gold else num_s
            cells.append([
                Spacer(1, 2),
                Paragraph(str(value), ns),
                Spacer(1, 4),
                Paragraph(label.upper(), lbl_s),
                Spacer(1, 2),
            ])

        t = Table([cells], colWidths=[col_w] * n)
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ]
        for i, (_, _, gold) in enumerate(kpis):
            accent = GOLD if gold else BROWN_MED
            style_cmds.append(("LINEABOVE", (i, 0), (i, 0), 4, accent))
            style_cmds.append(("BOX",       (i, 0), (i, 0), 0.5, BEIGE))
        t.setStyle(TableStyle(style_cmds))
        self._story.append(t)
        self._story.append(Spacer(1, 8))
        return self

    def add_table(
        self,
        headers: list,
        rows: list,
        col_widths: list = None,
        center_cols: list = None,
    ):
        """
        Add a data table with navy header row.

        headers    : list of column header strings
        rows       : list of lists (each inner list = one row)
        col_widths : optional list of column widths in cm
        center_cols: list of column indices to center-align (0-based)
        """
        center_cols = center_cols or []
        pw = self._page_width()

        if col_widths:
            widths = [w * cm for w in col_widths]
        else:
            widths = [pw / len(headers)] * len(headers)

        # Header row
        header_cells = []
        for i, h in enumerate(headers):
            s = self._styles["th_center"] if i in center_cols else self._styles["th"]
            header_cells.append(Paragraph(h.upper(), s))

        # Data rows
        table_data = [header_cells]
        for row in rows:
            cells = []
            for i, cell in enumerate(row):
                s = self._styles["td_center"] if i in center_cols else self._styles["td"]
                cells.append(Paragraph(self._md(str(cell)), s))
            table_data.append(cells)

        t = Table(table_data, colWidths=widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0),  BROWN_DARK),
            ("BACKGROUND",    (0, 1), (-1, -1), WHITE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, CREAM_ROW]),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LINEBELOW",     (0, 0), (-1, -1), 0.4, BEIGE),
            ("BOX",           (0, 0), (-1, -1), 0.5, BEIGE),
            ("LINEBEFORE",    (0, 0), (0, 0),   4, GOLD),   # gold left accent on header
            ("LINEBEFORE",    (0, 1), (0, -1),  2, BEIGE),  # subtle left line on data rows
        ]
        for i in center_cols:
            style_cmds.append(("ALIGN", (i, 0), (i, -1), "CENTER"))
        t.setStyle(TableStyle(style_cmds))
        self._story.append(t)
        self._story.append(Spacer(1, 8))
        return self

    def add_alert_box(self, text: str, level: str = "warning"):
        """
        Add a colored alert box — solid icon column + light text column.
        level: 'warning' | 'critical' | 'success' | 'info'
        """
        color_map = {
            "warning":  (GOLD,       colors.HexColor("#FFFBEF"), "!"),
            "critical": (CORAL,      colors.HexColor("#FEF2F0"), "!!"),
            "success":  (GREEN,      colors.HexColor("#EEF7F2"), "OK"),
            "info":     (BROWN_MED,  CREAM_ROW,                  "i"),
        }
        icon_bg, text_bg, icon_char = color_map.get(level, color_map["info"])
        icon_s = ParagraphStyle(
            "AlertIcon", fontSize=9, textColor=WHITE,
            fontName="Helvetica-Bold", alignment=TA_CENTER, leading=13,
        )
        text_s = ParagraphStyle(
            "AlertText", fontSize=10, textColor=BLACK,
            leading=16, fontName="Helvetica", alignment=TA_JUSTIFY,
        )
        pw     = self._page_width()
        icon_w = 26
        text_w = pw - icon_w - 2
        t = Table(
            [[Paragraph(icon_char, icon_s), Paragraph(self._md(text), text_s)]],
            colWidths=[icon_w, text_w],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0),   icon_bg),
            ("BACKGROUND",    (1, 0), (1, 0),   text_bg),
            ("ALIGN",         (0, 0), (0, 0),   "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (0, 0),   4),
            ("RIGHTPADDING",  (0, 0), (0, 0),   4),
            ("LEFTPADDING",   (1, 0), (1, 0),   14),
            ("RIGHTPADDING",  (1, 0), (1, 0),   12),
            ("TOPPADDING",    (0, 0), (-1, -1), 11),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
            ("BOX",           (0, 0), (-1, -1), 0.5, icon_bg),
        ]))
        self._story.append(t)
        self._story.append(Spacer(1, 8))
        return self

    def add_two_col(self, left_content: list, right_content: list):
        """
        Add a two-column layout — cream left card, white right card, gold left accent.
        left_content / right_content: list of (type, value) tuples
        type: 'paragraph', 'section', 'bullets'
        """
        pw    = self._page_width()
        col_w = (pw - 6) / 2

        inner_sec_s = ParagraphStyle(
            "TwoColSec", fontSize=8, textColor=GOLD,
            fontName="Helvetica-Bold", leading=12,
            letterSpacing=1.5, spaceBefore=4, spaceAfter=4,
        )
        bullet_s = ParagraphStyle(
            "TwoColBullet", fontSize=9.5, textColor=BLACK,
            fontName="Helvetica", leading=14, alignment=TA_LEFT,
        )

        def render_col(content):
            items = []
            for ctype, cval in content:
                if ctype == "section":
                    items.append(Paragraph(cval.upper(), inner_sec_s))
                elif ctype == "paragraph":
                    items.append(Paragraph(self._md(cval), self._styles["body"]))
                elif ctype == "bullets":
                    for b in cval:
                        items.append(Paragraph(f"◆  {self._md(b)}", bullet_s))
                        items.append(Spacer(1, 3))
            return items

        left  = render_col(left_content)
        right = render_col(right_content)
        max_len = max(len(left), len(right))
        while len(left)  < max_len: left.append(Spacer(1, 1))
        while len(right) < max_len: right.append(Spacer(1, 1))

        rows = [[l, r] for l, r in zip(left, right)]
        t = Table(rows, colWidths=[col_w, col_w])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), CREAM_ROW),
            ("BACKGROUND",    (1, 0), (1, -1), WHITE),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (0, -1),  14),
            ("RIGHTPADDING",  (0, 0), (0, -1),  12),
            ("LEFTPADDING",   (1, 0), (1, -1),  14),
            ("RIGHTPADDING",  (1, 0), (1, -1),  12),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LINEBEFORE",    (0, 0), (0, -1),  3, GOLD),
            ("BOX",           (0, 0), (0, -1),  0.5, BEIGE),
            ("LINEBEFORE",    (1, 0), (1, -1),  0.5, BEIGE),
            ("BOX",           (1, 0), (1, -1),  0.5, BEIGE),
        ]))
        self._story.append(t)
        self._story.append(Spacer(1, 8))
        return self

    def add_page_break(self):
        """Force a new page."""
        self._story.append(PageBreak())
        return self

    def add_caption(self, text: str):
        """Add a small centered caption (e.g. below a table)."""
        self._story.append(Paragraph(text, self._styles["caption"]))
        self._story.append(Spacer(1, 4))
        return self

    def add_source(self, text: str):
        """
        Register a data source citation.
        All sources are collected and printed as a 'Data Sources' section
        automatically at the end of the report before save().

        Example:
            rb.add_source("leads.csv — verified internal data, April 2026")
            rb.add_source("Facebook page public observation — estimated, April 2026")
        """
        self._sources.append(text)
        return self

    def add_callout(self, stat: str, label: str, description: str = ""):
        """
        Full-width centered highlight box — large gold stat, brown label, optional note.
        Use for a single powerful number or fact you want the reader to stop at.

        Example:
            rb.add_callout("Only School", "in the Philippines with both Les Roches AND Ecole Ducasse",
                           "No competitor has even one of these affiliations.")
        """
        pw    = self._page_width()
        stat_s = ParagraphStyle(
            "CallStat", fontSize=34, textColor=GOLD,
            fontName="Helvetica-Bold", leading=40, alignment=TA_CENTER,
        )
        lbl_s = ParagraphStyle(
            "CallLbl", fontSize=12, textColor=BROWN_DARK,
            fontName="Helvetica-Bold", leading=17, alignment=TA_CENTER,
        )
        desc_s = ParagraphStyle(
            "CallDesc", fontSize=9, textColor=BROWN_MED,
            fontName="Helvetica", leading=13, alignment=TA_CENTER,
        )
        inner = [Paragraph(str(stat), stat_s), Spacer(1, 5), Paragraph(self._md(label), lbl_s)]
        if description:
            inner += [Spacer(1, 5), Paragraph(description, desc_s)]
        t = Table([[inner]], colWidths=[pw])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), CREAM_ROW),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 22),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 22),
            ("LINEABOVE",     (0, 0), (-1,  0),  3, GOLD),
            ("LINEBELOW",     (0, -1),(-1, -1),  3, GOLD),
            ("BOX",           (0, 0), (-1, -1),  0.5, BEIGE),
        ]))
        self._story.append(t)
        self._story.append(Spacer(1, 8))
        return self

    # ------------------------------------------------------------------
    # CHARTS — private builders
    # ------------------------------------------------------------------

    def _chart_to_image(self, fig, target_width_pt: float) -> RLImage:
        """Save a matplotlib figure to a ReportLab Image at an exact pt width."""
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return RLImage(buf, width=target_width_pt)   # height auto-scales

    def _style_ax(self, ax, has_hgrid: bool = True):
        """Apply Enderun brand theme to a matplotlib Axes."""
        ax.set_facecolor(MPL_CREAM_ROW)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(MPL_BROWN_LIGHT)
        ax.spines["bottom"].set_color(MPL_BROWN_LIGHT)
        ax.tick_params(colors=MPL_BROWN_MED, labelsize=7.5, length=3)
        if has_hgrid:
            ax.yaxis.grid(True, color=MPL_BROWN_LIGHT, linewidth=0.4,
                          linestyle="--", alpha=0.8)
        ax.set_axisbelow(True)

    def _make_bar_fig(self, title, labels, values, color, horizontal, fig_w_in):
        """Build and return a bar chart figure."""
        fig_h = fig_w_in * (0.55 if horizontal else 0.44)
        fig, ax = plt.subplots(figsize=(fig_w_in, fig_h))
        fig.patch.set_facecolor(MPL_CREAM)
        self._style_ax(ax, has_hgrid=not horizontal)

        color_map = {
            "brown": [MPL_BROWN_DARK] * len(labels),
            "gold":  [MPL_GOLD]       * len(labels),
            "multi": [MPL_PALETTE[i % len(MPL_PALETTE)] for i in range(len(labels))],
        }
        bar_colors = color_map.get(color, color_map["brown"])
        x = np.arange(len(labels))
        max_val = max(values) if values else 1

        if horizontal:
            bars = ax.barh(x, values, color=bar_colors, edgecolor="white",
                           linewidth=0.6, height=0.55)
            ax.set_yticks(x)
            ax.set_yticklabels(labels, fontsize=7.5, color=MPL_BROWN_MED)
            ax.xaxis.grid(True, color=MPL_BROWN_LIGHT, linewidth=0.4, linestyle="--", alpha=0.7)
            ax.yaxis.grid(False)
            ax.spines["left"].set_visible(False)
            ax.tick_params(axis="y", length=0)
            ax.set_xlim(0, max_val * 1.18)
            for bar in bars:
                w = bar.get_width()
                ax.text(w + max_val * 0.015, bar.get_y() + bar.get_height() / 2,
                        f"{w:,.0f}", va="center", ha="left",
                        fontsize=7.5, color=MPL_BROWN_DARK, fontweight="bold")
        else:
            bars = ax.bar(x, values, color=bar_colors, edgecolor="white",
                          linewidth=0.6, width=0.55)
            ax.set_xticks(x)
            rotation = 30 if len(labels) > 5 else 0
            ax.set_xticklabels(labels, fontsize=7.5, color=MPL_BROWN_MED,
                               rotation=rotation, ha="right" if rotation else "center")
            ax.set_ylim(0, max_val * 1.18)
            for bar in bars:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2, h + max_val * 0.015,
                        f"{h:,.0f}", ha="center", va="bottom",
                        fontsize=7.5, color=MPL_BROWN_DARK, fontweight="bold")

        title_fs = 9.5 if fig_w_in < 4 else 11
        ax.set_title(title, fontsize=title_fs, color=MPL_BROWN_DARK,
                     fontweight="bold", pad=8, loc="left")
        fig.tight_layout(pad=1.0)
        return fig

    def _make_line_fig(self, title, labels, series, series_labels, fig_w_in):
        """Build and return a line chart figure."""
        if series and not isinstance(series[0], (list, tuple)):
            series = [series]
        series_labels = series_labels or [f"Series {i+1}" for i in range(len(series))]

        fig_h = fig_w_in * 0.44
        fig, ax = plt.subplots(figsize=(fig_w_in, fig_h))
        fig.patch.set_facecolor(MPL_CREAM)
        self._style_ax(ax)

        x = np.arange(len(labels))
        all_vals = [v for s in series for v in s]
        max_val = max(all_vals) if all_vals else 1

        for i, (vals, lbl) in enumerate(zip(series, series_labels)):
            clr = MPL_PALETTE[i % len(MPL_PALETTE)]
            ax.plot(x, vals, color=clr, linewidth=2.2, marker="o",
                    markersize=5, label=lbl, zorder=3)
            for xi, v in zip(x, vals):
                ax.text(xi, v + max_val * 0.025, f"{v:,.0f}",
                        ha="center", va="bottom",
                        fontsize=7, color=clr, fontweight="bold")

        ax.set_xticks(x)
        rotation = 25 if len(labels) > 5 else 0
        ax.set_xticklabels(labels, fontsize=7.5, color=MPL_BROWN_MED,
                           rotation=rotation, ha="right" if rotation else "center")
        ax.set_ylim(0, max_val * 1.22)

        title_fs = 9.5 if fig_w_in < 4 else 11
        ax.set_title(title, fontsize=title_fs, color=MPL_BROWN_DARK,
                     fontweight="bold", pad=8, loc="left")
        if len(series) > 1:
            ax.legend(fontsize=7.5, framealpha=0.6, facecolor=MPL_CREAM,
                      edgecolor=MPL_BROWN_LIGHT, loc="upper left")
        fig.tight_layout(pad=1.0)
        return fig

    def _make_pie_fig(self, title, labels, values, fig_w_in):
        """Build and return a donut pie chart figure."""
        fig_h = fig_w_in * 0.68
        fig, ax = plt.subplots(figsize=(fig_w_in, fig_h))
        fig.patch.set_facecolor(MPL_CREAM)
        ax.set_facecolor(MPL_CREAM)

        pie_colors = [MPL_PALETTE[i % len(MPL_PALETTE)] for i in range(len(values))]
        wedges, _, autotexts = ax.pie(
            values, labels=None, colors=pie_colors,
            autopct="%1.1f%%", pctdistance=0.72, startangle=90,
            wedgeprops={"edgecolor": MPL_CREAM, "linewidth": 1.8, "width": 0.55},
        )
        for at in autotexts:
            at.set_fontsize(7.5)
            at.set_color("white")
            at.set_fontweight("bold")

        ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
                  fontsize=7.5, framealpha=0.5,
                  facecolor=MPL_CREAM, edgecolor=MPL_BROWN_LIGHT)
        title_fs = 9.5 if fig_w_in < 4 else 11
        ax.set_title(title, fontsize=title_fs, color=MPL_BROWN_DARK,
                     fontweight="bold", pad=10, loc="left")
        fig.tight_layout(pad=0.8)
        return fig

    # ------------------------------------------------------------------
    # CHARTS — public API
    # ------------------------------------------------------------------

    def add_bar_chart(
        self,
        title: str,
        labels: list,
        values: list,
        color: str = "brown",
        source: str = "",
        horizontal: bool = False,
        width_pct: float = 0.92,
    ):
        """
        Add a branded bar chart.
        color: 'brown' | 'gold' | 'multi'
        horizontal: True for horizontal bars (better for long labels)
        width_pct: fraction of page width (default 0.92)
        """
        pw = self._page_width() * width_pct
        fig = self._make_bar_fig(title, labels, values, color, horizontal, pw / 72)
        self._story.append(self._chart_to_image(fig, pw))
        self._story.append(Spacer(1, 4))
        if source:
            self.add_source(source)
            self.add_caption(f"Source: {source}")
        return self

    def add_line_chart(
        self,
        title: str,
        labels: list,
        series: list,
        series_labels: list = None,
        source: str = "",
        width_pct: float = 0.92,
    ):
        """
        Add a branded line chart. Supports multiple series.
        series: single list [v1,v2,...] or list of lists for multi-series.
        """
        pw = self._page_width() * width_pct
        fig = self._make_line_fig(title, labels, series, series_labels, pw / 72)
        self._story.append(self._chart_to_image(fig, pw))
        self._story.append(Spacer(1, 4))
        if source:
            self.add_source(source)
            self.add_caption(f"Source: {source}")
        return self

    def add_pie_chart(
        self,
        title: str,
        labels: list,
        values: list,
        source: str = "",
        width_pct: float = 0.62,
    ):
        """
        Add a branded donut/pie chart.
        width_pct: default 0.62 — pie charts look best at a moderate width.
        """
        pw = self._page_width() * width_pct
        fig = self._make_pie_fig(title, labels, values, pw / 72)
        self._story.append(self._chart_to_image(fig, pw))
        self._story.append(Spacer(1, 4))
        if source:
            self.add_source(source)
            self.add_caption(f"Source: {source}")
        return self

    def add_charts_row(self, left: dict, right: dict, source: str = ""):
        """
        Place two charts side by side in a single row.
        Each chart spec is a dict:
            {"type": "bar",  "title": ..., "labels": [...], "values": [...],
             "color": "brown", "horizontal": False}
            {"type": "line", "title": ..., "labels": [...], "series": [...],
             "series_labels": [...]}
            {"type": "pie",  "title": ..., "labels": [...], "values": [...]}

        Example:
            rb.add_charts_row(
                left={"type": "bar", "title": "IG Followers", "labels": [...], "values": [...]},
                right={"type": "pie", "title": "Content Mix", "labels": [...], "values": [...]}
            )
        """
        pw      = self._page_width()
        col_w   = (pw - 10) / 2      # 5pt gap each side
        col_in  = col_w / 72

        def build(spec, w_in):
            t = spec.get("type", "bar")
            if t == "bar":
                return self._make_bar_fig(
                    spec["title"], spec["labels"], spec["values"],
                    spec.get("color", "brown"), spec.get("horizontal", False), w_in,
                )
            elif t == "line":
                return self._make_line_fig(
                    spec["title"], spec["labels"],
                    spec["series"], spec.get("series_labels"), w_in,
                )
            elif t == "pie":
                return self._make_pie_fig(
                    spec["title"], spec["labels"], spec["values"], w_in,
                )

        left_fig  = build(left,  col_in)
        right_fig = build(right, col_in)

        left_img  = self._chart_to_image(left_fig,  col_w)
        right_img = self._chart_to_image(right_fig, col_w)

        t = Table([[left_img, right_img]], colWidths=[col_w, col_w])
        t.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
            ("COLPADDING",   (0, 0), (-1, -1), 5),
        ]))
        self._story.append(t)
        self._story.append(Spacer(1, 4))

        if source:
            self.add_source(source)
            self.add_caption(f"Source: {source}")
        return self

    # ------------------------------------------------------------------
    # SAVE
    # ------------------------------------------------------------------

    def save(self) -> Path:
        """Build and save the PDF. Returns the Path to the saved file."""
        buffer  = BytesIO()
        pw      = self._page_width()
        agent_label = self.agent_id.replace("-", " ").title()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=1.8 * cm,
            rightMargin=1.8 * cm,
            topMargin=1.5 * cm,
            bottomMargin=2.0 * cm,
            title=self.report_title,
            author="Enderun Marketing AI",
        )

        story = []

        # ── GOLD TOP BAR (thick) ─────────────────────────────────────────
        story.append(Table(
            [[""]],
            colWidths=[pw],
            rowHeights=[6],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD)]),
        ))

        # ── HEADER: dark brown logo cell | cream title cell ─────────────
        logo_col_w = 5.2 * cm
        title_col_w = pw - logo_col_w

        if LOGO_PATH.exists():
            try:
                logo_el = RLImage(
                    str(LOGO_PATH), width=4.2 * cm, height=1.6 * cm, kind="proportional"
                )
            except Exception:
                logo_el = Paragraph("ENDERUN", ParagraphStyle(
                    "LF", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold",
                    alignment=TA_CENTER, leading=16,
                ))
        else:
            logo_el = Paragraph("ENDERUN", ParagraphStyle(
                "LF2", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold",
                alignment=TA_CENTER, leading=16,
            ))

        agent_badge = ParagraphStyle(
            "ABadge", fontSize=7, textColor=GOLD, fontName="Helvetica-Bold",
            leading=10, letterSpacing=2, alignment=TA_LEFT, spaceAfter=3,
        )
        title_s = ParagraphStyle(
            "HdrTitle", fontSize=17, textColor=BROWN_DARK,
            leading=22, fontName="Helvetica-Bold",
        )
        sub_s = ParagraphStyle(
            "HdrSub", fontSize=10, textColor=BROWN_MED,
            leading=15, fontName="Helvetica",
        )
        title_block = [
            Paragraph(agent_label.upper(), agent_badge),
            Paragraph(self.report_title, title_s),
            Spacer(1, 3),
            Paragraph(self.subtitle, sub_s),
        ]

        header_t = Table(
            [[logo_el, title_block]],
            colWidths=[logo_col_w, title_col_w],
        )
        header_t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0),   WHITE),
            ("BACKGROUND",    (1, 0), (1, 0),   WHITE),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (0, 0), (0, 0),   "LEFT"),
            ("ALIGN",         (1, 0), (1, 0),   "LEFT"),
            ("LEFTPADDING",   (0, 0), (0, 0),   12),
            ("RIGHTPADDING",  (0, 0), (0, 0),   14),
            ("LEFTPADDING",   (1, 0), (1, 0),   16),
            ("RIGHTPADDING",  (1, 0), (1, 0),   12),
            ("TOPPADDING",    (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("LINEBEFORE",    (0, 0), (0, -1),  5, GOLD),
            ("BOX",           (0, 0), (-1, -1), 0.5, BEIGE),
        ]))
        story.append(header_t)

        # ── GOLD ACCENT LINE ────────────────────────────────────────────
        story.append(Table(
            [[""]],
            colWidths=[pw],
            rowHeights=[3],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD)]),
        ))
        story.append(Spacer(1, 12))

        # ── META LINE ───────────────────────────────────────────────────
        meta_s = ParagraphStyle(
            "MetaLine", fontSize=7.5, textColor=BROWN_MED,
            fontName="Helvetica", alignment=TA_CENTER, leading=11,
        )
        story.append(Paragraph(
            f"Generated: {self.today.strftime('%B %d, %Y')}  ·  "
            f"Agent: {agent_label}  ·  Prepared by: Enderun Marketing AI",
            meta_s,
        ))
        story.append(Spacer(1, 14))

        # ── USER CONTENT ────────────────────────────────────────────────
        story.extend(self._story)

        # ── DATA SOURCES (auto-appended if any registered) ──────────────
        if self._sources:
            story.append(Spacer(1, 14))
            story.append(HRFlowable(width="100%", thickness=1, color=BEIGE, spaceAfter=6))
            src_lbl = ParagraphStyle(
                "SrcLbl", fontSize=7.5, textColor=GOLD,
                fontName="Helvetica-Bold", letterSpacing=2, spaceAfter=4,
            )
            src_body = ParagraphStyle(
                "SrcBody", fontSize=8, textColor=BROWN_MED,
                leading=12, fontName="Helvetica", spaceAfter=2, leftIndent=8,
            )
            story.append(Paragraph("DATA SOURCES", src_lbl))
            for i, src in enumerate(dict.fromkeys(self._sources), 1):
                story.append(Paragraph(f"{i}.  {src}", src_body))

        # ── FOOTER FUNCTION ─────────────────────────────────────────────
        report_title_short = self.report_title
        def add_footer(canvas, doc):
            canvas.saveState()
            page_w, page_h = A4
            margin = 1.8 * cm
            footer_h = 22

            # Dark brown footer bar
            canvas.setFillColor(BROWN_DARK)
            canvas.rect(0, 0, page_w, footer_h, fill=1, stroke=0)

            # Gold accent line above footer bar
            canvas.setFillColor(GOLD)
            canvas.rect(0, footer_h, page_w, 2, fill=1, stroke=0)

            # Left: institution name (white)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica", 7.5)
            canvas.drawString(
                margin, 7,
                "Enderun Colleges  ·  Enderun Extension  ·  enderunextension.com"
            )

            # Right: page number (gold)
            canvas.setFillColor(GOLD)
            canvas.setFont("Helvetica-Bold", 8)
            canvas.drawRightString(
                page_w - margin, 7,
                f"PAGE {doc.page}"
            )
            canvas.restoreState()

        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)

        # Write to file
        self.filepath.write_bytes(buffer.getvalue())
        return self.filepath

    # ------------------------------------------------------------------
    # EMAIL
    # ------------------------------------------------------------------

    def email_to(
        self,
        recipients: list,
        subject: str = "",
        body_html: str = "",
        gmail_address: str = "",
        gmail_app_pass: str = "",
    ) -> bool:
        """
        Save the PDF (if not already saved) then email it as an attachment.

        Parameters
        ----------
        recipients    : list of email addresses
        subject       : email subject (defaults to report title + date)
        body_html     : optional HTML body (defaults to a branded summary)
        gmail_address : sender Gmail address (defaults to GMAIL_ADDRESS env var)
        gmail_app_pass: Gmail app password (defaults to GMAIL_APP_PASS env var)

        Returns True if all emails sent successfully, False if any failed.
        """
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        # Ensure PDF is saved
        if not self.filepath.exists():
            self.save()

        gmail   = gmail_address  or os.environ.get("GMAIL_ADDRESS", "")
        app_pw  = gmail_app_pass or os.environ.get("GMAIL_APP_PASS", "")
        subject = subject or f"{self.report_title} — {self.today.strftime('%B %d, %Y')}"
        agent_label = self.agent_id.replace("-", " ").title()

        if not gmail or not app_pw:
            print("  email_to: GMAIL_ADDRESS or GMAIL_APP_PASS not set — skipping email.")
            return False

        # Default branded HTML body
        if not body_html:
            body_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F4F0EB;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F0EB;padding:24px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>
      <tr>
        <td style="background:#5C3D2E;padding:20px 36px;">
          <p style="margin:0;font-size:10px;letter-spacing:3px;color:#C9A84C;text-transform:uppercase;font-weight:700;">Enderun Marketing Intelligence</p>
          <p style="margin:4px 0 0;font-size:17px;color:#fff;font-weight:700;">{self.report_title}</p>
        </td>
      </tr>
      <tr><td style="background:#C9A84C;height:3px;font-size:0;">&nbsp;</td></tr>
      <tr>
        <td style="padding:28px 36px;background:#FAF7F2;">
          <p style="margin:0 0 12px;font-size:14px;color:#2C1810;line-height:1.7;text-align:justify;">
            Please find attached the <strong>{self.report_title}</strong> prepared by the <strong>{agent_label}</strong> agent for {self.today.strftime('%B %d, %Y')}.
          </p>
          <p style="margin:0 0 12px;font-size:14px;color:#2C1810;line-height:1.7;text-align:justify;">
            The PDF report is attached to this email. Open it to view the full analysis, data tables, and strategic recommendations.
          </p>
          <p style="margin:24px 0 0;font-size:13px;color:#8B6349;">
            Auto-generated by the Enderun Marketing AI System &bull;
            <a href="https://enderunextension.com" style="color:#C9A84C;text-decoration:none;">enderunextension.com</a>
          </p>
        </td>
      </tr>
      <tr><td style="background:#C9A84C;height:4px;font-size:0;">&nbsp;</td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

        pdf_bytes = self.filepath.read_bytes()
        all_ok = True

        for recipient in recipients:
            try:
                msg = MIMEMultipart("mixed")
                msg["From"]    = f"Enderun Marketing AI <{gmail}>"
                msg["To"]      = recipient
                msg["Subject"] = subject

                msg.attach(MIMEText(body_html, "html"))

                part = MIMEBase("application", "octet-stream")
                part.set_payload(pdf_bytes)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{self.filename}"',
                )
                msg.attach(part)

                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                    server.login(gmail, app_pw)
                    server.sendmail(gmail, recipient, msg.as_string())

                print(f"  Report emailed to {recipient}")

            except Exception as e:
                print(f"  Failed to email {recipient}: {e}")
                all_ok = False

        return all_ok

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _page_width(self) -> float:
        return A4[0] - 3.6 * cm  # A4 width minus left+right margins

    @staticmethod
    def _md(text: str) -> str:
        """Convert markdown to ReportLab tags. Strip unsupported syntax."""
        t = str(text)
        t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)   # **bold** → <b>
        t = re.sub(r'~~(.+?)~~', r'\1', t)               # ~~strikethrough~~ → plain
        t = re.sub(r'(?<!\S)~(?!\s)', '', t)             # stray ~ → removed
        return t


# ---------------------------------------------------------------------------
# CONVENIENCE FUNCTION
# ---------------------------------------------------------------------------

def make_report(
    agent_id: str,
    report_title: str,
    sections: list,
    subtitle: str = "",
    filename: str = "",
) -> Path:
    """
    Quick one-call report generator for simple reports.

    sections: list of dicts, each with:
        {"type": "section",    "text": "Title"}
        {"type": "paragraph",  "text": "Body text..."}
        {"type": "bullets",    "items": ["item1", "item2"], "intro": "optional intro"}
        {"type": "kpis",       "kpis": [("Label", "Value", gold_bool), ...]}
        {"type": "table",      "headers": [...], "rows": [[...], ...], "col_widths": [...]}
        {"type": "alert",      "text": "...", "level": "warning|critical|success|info"}
        {"type": "spacer",     "height": 10}
        {"type": "caption",    "text": "..."}
        {"type": "page_break"}
    """
    rb = ReportBuilder(agent_id, report_title, subtitle=subtitle, filename=filename)

    for s in sections:
        t = s.get("type", "")
        if t == "section":
            rb.add_section(s["text"])
        elif t == "paragraph":
            rb.add_paragraph(s["text"], s.get("justify", True))
        elif t == "bullets":
            rb.add_bullets(s["items"], s.get("intro", ""))
        elif t == "kpis":
            rb.add_kpi_row(s["kpis"])
        elif t == "table":
            rb.add_table(
                s["headers"], s["rows"],
                s.get("col_widths"), s.get("center_cols"),
            )
        elif t == "alert":
            rb.add_alert_box(s["text"], s.get("level", "info"))
        elif t == "spacer":
            rb.add_spacer(s.get("height", 6))
        elif t == "caption":
            rb.add_caption(s["text"])
        elif t == "page_break":
            rb.add_page_break()

    return rb.save()
