import os
from pathlib import Path
from pydantic import BaseModel, Field

# Project root: backend/harvester/ -> ../../ -> project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# On Render, if a persistent disk is mounted at /var/data and writable, use it
# so harvested PDFs, sessions, and indexes survive restarts.
# On Render Free tier (no persistent disk) or locally, fall back to BASE_DIR / "data".
custom_data_dir = os.environ.get("DATA_DIR")
if custom_data_dir:
    DATA_DIR = Path(custom_data_dir)
elif os.environ.get("RENDER"):
    render_disk = Path("/var/data")
    if render_disk.exists() and os.access(str(render_disk), os.W_OK):
        DATA_DIR = render_disk
    else:
        DATA_DIR = BASE_DIR / "data"
else:
    DATA_DIR = BASE_DIR / "data"

ARCHIVE_DIR = DATA_DIR / "archive"
TEMP_DIR = DATA_DIR / "temp"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
INBOX_ATTACHMENTS_DIR = DATA_DIR / "inbox_attachments"
INBOX_INGESTED_DIR = DATA_DIR / "inbox_ingested"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
PDF_INDEX_DIR = DATA_DIR / "pdf_index"
EXPORTS_DIR = DATA_DIR / "exports"

for directory in [DATA_DIR, ARCHIVE_DIR, TEMP_DIR, SESSIONS_DIR, LOGS_DIR, INBOX_ATTACHMENTS_DIR, INBOX_INGESTED_DIR, SNAPSHOTS_DIR, PDF_INDEX_DIR, EXPORTS_DIR]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[WARN] Could not create directory {directory}: {e}")



class Settings(BaseModel):
    app_name: str = "Automated ePaper Harvester"
    version: str = "2.1.0"
    
    # Storage settings
    base_dir: Path = BASE_DIR
    archive_dir: Path = ARCHIVE_DIR
    temp_dir: Path = TEMP_DIR
    sessions_dir: Path = SESSIONS_DIR
    logs_dir: Path = LOGS_DIR
    snapshots_dir: Path = SNAPSHOTS_DIR
    pdf_index_dir: Path = PDF_INDEX_DIR
    exports_dir: Path = EXPORTS_DIR
    
    # Retention policy in days (default 14 days)
    retention_days: int = 14

    # Digital Twin OCR & Translation Confidence Thresholds
    ocr_confidence_threshold: float = 0.85
    translation_confidence_threshold: float = 0.85

    
    # Worker & concurrency settings
    max_concurrent_harvests: int = 3
    max_page_download_workers: int = 6
    http_timeout_seconds: int = 45
    max_retries: int = 3
    retry_delay_seconds: int = 5
    
    # Browser / Playwright settings
    headless: bool = True
    browser_timeout_ms: int = 40000
    viewport_width: int = 1920
    viewport_height: int = 1080
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )
    
    # Captcha Solving settings
    captcha_provider: str = "local_ocr"  # "local_ocr", "2captcha", "anticaptcha", "manual"
    twocaptcha_api_key: str = ""
    anticaptcha_api_key: str = ""
    
    # Scheduler defaults
    default_schedule_cron: str = "0 5 * * *"  # 5:00 AM daily
    timezone: str = "Asia/Kolkata"
    
    # Web UI / API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # SMTP / Email Digest settings
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = "cuttygreenscreen@gmail.com"
    smtp_password: str = "doyrgqjhukzamsxy"
    default_recipient_email: str = "cuttyknowledge2006@gmail.com"

    # IMAP Inbox Monitor & Extraction settings
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = "cuttygreenscreen@gmail.com"
    imap_password: str = "doyrgqjhukzamsxy"
    email_monitor_sender_rules: list = ["cuttyknowledge2006@gmail.com", "bureau@chennai.com"]
    email_monitor_subject_keywords: list = ["clipping"]
    inbox_check_interval_minutes: int = 15

    # Telegram Bot Integration settings
    telegram_bot_token: str = "8681067096:AAEBDDHet4ExtSpPPLpqpRjEweDag8_Kg9Y"
    telegram_default_chat_id: str = "6517547045"
    telegram_enabled: bool = True
    telegram_registered_chats_file: Path = DATA_DIR / "telegram_chats.json"

    # WhatsApp Green API settings (https://green-api.com)
    whatsapp_id_instance: str = "710722740408"
    whatsapp_api_token: str = "c15956758f6c49c3bd1b1f1665120de6b2f02f6c9ba14592af"
    whatsapp_api_base: str = "https://api.green-api.com"
    whatsapp_media_base: str = "https://media.green-api.com"
    whatsapp_default_chat_id: str = "919445707197@c.us"
    whatsapp_enabled: bool = True
    whatsapp_registered_chats_file: Path = DATA_DIR / "whatsapp_chats.json"


settings = Settings()


