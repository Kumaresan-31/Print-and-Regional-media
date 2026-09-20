# Deploying Automated ePaper Harvester & Digital Twin Traceability to Render

This guide walks you through deploying this application to **Render** ([render.com](https://render.com)).

---

## 🚀 Quick Overview

- **Runtime**: Python 3.11
- **Root Directory**: `backend`
- **Build Command**: `pip install -r ../requirements.txt && playwright install chromium`
- **Start Command**: `python -m harvester.cli serve --port $PORT`
- **Port**: Automatic via `$PORT` (Render defaults to `10000`)

---

## Deployment Options

You can deploy using either **Method 1: Render Blueprints (Recommended)** or **Method 2: Manual Web Service**.

---

### Method 1: Render Blueprints (Automated via `render.yaml`)

Because this repository includes [`render.yaml`](render.yaml) configured for the **Free Plan**, you can deploy directly using this 1-click link:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Kumaresan-31/Print-and-Regional-media)

Or manually follow these steps:
1. Go to [dashboard.render.com/blueprints](https://dashboard.render.com/blueprints).
2. Click **New Blueprint Instance**.
3. Select your repository: `Kumaresan-31/Print-and-Regional-media`.
4. Render will read [`render.yaml`](render.yaml) automatically.
5. Click **Apply** to deploy.

---

### Method 2: Manual Web Service Setup (via Render Dashboard)

If you prefer to configure the service manually on Render:

1. Go to [Render Dashboard](https://dashboard.render.com).
2. Click **New +** > **Web Service**.
3. Select your repository: `Kumaresan-31/Print-and-Regional-media`.
4. Configure the service settings:
   - **Name**: `epaper-harvester` (or your choice)
   - **Region**: Singapore / Frankfurt / Oregon (Choose the closest to your users)
   - **Branch**: `main`
   - **Root Directory**: `backend`
   - **Runtime**: `Python 3`
   - **Build Command**:
     ```bash
     pip install -r ../requirements.txt && playwright install chromium
     ```
   - **Start Command**:
     ```bash
     python -m harvester.cli serve --port $PORT
     ```
   - **Instance Type**: **Free** or **Starter**

5. Under **Advanced** > **Environment Variables**, add:
   | Key | Value | Notes |
   | --- | --- | --- |
   | `PYTHON_VERSION` | `3.11` | Required for binary compatibility with RapidOCR and Playwright |
   | `PLAYWRIGHT_BROWSERS_PATH` | `/opt/render/project/.playwright` | Ensures Playwright browser is cached and accessible |

6. *(Optional - Paid Starter Plan only)* Under **Disks**:
   - Click **Add Disk**
   - **Name**: `epaper-data`
   - **Mount Path**: `/var/data`
   - **Size**: `10 GB` (or desired size)

7. Click **Create Web Service**.

---

## 🆓 Free Plan Setup (No Credit Card)

On Render's Free tier, persistent disks are not supported. Our application is pre-configured with automatic graceful fallback:

1. In [`render.yaml`](render.yaml):
   - Set `plan: free`
   - Remove or comment out the `disk:` section.
2. The application will automatically store data, sessions, and snapshots inside `./data/` instead of `/var/data`.
3. Note: On the free tier, files created during the session will be wiped when the free instance spins down after 15 minutes of inactivity.

---

## 🔐 Environment Variables Reference

You can add these under the **Environment** tab in your Render dashboard:

| Variable | Description | Default / Example |
| --- | --- | --- |
| `PORT` | Web server port | Render sets this automatically (`10000`) |
| `PYTHON_VERSION` | Python runtime version | `3.11` |
| `PLAYWRIGHT_BROWSERS_PATH` | Browser binaries location | `/opt/render/project/.playwright` |
| `DATA_DIR` | Optional custom data path | `/var/data` (Starter) or `data/` (Free) |
| `TELEGRAM_ENABLED` | Enable Telegram alerts & bot | `true` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | `8681067096:AAEBDDHet4ExtSpPPLpqpRjEweDag8_Kg9Y` |
| `TELEGRAM_DEFAULT_CHAT_ID` | Telegram chat ID for alerts | `6517547045` |
| `WHATSAPP_ENABLED` | Enable WhatsApp Green API | `true` |
| `WHATSAPP_ID_INSTANCE` | Green API Instance ID | `710722740408` |
| `WHATSAPP_API_TOKEN` | Green API Token | `c15956758f...` |
| `WHATSAPP_DEFAULT_CHAT_ID` | Default WhatsApp recipient | `919445707197@c.us` |
| `SMTP_USER` | Gmail address for digests | `cuttygreenscreen@gmail.com` |
| `SMTP_PASSWORD` | Gmail App Password | (16-character Google App Password) |
| `IMAP_USER` | Gmail address for clipping inbox | `cuttygreenscreen@gmail.com` |
| `IMAP_PASSWORD` | Gmail App Password | (16-character Google App Password) |

---

## 🔍 Post-Deployment Verification

Once Render finishes the build and shows **"Your service is live 🎉"**:

1. **Open Dashboard**:
   Click your Render service URL (e.g., `https://epaper-harvester.onrender.com/`). You will see the ePaper Harvester dashboard.
2. **Interactive API Docs**:
   Navigate to `/docs` (e.g. `https://epaper-harvester.onrender.com/docs`) to test FastAPI endpoints.
3. **Traceability & Search**:
   Test the PDF Keyword Search and 3-Tier Digital Twin Traceability modals from the dashboard.
4. **Check Logs**:
   In Render dashboard > **Logs**, verify that:
   - `cron_scheduler` initialized
   - Telegram / WhatsApp bot listeners connected
   - Uvicorn started on `0.0.0.0:10000`
