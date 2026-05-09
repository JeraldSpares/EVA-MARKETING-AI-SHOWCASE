# Zapier: Facebook Comment Auto-Reply + Lead Capture Setup

This guide walks you through connecting Facebook comments to your webhook server so that:
1. Every new comment on the Enderun Extension Facebook page gets an AI-generated reply
2. The commenter is automatically added to your drip email campaign (if their email is captured)

---

## Prerequisites

- Webhook server running on your PC (`run_webhook_server.bat`)
- ngrok installed and running to expose port 5000 publicly
- Zapier account (free tier is enough for testing)

---

## Step 1: Expose Your Webhook Server with ngrok

1. Download ngrok from https://ngrok.com/download and install it
2. Run: `ngrok http 5000`
3. Copy the HTTPS URL it gives you, e.g.: `https://abc123.ngrok-free.app`
4. Your webhook endpoint will be: `https://abc123.ngrok-free.app/fb-comment`

> **Note:** Free ngrok URLs change every restart. For a permanent URL, use a paid ngrok plan
> or deploy `webhook_server.py` to a cloud server (Render, Railway, or a VPS).

---

## Step 2: Create the Zapier Zap

### Trigger: New Comment on Facebook Page Post

1. Go to https://zapier.com → **Create Zap**
2. **Trigger App:** Facebook Pages
3. **Trigger Event:** New Comment on Page Post
4. **Connect Account:** Choose your Enderun Extension Facebook page
5. **Test trigger** — like a comment on the page to generate test data

---

### Action 1: Webhooks by Zapier (send comment data to your server)

1. **Action App:** Webhooks by Zapier
2. **Action Event:** POST
3. **URL:** `https://abc123.ngrok-free.app/fb-comment`
4. **Payload Type:** JSON
5. **Data (map these fields from the trigger):**

| Field | Value (from FB trigger) |
|---|---|
| `secret` | `<your WEBHOOK_SECRET>` |
| `comment_id` | Comment ID |
| `commenter_name` | From Name |
| `commenter_email` | *(leave blank — Facebook doesn't share emails)* |
| `comment_text` | Message |
| `post_caption` | Post Message |

6. **Test & Continue**

---

### Action 2 (Optional): Facebook Pages — Reply to Comment

If you don't have a Facebook Page Token set up for the Graph API,
you can use Zapier's built-in Facebook Pages action to post the reply:

1. **Action App:** Facebook Pages
2. **Action Event:** Reply to Comment
3. **Comment:** Choose "Comment ID" from Step 1 (the trigger)
4. **Message:** Use the **response** from Action 1 (the webhook)
   - In the Zapier response, look for `reply_text` field
   - Map it here

> **Tip:** The webhook server returns `reply_text` in its JSON response.
> Zapier can extract it from the HTTP response body in the next step.

---

## Step 3: Test the Full Flow

1. Go to your Enderun Extension Facebook page
2. Leave a test comment on any post
3. Wait 1-2 minutes for Zapier to detect it
4. Check your terminal (webhook server logs) for:
   - `Generated reply for [Name]`
   - `Reply posted to comment...`
5. Check the Facebook post — you should see the AI reply appear

---

## Step 4: Schedule Task Scheduler for Weekly Report (Manual Setup)

Since Task Scheduler needs admin rights, open **Task Scheduler** manually:

1. Press `Win + S` → search "Task Scheduler" → Open
2. Click **Create Basic Task** (right panel)
3. Name: `Enderun_WeeklyReport`
4. Trigger: **Weekly** → Every **Monday** at **8:00 AM**
5. Action: **Start a program**
6. Program: `C:\Users\Admin\OneDrive\Desktop\MARKETING DEPARTMENT\run_weekly_report.bat`
7. Click **Finish**

---

## Architecture Summary

```
Facebook Comment
       |
       v
  Zapier (New Comment trigger)
       |
       v
  Webhooks by Zapier → POST /fb-comment
       |
       v
  webhook_server.py
    ├── Claude AI generates personalized reply
    ├── Posts reply to Facebook (Graph API or Zapier)
    └── Adds commenter to leads.csv (if email available)
       |
       v
  Daily drip email picks up new lead tomorrow at 8AM
```

---

## Files Created

| File | Purpose |
|---|---|
| `webhook_server.py` | Flask server — handles /lead and /fb-comment endpoints |
| `run_webhook_server.bat` | Starts the webhook server |
| `weekly_analytics_report.py` | Generates and emails weekly marketing report |
| `run_weekly_report.bat` | Runs the weekly report (schedule in Task Scheduler) |

---

## Webhook Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/lead` | POST | Add new lead from form |
| `/fb-comment` | POST | Process Facebook comment |

### Example: Add a Lead Manually (via curl or Postman)

```json
POST http://localhost:5000/lead
{
  "secret": "<your WEBHOOK_SECRET>",
  "first_name": "Maria",
  "last_name": "Santos",
  "email": "maria@example.com",
  "program_interest": "Culinary Arts"
}
```
