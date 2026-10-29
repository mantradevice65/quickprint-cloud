# QuickPrint 24/7 Cloud Queue Server

This is the cloud backend for QuickPrint. It allows customers to scan the counter QR code, upload documents, and pay online via Razorpay 24/7 even when the shop computer is turned off.

When the shop computer turns on, the QuickPrint Desktop software automatically downloads all queued prints, announces voice alerts, and prints them on the Canon printer.

---

## 🚀 2-Minute Deployment to Render.com (100% Free)

### Step 1: Create a GitHub Repository
1. Open [https://github.com/new](https://github.com/new)
2. Name it: `quickprint-cloud`
3. Click **Create repository**

### Step 2: Push this folder to GitHub
Open Command Prompt in this folder and run:
```bash
git init
git add .
git commit -m "Initial QuickPrint Cloud commit"
git branch -M main
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/quickprint-cloud.git
git push -u origin main
```

### Step 3: Deploy on Render.com
1. Go to [https://dashboard.render.com](https://dashboard.render.com) (Sign in with Google or GitHub).
2. Click **New +** -> **Web Service**.
3. Select **Build and deploy from a Git repository** -> Connect your `quickprint-cloud` repo.
4. Settings:
   - **Name:** `quickprint-cloud`
   - **Language:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT`
   - **Instance Type:** `Free`
5. Click **Deploy Web Service**!

Render will give you a free URL like:
`https://quickprint-cloud.onrender.com`

---

## 🌐 Pointing Domain `print.fruitsgenerator.co.in`
In Cloudflare DNS for `fruitsgenerator.co.in`:
- Point `CNAME print.fruitsgenerator.co.in` to `quickprint-cloud.onrender.com` (or your Render URL).
- In Render Dashboard under **Settings** -> **Custom Domains**, add `print.fruitsgenerator.co.in`.
