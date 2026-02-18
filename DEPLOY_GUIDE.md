# 🚀 Exam Support Bot — Cloud Deployment Guide
## Deploy to Render.com (Free Tier) — No localhost needed!

---

## What You'll Get
A permanent public URL like:
```
https://exam-support-bot.onrender.com
```
Accessible by **anyone on the internet**, from any device, any location — no VPN, no localhost, no port numbers.

---

## Files in This Package
```
exam_bot_cloud/
├── app.py               ← Main application (Flask + bot logic)
├── requirements.txt     ← Python dependencies
├── render.yaml          ← Render auto-configuration
├── .gitignore           ← Keeps secrets & temp files out of GitHub
└── DEPLOY_GUIDE.md      ← This file
```

---

## Step 1 — Get Your OneDrive Direct Share Link

1. Open your SharePoint / OneDrive folder in a browser
2. **Right-click the Excel file** → **Share**
3. Set permission to **"Anyone with the link can view"**
4. Click **Copy link**
5. Save this link — you'll need it in Step 4

> ⚠️ The link must point to the **file**, not the folder.
> It should look like:
> `https://unextlearning-my.sharepoint.com/:x:/g/personal/.../XXXXX?e=YYYY`

---

## Step 2 — Upload Files to GitHub

1. Go to [github.com](https://github.com) and sign in (or create a free account)
2. Click **"New repository"** → name it `exam-support-bot`
3. Set it to **Private** (recommended)
4. Click **"Create repository"**
5. Upload these 4 files to the repo:
   - `app.py`
   - `requirements.txt`
   - `render.yaml`
   - `.gitignore`

   *(Click "Add file" → "Upload files" in GitHub)*

---

## Step 3 — Create a Free Render Account

1. Go to [render.com](https://render.com)
2. Click **"Get Started for Free"**
3. Sign up using your **GitHub account** (easiest)

---

## Step 4 — Deploy on Render

1. In Render dashboard, click **"New +"** → **"Web Service"**
2. Click **"Connect a repository"** → select your `exam-support-bot` repo
3. Render will auto-detect settings from `render.yaml`
4. Confirm these settings:
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
5. Scroll to **Environment Variables** section
6. Add this variable:
   - **Key:** `ONEDRIVE_SHARE_LINK`
   - **Value:** *(paste the link you copied in Step 1)*
7. Click **"Create Web Service"**

---

## Step 5 — Wait for Deployment (~2 minutes)

Render will:
- Install all Python packages
- Start the app
- Download your Excel data from OneDrive
- Go live at your URL

You'll see a green **"Live"** badge and a URL like:
```
https://exam-support-bot.onrender.com
```

**Share this URL with anyone!** ✅

---

## Updating Your Data

The bot auto-refreshes from OneDrive every **30 minutes**.

To force an immediate refresh:
- Click the **☁️ Refresh** button in the web UI
- Or visit: `https://your-url.onrender.com/api/refresh` (POST request)

---

## Updating the Excel File on OneDrive

Just update the file in OneDrive as usual. The bot will automatically pick up changes at the next refresh interval (or when you click Refresh).

---

## Free Tier Notes (Render)

| Feature | Free Tier |
|---|---|
| Hosting | ✅ Free |
| Custom URL | ✅ yourname.onrender.com |
| Sleep after inactivity | ⚠️ Spins down after 15 min — first visit may take ~30 sec to wake up |
| Always-on | 💲 Paid plan ($7/month) |

> For exam support during active exam periods, consider upgrading to a paid plan so the server never sleeps, or ping the URL every 10 minutes to keep it awake (e.g., using [UptimeRobot](https://uptimerobot.com) — free service).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Data not loaded" banner | Check `ONEDRIVE_SHARE_LINK` env var in Render dashboard |
| OneDrive download fails | Make sure the link is set to "Anyone with the link can view" |
| App won't start | Check Render logs → click your service → "Logs" tab |
| Slow first load | Normal on free tier — server wakes up after inactivity |

---

## Need Always-On Hosting? (Alternative Free Option)

Use **[Railway.app](https://railway.app)** instead:
1. Same GitHub repo
2. Same environment variables
3. Offers $5 free credit/month (enough for 24/7 uptime)

The `app.py` works on Railway without any changes.
