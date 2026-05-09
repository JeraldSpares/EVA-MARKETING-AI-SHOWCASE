#!/usr/bin/env python3
"""Eva Marketing AI — Complete Command & Agent Reference PDF"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report_helper import ReportBuilder

rb = ReportBuilder(
    agent_id="marketing-manager",
    report_title="Eva — Enderun Marketing AI",
    subtitle="Complete Command and Agent Reference Guide  |  April 2026"
)

# ─────────────────────────────────────────────
# PAGE 1: SYSTEM OVERVIEW
# ─────────────────────────────────────────────
rb.add_section("System Overview")
rb.add_paragraph(
    "Eva is the AI-powered marketing brain of Enderun Colleges. She runs 24/7 on Railway.app "
    "via Telegram, manages 27 specialized marketing agents, automates 7 daily and weekly workflows, "
    "and responds to both slash commands and natural language — in Filipino, English, or Taglish."
)

rb.add_kpi_row([
    ("Telegram Commands", "60+", False),
    ("Marketing Agents", "27", True),
    ("Auto Workflows", "9", False),
    ("Uptime", "24/7 Cloud", False),
])

rb.add_alert_box(
    "Eva runs on Railway.app — she works even when your laptop is completely OFF. "
    "Just open Telegram and start chatting.",
    level="success"
)

rb.add_section("How to Use Eva")
rb.add_bullets([
    "Open Telegram and find your @EnderunEvaBot",
    "Use slash commands (e.g. /leads, /today, /post) for specific actions",
    "Or just type naturally in Filipino or English — Eva understands both",
    "Attach PDFs, images, or send voice messages — Eva handles all of them",
    "Type /help anytime for a quick command list",
    "Use /agent [name] to activate any of the 27 specialized marketing agents",
])


# ─────────────────────────────────────────────
# PAGE 2: CORE & CONTENT COMMANDS
# ─────────────────────────────────────────────
rb.add_page_break()
rb.add_section("Core Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/start", "Start or restart conversation with Eva"],
        ["/help", "Show quick command reference list"],
        ["/status", "Check if all systems are running normally"],
        ["/today", "See today's scheduled posts and tasks at a glance"],
        ["/briefing", "Get your daily AI-powered marketing briefing"],
        ["/suggest", "Get AI content suggestions for any program or topic"],
        ["/gaps", "Find content gaps in your posting schedule"],
        ["/countdown", "Show enrollment deadline countdown timer"],
        ["/summary", "Summarize the current conversation"],
        ["/clear", "Clear conversation history and start fresh"],
        ["/retry", "Retry the last failed action"],
        ["/chatid", "Get your Telegram chat ID (needed for setup)"],
    ]
)

rb.add_section("Content and Social Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/post facebook", "Demo post to Facebook — safe, no schedule changes"],
        ["/post instagram", "Demo post to Instagram via Zapier + imgBB CDN"],
        ["/post email", "Send demo drip email to all active leads"],
        ["/post all", "Demo post to FB + IG + email simultaneously"],
        ["/schedule", "View the full weekly posting schedule"],
        ["/reschedule", "Move a scheduled post to a different date or time"],
        ["/lastposts", "View the most recently published posts"],
        ["/templates", "Access 9 pre-loaded caption templates by program"],
        ["/tiktok", "Generate a TikTok script for any program or topic"],
        ["/ideas", "Generate content ideas for any topic or program"],
        ["/hashtags", "Generate optimized hashtag sets for Facebook and Instagram"],
        ["/comment", "Generate an AI reply to a social media comment"],
        ["/voice", "Toggle voice output — English (Jenny Neural) or Filipino (Blessica Neural)"],
    ]
)

# ─────────────────────────────────────────────
# PAGE 3: LEADS, WORKSPACE, TRADING
# ─────────────────────────────────────────────
rb.add_page_break()
rb.add_section("Leads and CRM Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/leads", "View full leads summary — total, active, by program"],
        ["/lead [name or email]", "Look up a specific lead's profile and history"],
        ["/addlead", "Add a new lead — Eva will guide you through the details"],
        ["/updatelead", "Update an existing lead's information or status"],
        ["/bulklead", "Add multiple leads at once from a list or pasted data"],
        ["/report", "Generate a full analytics PDF report with charts"],
        ["/agent [name]", "Invoke a specific marketing agent by name or ID"],
        ["/addnote", "Add a note or reminder linked to a lead or topic"],
        ["/remember", "Save a fact or preference for Eva to use in future sessions"],
        ["/forget", "Delete a saved memory by keyword"],
        ["/memories", "View all memories Eva has saved for you"],
        ["/draftemail", "Draft a personalized email for a lead or contact"],
        ["/whatsapp", "Create a WhatsApp follow-up message template"],
    ]
)

rb.add_section("Google Workspace Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/cal", "View upcoming events from Google Calendar"],
        ["/addevent", "Add a new event to Google Calendar"],
        ["/inbox", "Check your Gmail inbox — latest unread emails"],
        ["/searchmail [keyword]", "Search Gmail for specific emails or threads"],
        ["/syncsheets", "Sync leads.csv data to Google Sheets"],
        ["/drivelist", "List files in your Google Drive marketing folder"],
    ]
)

rb.add_section("Trading Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/trade", "Review or execute a crypto trade signal"],
        ["/scanner start", "Start the auto signal scanner — runs every 15 minutes"],
        ["/scanner stop", "Stop the auto signal scanner"],
        ["/scanner status", "Check scanner on/off status and last signal time"],
        ["/positions", "View all open trading positions"],
        ["/balance", "Check current trading account balance"],
    ]
)

rb.add_section("Paper Trading Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/paperscan", "Scan for paper trading signals using real live prices (simulated, no real funds)"],
        ["/paperportfolio", "View your paper trading portfolio, PnL, and win rate"],
        ["/paperclose [pair]", "Close a specific paper trade position by trading pair"],
        ["/paperreset", "Reset paper trading account back to starting balance (1,000 USDT)"],
    ]
)

rb.add_section("Quality of Life Commands")
rb.add_table(
    headers=["Command", "What It Does"],
    rows=[
        ["/screenshot", "Screenshot the Enderun Extension website and send as photo in Telegram"],
        ["/screenshot [url]", "Screenshot any public URL — e.g. /screenshot facebook.com/EnderunExtension"],
        ["/generate [prompt]", "Generate a 1080x1080 social media image from a text prompt (free, no API key)"],
        ["/preview [name]", "Preview the exact drip email a lead will receive next — subject, body, CTA"],
        ["/preview [email]", "Same as above but search by email address instead of name"],
        ["/pdfreport", "Generate a live branded PDF snapshot — leads, drip steps, schedule — sent in chat"],
        ["/pdfreport prompts", "Send the complete Eva Command and Agent Reference Guide PDF (this file)"],
        ["/pdfreport agents", "Same as above — alternate keyword for the reference guide"],
    ]
)

rb.add_alert_box(
    "Generate tip: Be specific in your prompt for better results. "
    "Example: /generate professional culinary class in BGC kitchen, warm lighting, students in white uniforms",
    level="info"
)

# ─────────────────────────────────────────────
# PAGE 4: NATURAL LANGUAGE PROMPTS
# ─────────────────────────────────────────────
rb.add_page_break()
rb.add_section("Natural Language Prompts — Just Say It")
rb.add_paragraph(
    "You do not need slash commands for everything. Eva understands plain Filipino and English. "
    "These prompts trigger real actions — no commands needed."
)

rb.add_alert_box(
    "Tip: Speak naturally. Say 'Post to Facebook' or 'Sino yung hot leads?' and Eva will handle it.",
    level="info"
)

rb.add_section("Social Media and Posting")
rb.add_table(
    headers=["What to Say to Eva", "What Actually Happens"],
    rows=[
        ['"Post to Facebook"', "Triggers live Facebook post via GitHub Actions"],
        ['"Post to Instagram"', "Uploads to imgBB then posts via Zapier to Instagram"],
        ['"Send drip emails to all leads"', "Sends personalized HTML email to every active lead"],
        ['"Post to all"', "Posts to FB + IG + sends drip emails at once"],
        ['"Gawa ng caption para sa BS HM"', "AI caption for BS Hospitality Management — FB and IG ready"],
        ['"Ano pwedeng i-post bukas?"', "Suggests content ideas for tomorrow based on calendar"],
        ['"Ilang posts na tayo ngayong linggo?"', "Shows weekly posting count and schedule gaps"],
        ['"Paki-reschedule yung Wednesday post"', "Opens reschedule flow for Wednesday content"],
        ['"Gawa ng TikTok script para sa culinary"', "Full TikTok script with hook, body, and CTA"],
    ]
)

rb.add_section("Leads and CRM")
rb.add_table(
    headers=["What to Say to Eva", "What Actually Happens"],
    rows=[
        ['"Sino yung mga hot leads?"', "Shows leads scored Hot — high email open and click engagement"],
        ['"May bago bang leads ngayon?"', "Lists all leads added in the last 24 hours"],
        ['"I-follow up si [name]"', "Drafts a personalized follow-up email for that lead"],
        ['"Magkano na yung leads natin for BS CA?"', "Filters and counts leads in BS Culinary Arts"],
        ['"Sino pa hindi nag-reply?"', "Shows cold leads with zero email engagement"],
        ['"Draft email para kay [lead name]"', "Writes a personalized email based on the lead profile"],
        ['"I-update yung status ni [name] to enrolled"', "Updates lead status in leads.csv"],
    ]
)

rb.add_section("Research and Competitor Intelligence")
rb.add_table(
    headers=["What to Say to Eva", "What Actually Happens"],
    rows=[
        ['"Anong balita sa DLSU ngayon?"', "DuckDuckGo web search — DLSU competitor news with AI summary"],
        ['"I-analyze yung CCA website"', "Competitor deep dive on CCA culinary school"],
        ['"Mag-search ng hospitality trends 2026"', "Web search + AI summary of latest hospitality trends"],
        ['"Buksan mo Google"', "Playwright browser automation — opens and navigates Google"],
        ['"Icompare natin ang pricing natin vs ISCAHM"', "Competitive pricing research and analysis"],
        ['"Anong ginagawa ng Ateneo sa social media?"', "Social media competitor scan for Ateneo"],
    ]
)

rb.add_section("Voice and Multimedia")
rb.add_table(
    headers=["What to Do", "What Actually Happens"],
    rows=[
        ["Send a voice message", "Groq Whisper transcribes it, Eva responds to the full content"],
        ["Upload a PDF document", "Claude reads it natively — brief, analyze, or extract data from it"],
        ["Upload an image", "Eva analyzes it — describe, critique, or repurpose for content"],
        ['"I-voice mo yung sagot"', "Eva replies with text-to-speech audio via edge-tts"],
        ['"Switch to Filipino voice"', "Eva uses Blessica Neural for all voice replies"],
        ['"Switch to English voice"', "Eva uses Jenny Neural for all voice replies"],
    ]
)

rb.add_section("Agent Invocation via Natural Language")
rb.add_table(
    headers=["What to Say to Eva", "What Actually Happens"],
    rows=[
        ['"Invoke the Social Media Agent"', "Eva fully adopts the Social Media Agent role and voice"],
        ['"Ask the PR Agent to draft a press release"', "Eva writes as the PR Agent with formal media style"],
        ['"Use the Competitor Analysis Agent"', "Deep competitor intelligence mode — thorough research"],
        ['"I need the Business Analyst Agent"', "Revenue modeling and strategic planning mode"],
        ['"Activate Chief Strategist"', "Senior approval and high-level strategic advisory mode"],
        ['"Switch to Marketing Manager"', "Eva becomes the campaign orchestrator and coordinator"],
    ]
)

# ─────────────────────────────────────────────
# PAGE 5: AGENT ROSTER
# ─────────────────────────────────────────────
rb.add_page_break()
rb.add_section("Agent Roster — 27 Specialized Marketing Agents")
rb.add_paragraph(
    "Eva can adopt the role of any of these 27 specialized agents. Each agent has deep domain "
    "expertise and follows Enderun brand guidelines. Invoke via /agent [name] or natural language."
)

rb.add_kpi_row([
    ("Strategic", "2 Agents", False),
    ("Core Marketing", "8 Agents", True),
    ("Specialist", "9 Agents", False),
    ("Growth & Conversion", "7 Agents", False),
])

rb.add_section("Strategic Leadership — Start Here for Big Decisions")
rb.add_table(
    headers=["Agent", "Invoke As", "What They Do"],
    rows=[
        ["Chief Strategist", "/agent chief-strategist",
         "Senior strategic advisor. Approves or rejects any major proposal. Highest authority. Ask: 'Approve mo ba ito?' or 'Anong opinion mo?'"],
        ["Marketing Manager", "/agent marketing-manager",
         "Chief campaign coordinator. Manages all agents, orchestrates multi-channel campaigns, and suggests new AI capabilities for the team."],
    ]
)

rb.add_section("Core Marketing Agents")
rb.add_table(
    headers=["Agent", "Invoke As", "Specialty"],
    rows=[
        ["Social Media", "/agent social-media",
         "Daily content for Facebook, Instagram, TikTok, LinkedIn. Taglish-ready, trend-aware, brand-voice perfect."],
        ["PR Agent", "/agent pr",
         "Press releases, media pitches, influencer outreach, crisis communications, journalist contacts."],
        ["Competitor Analysis", "/agent competitor-analysis",
         "Deep intelligence on DLSU, Ateneo, CCA, ISCAHM — pricing, campaigns, enrollment, weaknesses."],
        ["Drip Campaign", "/agent drip-campaign",
         "Email sequence architecture, subject line testing, lead nurture flows, re-engagement campaigns."],
        ["Designer", "/agent designer",
         "Creative direction, Canva design briefs, visual identity guidelines, photo and video direction."],
        ["Data Analysis", "/agent data-analysis",
         "KPI dashboards, lead funnel analytics, campaign ROI, weekly performance reporting with charts."],
        ["Content Strategy", "/agent content-strategy",
         "Editorial calendar, content pillar planning, messaging hierarchy, quarterly campaign themes."],
        ["SEO and Digital", "/agent seo-digital",
         "SEO article strategy, Google Ads campaigns, Meta Ads setup, YouTube SEO, TikTok optimization."],
    ]
)

rb.add_page_break()
rb.add_section("Specialist Agents")
rb.add_table(
    headers=["Agent", "Invoke As", "Specialty"],
    rows=[
        ["Admissions", "/agent admissions",
         "Inquiry handling scripts, lead qualification, campus tour facilitation, application support for students."],
        ["Video and Multimedia", "/agent video-multimedia",
         "TikTok scripts, YouTube content plans, Instagram Reels briefs, video production direction."],
        ["Events and Activations", "/agent events-activations",
         "Open house planning, campus tours, webinars, Enderun Extension events, Banquetes activations."],
        ["Alumni Relations", "/agent alumni-relations",
         "Alumni engagement programs, testimonial collection campaigns, referral programs, alumni features."],
        ["Influencer and KOL", "/agent influencer-kol",
         "Influencer identification, outreach email scripts, campaign briefs, deliverables, and ROI tracking."],
        ["Marketing Analysis", "/agent marketing-analysis",
         "Deep data analysis with Python, chart generation, visualization, trend modeling, insight reporting."],
        ["Business Analyst", "/agent business-analyst",
         "Revenue modeling, market sizing, business cases for new programs, strategic planning frameworks."],
        ["Events Banquetes", "/agent events-banquetes",
         "Venue and catering marketing — wedding leads, corporate event proposals, Banquetes promotions."],
        ["Researcher", "/agent researcher",
         "Brand research, industry intelligence, fact-checking, competitive deep dives, source verification."],
    ]
)

rb.add_section("Growth and Conversion Agents")
rb.add_table(
    headers=["Agent", "Invoke As", "Specialty"],
    rows=[
        ["Lead Generation", "/agent lead-generation",
         "Paid lead acquisition — Facebook Lead Forms, Google Search Ads, WhatsApp Click-to-Chat, retargeting."],
        ["Community Manager", "/agent community-manager",
         "Real-time social engagement — comment replies, DM handling, Google Reviews, lead recovery."],
        ["Parent Engagement", "/agent parent-engagement",
         "Parent-focused content, parent drip email sequences, Open House parent track planning."],
        ["WhatsApp and SMS", "/agent whatsapp-sms",
         "Conversational lead follow-up and closing via WhatsApp — warm, personalized, conversion-focused."],
        ["Enrollment Tracker", "/agent enrollment-tracker",
         "Daily funnel monitoring, weekly funnel reports, enrollment forecasting, conversion rate tracking."],
        ["Blog and SEO Content", "/agent blog-seo-content",
         "Long-form SEO articles for Google ranking, content repurposing from social to blog format."],
        ["Testing Agent", "/agent testing",
         "Safe live demo testing — posts to FB/IG/email without affecting real schedule or leads.csv."],
    ]
)

rb.add_section("Special Agent")
rb.add_table(
    headers=["Agent", "Invoke As", "Specialty"],
    rows=[
        ["Crypto Trader", "/agent crypto-trader",
         "Elite crypto analyst — Smart Money Concepts (SMC), Wyckoff, ICT methodology, CVD, VWAP, "
         "liquidation heatmap, multi-timeframe analysis. Paper trading and live signal scanning."],
    ]
)

# ─────────────────────────────────────────────
# PAGE 6: AUTOMATIONS + QUICK TIPS
# ─────────────────────────────────────────────
rb.add_page_break()
rb.add_section("Automated Workflows — Runs 24/7 Without Your Laptop")
rb.add_paragraph(
    "All automations run on GitHub Actions on a fixed cloud schedule. "
    "Results are sent directly to your Telegram. No laptop, no manual trigger needed."
)

rb.add_table(
    headers=["Workflow", "Schedule (PHT)", "What It Does"],
    rows=[
        ["Social Listening", "Daily 7:50 AM",
         "Competitor website change detection + Google News scraping + AI intelligence briefing emailed to team"],
        ["Daily Facebook Post", "Daily 8:00 AM",
         "Posts today's scheduled image to Facebook with AI-generated caption via Zapier webhook"],
        ["Daily Instagram Post", "Daily 8:00 AM",
         "Posts to Instagram — image uploaded to imgBB CDN, AI caption, posted via Zapier"],
        ["Drip Email Campaign", "Daily 8:00 AM",
         "Sends personalized branded HTML email with logo to every active lead in leads.csv"],
        ["Weekly Analytics Report", "Monday 8:00 AM",
         "Branded PDF analytics report emailed to team — lead stats, program breakdown, AI insights"],
        ["Weekly Campaign Preview", "Sunday 5:00 PM",
         "PDF preview of next week: FB/IG posts + drip email schedule. Reply to approve or request changes."],
        ["Preview Reply Checker", "Sun 7PM to Mon 7AM (every 2 hrs)",
         "Polls Gmail for your approval reply. Auto-sends revised PDF if you request changes."],
        ["Competitor Alert", "Daily 9:00 AM",
         "Web search for competitor news + Telegram alert when something notable is detected"],
        ["Crypto Signal Scanner", "Every 15 min (8AM to 10PM)",
         "Auto-scans crypto pairs for strong buy/sell signals. Telegram alert when signal fires."],
    ]
)

rb.add_alert_box(
    "All workflow results are pushed to Telegram. "
    "Success = one clean summary message. Any failure = per-job breakdown with details so you can act fast.",
    level="info"
)

rb.add_section("Quick Tips for Getting the Most Out of Eva")
rb.add_bullets([
    "Type /status anytime to confirm Railway server is up and all systems are running",
    "Voice messages work best in a quiet space — Groq Whisper transcription is highly accurate",
    "Upload a PDF lead list and tell Eva to /bulklead — she extracts names and adds them automatically",
    "Use /remember to train Eva on your preferences so she carries them into future sessions",
    "The /agent command is the fastest way to switch Eva into any specialized role",
    "Paper trading (/paperscan) uses real live prices but zero real funds — safe to practice anytime",
    "Weekly Preview arrives every Sunday 5PM — reply directly to the email to approve or request changes",
    "Say 'Activate Chief Strategist' before any big campaign decision for a senior-level reality check",
    "Eva can read any PDF you upload natively — upload competitor decks, research papers, or briefs",
    "Use /draftemail + lead name for instant personalized outreach — no copy-paste needed",
])

rb.add_section("Getting Help")
rb.add_bullets([
    "/help — Quick command list inside Telegram",
    "/status — System health check",
    "/chatid — Find your Telegram chat ID if automations stop working",
    "Natural language: just ask Eva anything — she will figure it out",
])

rb.add_source("CLAUDE.md — Enderun Marketing AI System documentation, April 2026")
rb.add_source("telegram_bot.py — Eva Telegram bot source, Railway.app deployment, April 2026")
rb.add_source("agents/ directory — 27 agent definition files, verified April 2026")

path = rb.save()
print(f"\nPDF saved: {path}\n")
