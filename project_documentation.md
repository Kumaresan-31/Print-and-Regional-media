# ePaper Harvester & Digital Twin Traceability System

## Overview
The **ePaper Harvester** is a comprehensive, automated system designed to aggregate, process, and analyze news from over 50 regional and national newspaper sources across India. It features a unique **3-Tier Digital Twin Traceability** system that guarantees the authenticity of news by tracking translated summaries back to their original regional language extraction and printed physical snapshots.

## Key Features
- **Automated ePaper Ingestion**: Monitors email inboxes (IMAP) for daily newspaper clippings and automatically downloads PDF attachments.
- **Advanced OCR Pipeline**: Utilizes state-of-the-art **RapidOCR** (ONNX-based) to extract multi-lingual text from highly complex, unstructured newspaper PDFs.
- **Live News Aggregation**: Syncs with live RSS feeds and web sources to maintain a real-time repository of the latest news across various categories (Business, Politics, Sports, etc.).
- **3-Tier Traceability Audit**: 
  - **Tier 1 (Translated Text)**: Clean, English-translated text representing the final digestible news.
  - **Tier 2 (OCR Raw Extraction)**: The raw, unedited regional language text exactly as extracted by the OCR engine.
  - **Tier 3 (Digital Snapshot)**: A visual snapshot of the original printed newspaper page (or dynamically generated digital clippings for live web feeds).
- **Scheduled Harvesting**: Runs scheduled cron jobs (via APScheduler) to scrape, aggregate, and purge data at defined intervals to maintain storage efficiency.
- **Unified Dashboard**: A high-performance, dark-themed vanilla JavaScript dashboard that provides a real-time ticker, categorized news filtering, and instant access to the digital twin traceability modal.

---

## Architecture & Components

### 1. API Gateway (`harvester/api/app.py`)
Built on **FastAPI**, this serves as the backend gateway for the frontend dashboard. 
- Serves the static HTML/JS/CSS assets.
- Exposes REST endpoints for querying live news (`/api/news/{source_id}`), fetching traceability records (`/api/traceability/{article_id}`), and serving high-resolution image snapshots.
- Includes a dynamic image generator (`/api/dynamic_snapshot/`) that uses Python `Pillow (PIL)` to instantly create newspaper-style snapshot clippings for RSS articles that lack physical scans.

### 2. Frontend Dashboard (`harvester/web/`)
A responsive, vanilla HTML/JS/CSS dashboard.
- **`index.html`**: Structures the grid layout, the live ticker, the news cards, and the modal dialogs.
- **`app.js`**: Manages application state, handles API interactions, and dynamically populates the 3-Tier Traceability Modal. It renders the news feed asynchronously for a seamless user experience.

### 3. News Feed Aggregation (`harvester/news/service.py`)
The `NewsFeedService` is a robust background service that handles caching and aggregating live RSS feeds.
- Implements a fast in-memory caching layer with TTL (Time-To-Live) to prevent rate-limiting and ensure instant API responses.
- Normalizes disparate news formats into a standard `NewsArticle` Pydantic model.

### 4. OCR & PDF Processing (`harvester/news/pdf_parser.py`)
The AI engine of the physical newspaper pipeline.
- Parses incoming PDF clippings into individual page images.
- Runs **RapidOCR** on the images to detect and recognize text blocks, preserving confidence scores for traceability.

### 5. Automation & Ingestion (`harvester/automation/email_monitor.py`)
The automated data entry point for physical scans.
- Connects to a configured IMAP email inbox.
- Scans for specific sender rules or subject keywords (e.g., "clipping").
- Extracts PDF attachments and passes them to the `pdf_parser` pipeline.

### 6. Scheduling & Cron (`harvester/scheduler/cron_manager.py`)
Powered by `APScheduler`, this module handles the lifecycle of the data.
- Schedules daily early-morning sweeps of all 50+ newspaper sources.
- Triggers regular email inbox checks every 15 minutes.
- Triggers nightly retention purges to delete outdated PDFs and clear caches, ensuring the server doesn't run out of storage space.

### 7. WhatsApp & Telegram Bot Services (`harvester/notifications/`)
- **WhatsApp Bot Service (`whatsapp_service.py`)**:
  - Powered by Green API (`idInstance: 710722740408`).
  - Real-time broadcasts for critical & high-priority alerts with WhatsApp Markdown formatting.
  - Interactive bot polling (`receiveNotification`/`deleteNotification`) supporting `/start`, `/news`, `/search`, `/alerts`, `/status`, `/sports`, `/business`.
  - Inbound PDF ingestion: Users send ePaper PDFs or clippings directly to the WhatsApp bot; it renders pages, runs RapidOCR, extracts headlines/stories, evaluates threat alerts, and replies with categorized summaries.
  - PDF document export and sharing via `/api/pdf-search/share/whatsapp` and the UI's `💬 WhatsApp` button.
- **Telegram Bot Service (`telegram_service.py`)**:
  - Telegram Bot API integration (`@Mhjkbktbot`) mirroring the same alert broadcast, interactive command, and PDF extraction pipeline.

---

## Data Flow
1. **Ingestion**: An email with a PDF newspaper clipping arrives OR a scheduled RSS sweep is triggered.
2. **Processing**: 
   - *For PDFs*: The file is downloaded, converted to images, and passed through RapidOCR. Text, bounding boxes, and snapshots are saved. Alerts are generated.
   - *For Live Feeds*: RSS XML is parsed, structured, and cached in memory.
3. **Serving**: The user opens the dashboard. The frontend polls `FastAPI` for the latest news and displays them in categorised cards.
4. **Verification**: The user clicks the **"Digital Twin Traceability"** button on an article.
5. **Traceability resolution**: 
   - `app.js` queries `/api/traceability/{article_id}`.
   - `app.py` cross-references the ID against physical OCR alerts or the live news cache.
   - If it's a live feed, it dynamically renders an image of the text via PIL and returns the English title/snippet for Tier 1 and the raw extraction format for Tier 2.
   - The UI modal opens, proving the unbroken chain of custody of the data.
