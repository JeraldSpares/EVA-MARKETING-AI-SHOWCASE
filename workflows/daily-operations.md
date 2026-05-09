# Daily Marketing Operations Workflow
**For:** Marketing Team — Daily Use
**Managed by:** Content Strategy Agent

---

## How to Use the Agent System

### Opening the System
1. Open Claude Code in the `MARKETING DEPARTMENT` folder
2. Claude automatically loads `CLAUDE.md` (Enderun brand context)
3. Tell Claude which agent you need, or describe your task

### Quick Agent Invocations

| What you need | Say this to Claude |
|---|---|
| Write today's social media posts | "Act as the Social Media Agent. Write today's posts for [platforms]. Today's topic is [topic]." |
| Write a press release | "Act as the PR Agent. Write a press release about [event/news]." |
| Check on competitors | "Act as the Competitor Analysis Agent. Give me a weekly snapshot of our top competitors." |
| Write a drip email | "Act as the Drip Campaign Agent. Write email #3 for the SHS Inquirer sequence." |
| Create a design brief | "Act as the Designer Agent. Create a brief for an Instagram post about [topic]." |
| Analyze our metrics | "Act as the Data Analysis Agent. Here is last week's data: [paste data]. Give me insights." |
| Plan next month's content | "Act as the Content Strategy Agent. Plan October's editorial calendar." |
| Set up Google Ads | "Act as the SEO/Digital Agent. Write ad copy for a new Google campaign targeting [keyword]." |

---

## Daily Checklist by Role

### Social Media Manager (Daily)
```
Morning (8:00 AM):
[ ] Check overnight comments and DMs — respond or escalate
[ ] Post today's scheduled content (or schedule via Meta Business Suite)
[ ] Check yesterday's post performance — note top performer

Midday (12:00 PM):
[ ] Post Facebook or LinkedIn content (if scheduled for midday)
[ ] Engage with comments on morning posts
[ ] Monitor any trending topics to piggyback

Evening (5:00–6:00 PM):
[ ] Post Instagram Stories behind-the-scenes content
[ ] Queue tomorrow's content for scheduling
[ ] Flag anything that needs Design Agent attention for tomorrow
```

### Marketing Director (Weekly Review)
```
Monday:
[ ] Read Weekly Pulse Report from Data Analysis Agent
[ ] Approve content calendar for the week from Content Strategy Agent
[ ] Review any PR pitches or releases pending approval

Friday:
[ ] Review week's performance vs. targets
[ ] Approve next week's budget allocation for paid ads
[ ] Review any competitor intelligence alerts
```

---

## File Naming Convention

All output files saved to `/output/` must follow this format:

```
YYYY-MM-DD_[agent]_[description].md
```

| Agent Code | Agent |
|---|---|
| `social` | Social Media Agent |
| `pr` | PR Agent |
| `competitor` | Competitor Analysis Agent |
| `drip` | Drip Campaign Agent |
| `design` | Designer Agent |
| `data` | Data Analysis Agent |
| `content` | Content Strategy Agent |
| `seo` | SEO/Digital Agent |

**Examples:**
- `2026-04-01_social_facebook-instagram-posts.md`
- `2026-04-01_pr_open-house-press-release.md`
- `2026-04-01_data_weekly-pulse-report.md`
- `2026-04-01_design_enrollment-campaign-brief.md`

---

## Weekly Agent Sync (Every Monday)

Run this prompt every Monday morning to get your week aligned:

```
Act as the Content Strategy Agent. 

Today is [DATE]. 

Please:
1. Review the enrollment calendar (/context/enrollment-calendar.md) for this week's priorities
2. Produce this week's editorial calendar across all channels
3. Assign tasks to each agent (list what each agent should produce this week)
4. Flag any deadlines or urgent items this week
5. Note what assets the Designer Agent needs to prepare
```

---

## Monthly Marketing Review (Last Friday of Month)

Run this prompt at end of each month:

```
Act as the Data Analysis Agent.

It's the end of [MONTH]. Please:
1. Produce the Monthly Marketing Performance Report using the template in your agent file
2. Assess our performance against KPI targets
3. Recommend budget allocation changes for next month
4. Identify the top 3 content themes that worked and 2 that didn't
5. Brief all other agents on what to prioritize next month
```

---

## Escalation Contacts

| Situation | Who to Contact |
|---|---|
| Crisis / negative press | Marketing Director → PR Agent |
| Ad account issues | Digital Agent → Marketing Director |
| CRM / email platform issues | Drip Campaign Agent → IT |
| Competitor emergency | Competitor Analysis Agent → Marketing Director |
| Content approval urgency | Content Strategy Agent → Marketing Director |
