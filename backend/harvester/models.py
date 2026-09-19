from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from pydantic import BaseModel, Field


class EngineType(str, Enum):
    MANIFEST_API = "manifest_api"
    PLAYWRIGHT_FLIPBOOK = "playwright_flipbook"
    DIRECT_PDF = "direct_pdf"
    GENERIC_STITCHER = "generic_stitcher"


class SourceLanguage(str, Enum):
    ENGLISH = "English"
    HINDI = "Hindi"
    TELUGU = "Telugu"
    TAMIL = "Tamil"
    MARATHI = "Marathi"
    BENGALI = "Bengali"
    GUJARATI = "Gujarati"
    KANNADA = "Kannada"
    MALAYALAM = "Malayalam"
    ODIA = "Odia"
    PUNJABI = "Punjabi"
    URDU = "Urdu"


class EditionInfo(BaseModel):
    code: str
    name: str
    edition_id: Optional[str] = None
    url_override: Optional[str] = None


class SourceConfig(BaseModel):
    id: str
    name: str
    language: SourceLanguage
    category: str = "General"  # National, Regional, Business, Financial
    state_region: str = "National"
    engine_type: EngineType
    base_url: str
    url_template: str
    default_edition: str
    available_editions: List[EditionInfo]
    auth_required: bool = False
    schedule_time: str = "05:00"  # HH:MM IST
    active: bool = True
    headers: Dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RESOLVING_URL = "resolving_url"
    FETCHING_MANIFEST = "fetching_manifest"
    DOWNLOADING_PAGES = "downloading_pages"
    COMPILING_PDF = "compiling_pdf"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class HarvestJob(BaseModel):
    job_id: str
    source_id: str
    source_name: str
    target_date: str  # YYYY-MM-DD
    edition: str
    status: JobStatus = JobStatus.PENDING
    progress_percentage: int = 0
    total_pages: int = 0
    downloaded_pages: int = 0
    current_step: str = "Initialized"
    result_pdf_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    file_size_bytes: int = 0
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class HarvestResult(BaseModel):
    success: bool
    source_id: str
    edition: str
    target_date: str
    pdf_path: Optional[str] = None
    page_count: int = 0
    file_size_bytes: int = 0
    error: Optional[str] = None
    duration_seconds: float = 0.0


class ArchiveItem(BaseModel):
    id: str
    source_id: str
    source_name: str
    language: str
    target_date: str
    edition: str
    filename: str
    filepath: str
    file_size_mb: float
    page_count: int
    thumbnail_url: Optional[str] = None
    download_url: str
    created_at: datetime


class SessionInfo(BaseModel):
    source_id: str
    source_name: str
    has_session: bool
    cookie_count: int
    expires_at: Optional[datetime] = None
    is_valid: bool = False
    last_updated: Optional[datetime] = None


class NewsCategory(str, Enum):
    ALL = "all"
    SPORTS = "sports"
    BUSINESS = "business"
    ECONOMIC = "economic"
    POLITICAL = "political"
    CRISES_DISASTERS = "crises_disasters"


class NewsArticle(BaseModel):
    id: str
    source_id: str
    source_name: str
    category: str
    title: str
    link: str
    snippet: Optional[str] = None
    published_at: Optional[str] = None
    author: Optional[str] = None
    original_title: Optional[str] = None
    original_snippet: Optional[str] = None
    original_language: Optional[str] = None
    is_translated: bool = False

    # Digital Twin Full Traceability Fields
    ocr_raw_text: Optional[str] = None
    ocr_confidence: float = 1.0
    translation_confidence: float = 1.0
    needs_review: bool = False
    preserved_entities: List[str] = Field(default_factory=list)
    page_number: int = 1
    page_snapshot_url: Optional[str] = None
    bounding_box: Optional[List[float]] = None
    publication_date: Optional[str] = None
    audit_status: str = "verified"  # "verified", "needs_review", "disputed"


class NewsAlert(BaseModel):
    id: str
    article_id: str
    source_name: str
    severity: str = "high"  # "critical", "high", "medium", "info"
    category: str = "all"
    topic: str
    summary: str
    translated_text: str
    ocr_raw_text: str
    ocr_confidence: float = 1.0
    translation_confidence: float = 1.0
    needs_review: bool = False
    preserved_entities: List[str] = Field(default_factory=list)
    page_number: int = 1
    page_snapshot_url: Optional[str] = None
    bounding_box: Optional[List[float]] = None
    created_at: datetime = Field(default_factory=datetime.now)



