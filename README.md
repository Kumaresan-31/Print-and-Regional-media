# Automated ePaper Harvester 📰

An enterprise-grade, automated scheduled newspaper harvesting system supporting **50+ Indian and international publications** (The Times of India, The Hindu, Dainik Bhaskar, Eenadu, The Indian Express, Hindustan Times, Sakshi, Amar Ujala, Lokmat, etc.).

Handles dynamic date-based URLs, authentication/session persistence, anti-bot/captcha mitigation, concurrent downloading, high-resolution PDF compilation, disk retention policies, and includes a modern web dashboard and CLI.

---

## Key Features

- **57 Configured Newspaper Sources**:
  - **English (16)**: TOI, The Hindu, Indian Express, Hindustan Times, Economic Times, Mint, Financial Express, Business Standard, Deccan Herald, Deccan Chronicle, The Tribune, The Telegraph, The Pioneer, The Statesman, Mid-Day, Free Press Journal.
  - **Hindi (12)**: Dainik Bhaskar, Dainik Jagran, Amar Ujala, Navbharat Times, Hindustan Hindi, Punjab Kesari, Prabhat Khabar, Rajasthan Patrika, Lokmat Samachar, Haribhoomi, Jansatta, Rashtriya Sahara.
  - **Telugu (8)**: Eenadu, Sakshi, Andhra Jyothi, Namasthe Telangana, Prajasakti, Nava Telangana, Surya, Vaartha.
  - **Tamil (5)**: Daily Thanthi, Dinamalar, Dinakaran, Hindu Tamil Thisai, Dinamani.
  - **Marathi (6)**: Lokmat, Loksatta, Maharashtra Times, Sakaal, Saamana, Pudhari.
  - **Bengali (4)**: Anandabazar Patrika (ABP), Bartaman, Ei Samay, Sangbad Pratidin.
  - **Gujarati (3)**: Gujarat Samachar, Sandesh, Divya Bhaskar.
  - **Kannada (4)**: Prajavani, Vijayavani, Vijaya Karnataka, Kannada Prabha.
  - **Malayalam (3)**: Malayala Manorama, Mathrubhumi, Deshabhimani.
  - **Odia, Punjabi, Urdu (3)**: Sambad, Daily Ajit, The Inquilab.
- **Adaptive Scraping Engines**:
  - **Manifest API Engine**: High-speed concurrent JSON/page manifest downloader with automatic retry and rate-limiting.
  - **Playwright Stealth Browser Engine**: Headless Chromium with bot evasion, cookie injection, and HTML5 canvas extraction for dynamic SPA flipbooks.
  - **Direct PDF Engine**: Streamed download and assembly for direct vector PDFs.
- **Dynamic URL Resolution**: Automatic date formatting (`{YYYY}`, `{MM}`, `{DD}`) and edition code mapping.
- **Authentication & Cookies**: Session manager with one-click cookie import (JSON or Netscape format) for paid subscription editions (The Hindu, TOI+, etc.).
- **Anti-Bot & Captcha Solving**: Playwright stealth parameters, local OCR image captcha solver, 2Captcha/AntiCaptcha hooks, and manual challenge registration.
- **Automated Scheduling**: APScheduler configured on IST (`Asia/Kolkata`) with early-morning staggered harvest runs (04:30 AM – 05:45 AM).
- **PDF Compilation & Storage**: High-resolution multi-page PDF generation (PIL + PyPDF), page bookmarks, metadata, front-page thumbnails, and automatic disk retention cleanup.
- **Modern Web Dashboard**: Glassmorphic dark UI, real-time WebSocket log streaming, live progress bars, source filtering, and an in-browser PDF reader modal.
- **CLI Utility**: Command-line interface for running individual or batch harvests, listing sources, and scheduling.

---

## Quick Start

### 1. Launch the Web Dashboard & API

```powershell
python -m harvester.cli serve --port 8000
```
Then open your browser at:
👉 **[http://localhost:8000](http://localhost:8000)**

### 2. CLI Usage Examples

#### List all configured sources:
```powershell
python -m harvester.cli list
python -m harvester.cli list --language Telugu
```

#### Run a single harvest:
```powershell
# Harvest today's Delhi edition of Indian Express
python -m harvester.cli run --source indian_express --edition delhi

# Harvest specific date
python -m harvester.cli run --source eenadu --edition hyderabad --date 2026-08-29
```

#### Batch harvest all newspapers:
```powershell
python -m harvester.cli run-all
```

#### View downloaded PDF archives:
```powershell
python -m harvester.cli archive
```

#### Import session cookies for subscribed newspapers:
```powershell
python -m harvester.cli import-cookies --source toi --file cookies.json
```

#### Run retention cleanup:
```powershell
python -m harvester.cli purge --days 14
```

---

## Architecture

```
harvester/
├── config.py                 # Configuration & paths
├── models.py                 # Pydantic schemas (Sources, Jobs, Archives)
├── registry.py               # Catalog of 57 configured newspapers
├── orchestrator.py           # Concurrency worker pool & event broadcaster
├── cli.py                    # Command-line interface
├── auth/
│   └── session_manager.py    # Cookie persistence & Netscape/JSON importer
├── captcha/
│   └── solver.py             # Anti-bot stealth, OCR solver, 2Captcha hook
├── extractors/
│   ├── base.py               # BaseExtractor abstract class
│   ├── factory.py            # Instantiates appropriate extractor
│   ├── engines/
│   │   ├── image_stitcher.py # Concurrent image downloader & PDF compiler
│   │   ├── manifest_api.py   # Manifest API extractor
│   │   ├── browser_engine.py # Playwright stealth flipbook extractor
│   │   └── direct_pdf.py     # Direct PDF downloader
│   └── sources/
│       ├── toi.py            # Times of India handler
│       ├── the_hindu.py      # The Hindu handler
│       ├── dainik_bhaskar.py # Dainik Bhaskar handler
│       ├── eenadu.py         # Eenadu handler
│       ├── indian_express.py # Indian Express handler
│       ├── sakshi.py         # Sakshi handler
│       ├── amar_ujala.py     # Amar Ujala handler
│       └── generic.py        # Universal extractor for remaining 45+ sources
├── storage/
│   └── retention.py          # Storage stats, thumbnails, and auto-cleanup
├── scheduler/
│   └── cron_manager.py       # APScheduler IST cron runner
├── api/
│   └── app.py               # FastAPI backend & WebSocket service
└── web/
    ├── templates/index.html  # Modern glassmorphism web dashboard
    └── static/
        ├── css/style.css     # Dark mode CSS design system
        └── js/app.js         # Reactive frontend with WebSocket live sync
```

---

## Testing

Run unit and integration tests:
```powershell
python -m unittest discover -s tests -p "test_*.py"
```
