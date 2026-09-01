import os
from pathlib import Path
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
TEMP_DIR = DATA_DIR / "temp"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
INBOX_ATTACHMENTS_DIR = DATA_DIR / "inbox_attachments"
INBOX_INGESTED_DIR = DATA_DIR / "inbox_ingested"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"

for directory in [DATA_DIR, ARCHIVE_DIR, TEMP_DIR, SESSIONS_DIR, LOGS_DIR, INBOX_ATTACHMENTS_DIR, INBOX_INGESTED_DIR, SNAPSHOTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


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


settings = Settings()

