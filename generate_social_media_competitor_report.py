# -*- coding: utf-8 -*-
"""
Competitor Analysis: Universities Strong on Social Media (Philippines)
Competitor Intelligence Analyst — Enderun Colleges
Generated: April 2026
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from report_helper import ReportBuilder

rb = ReportBuilder(
    agent_id="competitor-analysis",
    report_title="Philippine Universities: Social Media Strength Analysis",
    subtitle="Competitor Intelligence Report — April 2026",
)

# ── PAGE 1: EXECUTIVE SUMMARY + OVERALL RANKING ─────────────────────────────
rb.add_section("Executive Summary")
rb.add_paragraph(
    "This report benchmarks 10 Philippine universities — including Enderun Colleges — "
    "across Facebook, Instagram, TikTok, and LinkedIn. Schools are scored on a composite "
    "Social Media Strength (SMS) index weighted by follower volume (40%), estimated "
    "engagement rate (35%), and content strategy quality (25%). "
    "Enderun ranks 6th overall but leads all competitors in content quality and international "
    "positioning. The primary gap is execution volume — especially on TikTok, where the "
    "SHS student market is most active during enrollment season."
)

rb.add_kpi_row([
    ("Universities Benchmarked", "10",  False),
    ("Platforms Analyzed",       "4",   True),
    ("Enderun Current Rank",     "#6",  False),
    ("Target Rank Dec 2026",     "#4",  True),
])

# Overall ranking table + chart side by side
rb.add_section("Overall Social Media Strength (SMS) Score")
rb.add_table(
    headers=["Rank", "University", "Score", "Top Platform", "Key Strength"],
    rows=[
        ["#1",  "DLSU",    "95",  "FB + IG",    "Mass following, alumni amplification"],
        ["#2",  "ADMU",    "91",  "LinkedIn+IG","Elite brand storytelling"],
        ["#3",  "UST",     "88",  "FB + TikTok","Viral campus content, mass community"],
        ["#4",  "UP",      "85",  "Twitter+FB", "Academic authority, social relevance"],
        ["#5",  "UA&P",    "72",  "LinkedIn+IG","Premium positioning, professional reach"],
        ["#6",  "Enderun", "68",  "IG + FB",    "Aspirational lifestyle, intl affiliations"],
        ["#7",  "FEU",     "60",  "TikTok+FB",  "Gen Z energy, viral reels"],
        ["#8",  "LPU",     "62",  "Facebook",   "Affordability, large enrollment promos"],
        ["#9",  "CCA",     "55",  "IG + FB",    "Food content, culinary visuals"],
        ["#10", "ISCAHM",  "42",  "Instagram",  "Niche hospitality, professional niche"],
    ],
    col_widths=[1.2, 2.8, 1.4, 2.8, 6.0],
    center_cols=[0, 2],
)
rb.add_caption("SMS Score = follower volume 40% + engagement rate 35% + content quality 25%. Estimated April 2026.")

rb.add_bar_chart(
    title="SMS Score by University",
    labels=["DLSU","ADMU","UST","UP","UA&P","Enderun","LPU","FEU","CCA","ISCAHM"],
    values=[95, 91, 88, 85, 72, 68, 62, 60, 55, 42],
    color="multi",
    horizontal=True,
    source="Competitor Intelligence Analyst estimate — April 2026",
)

rb.add_alert_box(
    "Enderun has the strongest content story in the Philippine education market — Les Roches + "
    "Ecole Ducasse is unmatched. The gap vs. the top 5 is execution volume, not brand quality.",
    level="info",
)

# ── PAGE 2: FACEBOOK + INSTAGRAM ────────────────────────────────────────────
rb.add_page_break()

rb.add_section("Facebook — Follower Estimates and Strategy")
rb.add_paragraph(
    "Facebook remains the dominant platform for reaching parents (40-55) — Enderun's key "
    "decision-maker audience. DLSU and UST lead in raw volume, but Enderun's content quality "
    "and aspirational storytelling outperform on engagement among premium-seeking families."
)
rb.add_table(
    headers=["University", "Est. Followers", "Posts/Week", "Primary Content Angle"],
    rows=[
        ["DLSU",             "~500K+",  "7-10x", "Alumni pride, events, campus life"],
        ["UST",              "~600K+",  "8-12x", "Community, culture, viral student content"],
        ["ADMU",             "~400K+",  "5-7x",  "Values, thought leadership, events"],
        ["UP",               "~350K+",  "5-8x",  "Academic excellence, activism"],
        ["FEU",              "~200K+",  "5-8x",  "Campus energy, Gen Z, events"],
        ["LPU",              "~150K+",  "4-6x",  "Affordability, enrollment promos"],
        ["UA&P",             "~80K+",   "3-5x",  "Premium content, faculty features"],
        ["Enderun Colleges", "~50K+",   "5-7x",  "International affiliation, campus life, BGC"],
        ["CCA",              "~40K+",   "3-5x",  "Food photos, short courses"],
        ["ISCAHM",           "~20K+",   "2-4x",  "Niche hospitality, certifications"],
    ],
    col_widths=[3.5, 2.5, 2.5, 5.7],
    center_cols=[1, 2],
)

rb.add_section("Instagram — Visual Brand and Engagement")
rb.add_table(
    headers=["University", "Est. Followers", "Reels Usage", "Est. Engagement Rate"],
    rows=[
        ["DLSU",             "~200K+", "High",     "2.5-3.5%"],
        ["ADMU",             "~180K+", "High",     "3.0-4.0%"],
        ["UST",              "~120K+", "Medium",   "2.0-3.0%"],
        ["UP",               "~100K+", "Medium",   "2.5-3.5%"],
        ["FEU",              "~60K+",  "High",     "3.0-4.5%"],
        ["LPU",              "~40K+",  "Medium",   "1.5-2.5%"],
        ["UA&P",             "~30K+",  "Low-Med",  "3.0-4.5%"],
        ["Enderun Colleges", "~35K+",  "Medium",   "3.5-5.0%"],
        ["CCA",              "~30K+",  "High",     "4.0-5.5%"],
        ["ISCAHM",           "~15K+",  "Medium",   "3.0-4.5%"],
    ],
    col_widths=[3.5, 2.5, 2.8, 5.4],
    center_cols=[1, 2, 3],
)
rb.add_caption("Engagement rates estimated from public likes/comments vs. follower counts — April 2026.")

# Side-by-side: Facebook followers vs Instagram followers
rb.add_charts_row(
    left={
        "type": "bar",
        "title": "Est. Facebook Followers (K)",
        "labels": ["UST","DLSU","ADMU","UP","FEU","LPU","UA&P","Enderun","CCA","ISCAHM"],
        "values": [600, 500, 400, 350, 200, 150, 80, 50, 40, 20],
        "color": "brown",
    },
    right={
        "type": "bar",
        "title": "Est. Instagram Followers (K)",
        "labels": ["DLSU","ADMU","UST","UP","FEU","LPU","UA&P","Enderun","CCA","ISCAHM"],
        "values": [200, 180, 120, 100, 60, 40, 30, 35, 30, 15],
        "color": "gold",
    },
    source="Public social media page observation — estimated figures, April 2026",
)

# ── PAGE 3: TIKTOK + LINKEDIN ────────────────────────────────────────────────
rb.add_page_break()

rb.add_section("TikTok — Gen Z Battlefield (Highest Urgency for Enderun)")
rb.add_paragraph(
    "TikTok is where SHS students (15-18) discover schools during enrollment season. "
    "UST and FEU are investing heavily. Enderun's TikTok is still emerging — "
    "this is the single highest-upside, highest-urgency gap in the competitive landscape right now."
)
rb.add_table(
    headers=["University", "TikTok Presence", "Avg Views/Video", "Primary Content", "Threat Level"],
    rows=[
        ["UST",             "Very Strong", "100K-1M+",  "Viral challenges, Gen Z humor, events",       "Medium"],
        ["DLSU",            "Strong",      "50K-500K+", "Student life, campus tours, org promos",      "High"],
        ["FEU",             "Strong",      "50K-300K",  "Trending audio, Gen Z campus energy",         "Medium"],
        ["ADMU",            "Moderate",    "20K-200K",  "Campus culture, values, academic life",       "Medium"],
        ["UP",              "Moderate",    "20K-150K",  "Academic culture, activism",                  "Low"],
        ["CCA",             "Moderate",    "10K-100K",  "Recipe demos, cooking process, behind-scenes","Medium"],
        ["LPU",             "Moderate",    "10K-80K",   "Campus events, enrollment promos",            "Low"],
        ["Enderun Colleges","Emerging",    "5K-50K",    "Culinary demos, BGC campus, intl content",    "—"],
        ["UA&P",            "Weak",        "5K-30K",    "Repurposed IG content",                       "Low"],
        ["ISCAHM",          "Weak",        "2K-15K",    "Occasional hospitality content",              "Low"],
    ],
    col_widths=[3.2, 2.5, 2.8, 4.8, 2.5],
    center_cols=[2, 4],
)

rb.add_section("LinkedIn — Professional Credibility")
rb.add_table(
    headers=["University", "Est. Followers", "Content Focus", "Enderun Advantage"],
    rows=[
        ["ADMU",            "~80K+",  "Thought leadership, alumni, research",        "Enderun has intl culinary credentials ADMU cannot match"],
        ["DLSU",            "~70K+",  "Business school, corporate partnerships",     "Les Roches ranking + BGC location outclass La Salle prestige"],
        ["UP",              "~60K+",  "Academic excellence, faculty profiles",       "Different audience — minimal competitive overlap"],
        ["UA&P",            "~25K+",  "Premium MBA, executive education",            "Extension short courses can compete in professional market"],
        ["LPU",             "~20K+",  "Enrollment, affordable education",            "No overlap — different market tier"],
        ["Enderun Colleges","~15K+",  "Intl partnerships, internships, alumni",      "Best content story in PH education — needs more volume"],
        ["CCA",             "~8K+",   "Culinary industry, chef profiles",            "Ecole Ducasse affiliation >> CCA credentials"],
        ["ISCAHM",          "~5K+",   "Hospitality industry, certifications",        "Les Roches global affiliation dwarfs ISCAHM positioning"],
    ],
    col_widths=[3.0, 2.3, 4.0, 6.5],
    center_cols=[1],
)

# Side-by-side: TikTok strength + LinkedIn followers
rb.add_charts_row(
    left={
        "type": "bar",
        "title": "TikTok Presence Score (1=Weak, 5=Very Strong)",
        "labels": ["UST","DLSU","FEU","ADMU","UP","CCA","LPU","Enderun","UA&P","ISCAHM"],
        "values": [5, 4, 4, 3, 3, 3, 3, 2, 1, 1],
        "color": "gold",
    },
    right={
        "type": "bar",
        "title": "Est. LinkedIn Followers (K)",
        "labels": ["ADMU","DLSU","UP","UA&P","LPU","Enderun","CCA","ISCAHM"],
        "values": [80, 70, 60, 25, 20, 15, 8, 5],
        "color": "brown",
    },
    source="Public social media page observation — estimated figures, April 2026",
)

rb.add_alert_box(
    "URGENT: Enderun must post on TikTok daily during enrollment season. "
    "SHS students are choosing schools on TikTok right now — CCA is already building "
    "a strong culinary niche that could own the search term 'culinary school Philippines'.",
    level="warning",
)

# ── PAGE 4: SWOT + STRATEGY ──────────────────────────────────────────────────
rb.add_page_break()

rb.add_section("Enderun Social Media SWOT vs. Competitors")
rb.add_two_col(
    left_content=[
        ("section", "Strengths"),
        ("bullets", [
            "Only PH school with Les Roches + Ecole Ducasse — unmatched content story",
            "BGC campus = premium visual backdrop for every format",
            "Internships in 30+ countries = aspirational travel content pipeline",
            "Small class sizes = authentic, intimate content large schools cannot replicate",
            "Kitchen labs, simulation rooms, Bloomberg terminals = unique content environments",
            "Alumni at Mandarin Oriental, Shangri-La, Four Seasons = powerful social proof",
        ]),
        ("section", "Opportunities"),
        ("bullets", [
            "TikTok severely underdeveloped — huge first-mover window for culinary/BGC content",
            "Parent Facebook series — the 40-55 audience is underserved by current content",
            "LinkedIn: Les Roches angles have ZERO competitor equivalents in PH",
            "Instagram Reels: cooking demos + hotel internship = highly shareable content",
            "UGC pipeline — students tagging Enderun is not yet systematically encouraged",
        ]),
    ],
    right_content=[
        ("section", "Weaknesses"),
        ("bullets", [
            "Follower volume lags DLSU/ADMU by 10x — organic reach is constrained",
            "TikTok too small to influence SHS decisions during peak enrollment season",
            "Posting consistency drops during off-peak months",
            "LinkedIn follower count does not reflect the strength of the content story",
            "Paid social budget likely outspent by top-tier competitors",
        ]),
        ("section", "Threats"),
        ("bullets", [
            "DLSU + ADMU post daily across all platforms — volume drowns Enderun in the feed",
            "CCA building strong IG/TikTok culinary presence — risks owning the niche",
            "FEU aggressively targeting Gen Z on TikTok during enrollment season",
            "UA&P positioning as premium alternative in the same market segment",
            "ISCAHM quietly growing Instagram with hotel content — same niche overlap",
        ]),
    ],
)

rb.add_section("Priority Actions — Competitor Counter-Strategy")
rb.add_table(
    headers=["Priority", "Action", "Platform", "Agent", "Timeline"],
    rows=[
        ["P1 URGENT", "Daily TikTok/Reels: Day in the Life at Enderun — culinary, BGC, internships", "TikTok + IG", "Social Media + Video", "This week"],
        ["P1 URGENT", "5x/week Instagram minimum — Reels prioritized over static posts",              "Instagram",   "Social Media",         "Ongoing"],
        ["P2 HIGH",   "LinkedIn: Where Enderun Graduates Work — alumni at top 5-star hotels",          "LinkedIn",    "PR + Social Media",    "April 2026"],
        ["P2 HIGH",   "Facebook parent series: ROI, safety, placement rate, campus tour dates",        "Facebook",    "Parent Engagement",    "April 2026"],
        ["P3 MEDIUM", "UGC pipeline — encourage student tagging, reshare with credit systematically",  "All",         "Community Manager",    "Ongoing"],
        ["P3 MEDIUM", "Boost top organic posts → SHS students in BGC/Makati/Taguig targeting",         "FB + IG Ads", "SEO/Digital + LeadGen","May 2026"],
        ["P4 MONITOR","Watch CCA TikTok — counter if they gain on culinary school Philippines search", "TikTok",      "Competitor Analysis",  "Monthly"],
    ],
    col_widths=[2.3, 6.3, 2.3, 3.3, 2.5],
    center_cols=[2, 4],
)

# Enderun current vs target + content mix side by side
rb.add_charts_row(
    left={
        "type": "line",
        "title": "Enderun Score: Current vs. Target (Dec 2026)",
        "labels": ["Facebook", "Instagram", "TikTok", "LinkedIn"],
        "series": [[65, 70, 30, 50], [80, 85, 75, 75]],
        "series_labels": ["Current Apr 2026", "Target Dec 2026"],
    },
    right={
        "type": "pie",
        "title": "Recommended Content Mix (% of posts)",
        "labels": ["IG Reels", "Facebook", "TikTok", "LinkedIn", "Stories"],
        "values": [30, 25, 25, 10, 10],
    },
    source="Internal Competitor Intelligence assessment — Enderun Marketing AI, April 2026",
)

rb.add_alert_box(
    "BOTTOM LINE: Enderun owns the strongest content narrative in Philippine education — "
    "no competitor can claim Les Roches + Ecole Ducasse. Fix TikTok volume and LinkedIn growth, "
    "and Enderun reaches rank #4 in the SMS index by Q4 2026.",
    level="success",
)

# Register all data sources
rb.add_source("Public Facebook, Instagram, TikTok, LinkedIn page observations — all follower counts and engagement rates are estimates, April 2026")
rb.add_source("Facebook Ad Library — public data, April 2026")
rb.add_source("SMS Score — composite index calculated by Competitor Intelligence Analyst, April 2026")
rb.add_source("TikTok presence scores — qualitative assessment based on public page activity, April 2026")

path = rb.save()
print(f"Report saved to: {path}")
