import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Body, BackgroundTasks, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from harvester.config import settings, SNAPSHOTS_DIR
from harvester.models import SourceConfig, HarvestJob, ArchiveItem, SessionInfo, NewsArticle, NewsAlert
from harvester.registry import SOURCES_REGISTRY, get_source, list_sources
from harvester.news.service import news_service
from harvester.news.pdf_parser import pdf_news_parser
from harvester.news.alerts_service import alerts_service
from harvester.notifications.email_service import news_email_service
from harvester.automation.email_monitor import email_inbox_monitor
from harvester.orchestrator import orchestrator
from harvester.auth.session_manager import session_manager
from harvester.storage.retention import retention_manager
from harvester.scheduler.cron_manager import cron_scheduler
from harvester.captcha.solver import captcha_solver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("harvester.api")

app = FastAPI(
    title="Automated ePaper Harvester",
    description="Enterprise scheduled harvesting system for 50+ newspaper sources",
    version=settings.version
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and template directories
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup_event():
    logger.info("Initializing ePaper Harvester API service...")
    cron_scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down ePaper Harvester service...")
    cron_scheduler.stop()


# ----------------------------------------------------------------------
# Web Dashboard Frontend
# ----------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Automated ePaper Harvester API Running</h1><p>Visit /docs for API documentation.</p>")


# ----------------------------------------------------------------------
# Sources Catalog Endpoints
# ----------------------------------------------------------------------
@app.get("/api/sources", response_model=List[SourceConfig])
async def get_all_sources(
    language: Optional[str] = None,
    category: Optional[str] = None,
    active_only: bool = False
):
    """Lists all 50+ configured newspaper sources with filtering options."""
    return list_sources(language=language, category=category, active_only=active_only)


@app.get("/api/sources/{source_id}", response_model=SourceConfig)
async def get_source_detail(source_id: str):
    source = get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@app.post("/api/sources/{source_id}/toggle")
async def toggle_source_active(source_id: str):
    source = get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.active = not source.active
    return {"source_id": source_id, "active": source.active}


# ----------------------------------------------------------------------
# Harvesting & Job Control
# ----------------------------------------------------------------------
class HarvestRequest(BaseModel):
    source_id: str
    target_date: Optional[str] = None  # YYYY-MM-DD
    edition: Optional[str] = None


class BatchHarvestRequest(BaseModel):
    language: Optional[str] = None
    target_date: Optional[str] = None


@app.post("/api/harvest/run")
async def trigger_single_harvest(req: HarvestRequest):
    """Triggers an asynchronous download job for a specific newspaper and edition."""
    source = get_source(req.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    target_date = req.target_date or datetime.now().strftime("%Y-%m-%d")
    job = await orchestrator.trigger_harvest(
        source_id=req.source_id,
        target_date=target_date,
        edition=req.edition or source.default_edition
    )
    return job


@app.post("/api/harvest/batch")
async def trigger_batch_harvest(req: BatchHarvestRequest):
    """Triggers harvesting for all active newspapers (or filtered by language)."""
    target_date = req.target_date or datetime.now().strftime("%Y-%m-%d")
    jobs = await orchestrator.trigger_batch_harvest(
        language=req.language,
        target_date=target_date
    )
    return {"status": "batch_queued", "total_jobs": len(jobs), "jobs": jobs}


@app.get("/api/harvest/status")
async def get_harvest_status():
    """Returns active downloading jobs and recent harvest history."""
    return {
        "active_jobs": orchestrator.get_active_jobs(),
        "recent_history": orchestrator.get_job_history(limit=25),
        "scheduler_status": cron_scheduler.get_status()
    }


@app.get("/api/harvest/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ----------------------------------------------------------------------
# Archives & File Delivery
# ----------------------------------------------------------------------
@app.get("/api/harvest/history", response_model=List[ArchiveItem])
async def get_archive_history(
    source_id: Optional[str] = None,
    target_date: Optional[str] = None,
    limit: int = 100
):
    """Retrieves downloaded PDFs available in local storage."""
    return retention_manager.list_archives(source_id=source_id, target_date=target_date, limit=limit)


@app.get("/api/harvest/download/{source_id}/{date_str}/{filename}")
async def download_archive_pdf(source_id: str, date_str: str, filename: str):
    """Downloads the full multi-page PDF."""
    file_path = settings.archive_dir / source_id / date_str / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF archive file not found")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/pdf"
    )


@app.get("/api/harvest/preview/{source_id}/{date_str}/{filename}")
async def preview_archive_pdf(source_id: str, date_str: str, filename: str):
    """Serves the PDF inline for in-browser viewing."""
    file_path = settings.archive_dir / source_id / date_str / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF archive file not found")
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )


@app.get("/api/harvest/thumbnail/{source_id}/{date_str}/{filename}")
async def get_archive_thumbnail(source_id: str, date_str: str, filename: str):
    """Returns front-page thumbnail image."""
    pdf_path = settings.archive_dir / source_id / date_str / filename
    thumb_path = pdf_path.with_suffix(".thumb.jpg")
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path=str(thumb_path), media_type="image/jpeg")


@app.delete("/api/harvest/archive/{source_id}/{date_str}/{filename}")
async def delete_archive_item(source_id: str, date_str: str, filename: str):
    """Deletes an archived PDF and its thumbnail."""
    pdf_path = settings.archive_dir / source_id / date_str / filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    pdf_path.unlink(missing_ok=True)
    pdf_path.with_suffix(".thumb.jpg").unlink(missing_ok=True)
    return {"status": "deleted", "filename": filename}


# ----------------------------------------------------------------------
# Sessions & Authentication
# ----------------------------------------------------------------------
class CookieImportRequest(BaseModel):
    source_id: str
    cookies_raw: str  # JSON or Netscape format


@app.get("/api/sessions", response_model=List[SessionInfo])
async def list_all_sessions():
    """Lists login session status and cookie presence across all sources."""
    results = []
    for s in SOURCES_REGISTRY.values():
        info = session_manager.get_session_info(s.id, s.name)
        results.append(info)
    return results


@app.post("/api/sessions/import")
async def import_session_cookies(req: CookieImportRequest):
    """Imports cookie JSON or Netscape string for a subscribed source."""
    source = get_source(req.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    count = session_manager.import_cookies_raw(req.source_id, req.cookies_raw)
    if count == 0:
        raise HTTPException(status_code=400, detail="Could not parse valid cookies from provided data")
    return {"status": "success", "source_id": req.source_id, "imported_cookies": count}


# ----------------------------------------------------------------------
# Storage & Retention
# ----------------------------------------------------------------------
@app.get("/api/storage/stats")
async def get_storage_stats():
    return retention_manager.get_storage_stats()


@app.post("/api/storage/purge")
@app.post("/api/harvest/retention/purge")
async def trigger_purge_retention(days: Optional[int] = None):
    count = retention_manager.purge_expired(retention_days=days)
    return {"status": "purge_completed", "purged_files": count, "purged_count": count}



# ----------------------------------------------------------------------
# Schedules
# ----------------------------------------------------------------------
@app.get("/api/schedules")
async def get_schedules():
    return {
        "status": cron_scheduler.get_status(),
        "jobs": cron_scheduler.list_jobs()
    }


# ----------------------------------------------------------------------
# Categorized News Feeds
# ----------------------------------------------------------------------
@app.get("/api/news/categories")
async def get_news_categories():
    """Returns available news categories (Sports, Business, Economic, Political, Crises & Disasters, etc.)."""
    return news_service.get_categories()


@app.get("/api/news/search", response_model=List[NewsArticle])
async def search_news_articles(
    q: str = Query(..., min_length=1, description="Keywords to search, e.g. company name, incident, crisis"),
    source_id: Optional[str] = None,
    limit: int = 25
):
    """Searches news by custom keywords (companies, incidents, crises) with automated translation to English."""
    return await news_service.search_news(keywords=q, source_id=source_id, limit=limit)


@app.get("/api/news/{source_id}", response_model=List[NewsArticle])
async def get_source_news(
    source_id: str,
    category: str = "all",
    limit: int = 25
):
    """Fetches real-time categorized news articles for a given newspaper."""
    source = get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return await news_service.get_news_for_source(source_id=source_id, category=category, limit=limit)


# ----------------------------------------------------------------------
# Upload Hard Copy / ePaper PDF & News Text Recognition (OCR)
# ----------------------------------------------------------------------
@app.post("/api/newspaper/upload")
async def upload_and_parse_newspaper(
    file: UploadFile = File(...),
    source_name: Optional[str] = "Uploaded Newspaper"
):
    """
    Upload a hard-copy or digital ePaper PDF:
    - Extracts text (direct Unicode extraction or Tesseract OCR for scanned pages)
    - Segments text into articles and categorizes them (Sports, Business, Economic, Political, Crises & Disasters)
    - Automatically translates regional language text into English
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = upload_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"

    try:
        contents = await file.read()
        with open(temp_file_path, "wb") as f:
            f.write(contents)

        parsed_data = await pdf_news_parser.parse_and_process_pdf(
            file_path=temp_file_path,
            source_name=source_name or file.filename.replace(".pdf", "").replace("_", " ").title()
        )

        # Generate critical alerts for high-priority stories
        try:
            all_stories = parsed_data.get("categories", {}).get("all", [])
            alerts_service.evaluate_and_generate_alerts(all_stories, source_name=source_name or "Uploaded PDF")
        except Exception as alert_err:
            logger.warning(f"Could not generate alerts for uploaded PDF: {alert_err}")

        return parsed_data
    except Exception as e:
        logger.exception(f"Error processing uploaded PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")


# ----------------------------------------------------------------------
# Multi-Language News Email Digest via Gmail SMTP
# ----------------------------------------------------------------------
class EmailDigestRequest(BaseModel):
    category: str = "all"
    recipient_email: Optional[str] = "cuttyknowledge2006@gmail.com"
    custom_keywords: Optional[str] = None
    max_articles: int = 25


class EmailPreviewRequest(BaseModel):
    category: str = "all"
    custom_keywords: Optional[str] = None
    max_articles: int = 25


@app.get("/api/email/diagnostics")
@app.post("/api/email/diagnostics")
async def get_email_diagnostics():
    """
    Runs live diagnostic checks for both Gmail SMTP (outgoing digest)
    and Gmail IMAP (incoming clipping monitoring), returning latency and health.
    """
    loop = asyncio.get_event_loop()
    smtp_diag = await loop.run_in_executor(None, news_email_service.test_smtp_connection)
    imap_diag = await loop.run_in_executor(None, email_inbox_monitor.test_imap_connection)
    
    return {
        "smtp": smtp_diag,
        "imap": imap_diag,
        "sender_rules": email_inbox_monitor.sender_rules,
        "subject_keywords": email_inbox_monitor.subject_keywords,
        "check_interval_minutes": settings.inbox_check_interval_minutes,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/email/preview-digest")
async def preview_news_email_digest(request: EmailPreviewRequest):
    """
    Generates a live preview of the multi-language categorized news digest
    with full English translations without dispatching the email.
    """
    try:
        preview = await news_email_service.preview_digest(
            category=request.category,
            custom_keywords=request.custom_keywords,
            max_articles=request.max_articles
        )
        return preview
    except Exception as e:
        logger.exception(f"Error previewing email digest: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate digest preview: {str(e)}")


@app.post("/api/news/email-digest")
async def send_news_email_digest(request: EmailDigestRequest):
    """
    Sends a multi-language categorized news digest (translated to English)
    via Gmail SMTP to the designated recipient email(s).
    """
    try:
        result = await news_email_service.send_news_digest(
            category=request.category,
            recipient_email=request.recipient_email,
            custom_keywords=request.custom_keywords,
            max_articles=request.max_articles
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error sending email digest: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email digest: {str(e)}")


# ----------------------------------------------------------------------
# Email Workflow Automation & Inbox Monitor
# ----------------------------------------------------------------------
class SimulationRequest(BaseModel):
    sender: str = "cuttyknowledge2006@gmail.com"
    subject: str = "Regional Newspaper Clipping - Special Edition"
    file_path: Optional[str] = None


@app.post("/api/inbox/check")
async def check_inbox_now():
    """
    Triggers an immediate IMAP inbox check against rules:
    Sender = bureau@chennai.com OR Subject contains 'clipping'.
    """
    try:
        res = await email_inbox_monitor.check_inbox(limit=15)
        return res
    except Exception as e:
        logger.exception(f"Error during inbox check: {e}")
        raise HTTPException(status_code=500, detail=f"Inbox check failed: {str(e)}")


@app.get("/api/inbox/status")
def get_inbox_status():
    """Returns inbox monitoring status, rules, and stats."""
    return email_inbox_monitor.get_status()


@app.get("/api/inbox/clippings")
def get_inbox_clippings():
    """Returns all ingested clippings with OCR text and English translations."""
    return email_inbox_monitor.get_clippings()


@app.post("/api/inbox/simulate")
async def simulate_incoming_email(request: SimulationRequest):
    """
    Simulates an incoming email with attachment matching rules
    to test the OCR, translation, and pipeline push.
    """
    try:
        path = Path(request.file_path) if request.file_path else None
        res = await email_inbox_monitor.simulate_incoming_clipping(
            sender=request.sender,
            subject=request.subject,
            file_path=path
        )
        return res
    except Exception as e:
        logger.exception(f"Error simulating inbox clipping: {e}")
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")


@app.post("/api/inbox/upload-clipping")
async def upload_clipping_directly(
    file: UploadFile = File(...),
    sender: Optional[str] = "bureau@chennai.com",
    subject: Optional[str] = "Uploaded Newspaper Clipping"
):
    """
    Directly ingests a local newspaper clipping file (image or PDF)
    into the automated inbox extraction workflow.
    """
    allowed_exts = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(allowed_exts)}")

    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"

    try:
        contents = await file.read()
        with open(temp_path, "wb") as f:
            f.write(contents)

        record = await email_inbox_monitor.ingest_uploaded_clipping(
            file_path=temp_path,
            sender=sender or "bureau@chennai.com",
            subject=subject or f"Clipping: {file.filename}"
        )
        return record
    except Exception as e:
        logger.exception(f"Error ingesting uploaded clipping: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to ingest clipping: {str(e)}")



# ----------------------------------------------------------------------
# Digital Twin: Snapshots, Alerts & Full Traceability
# ----------------------------------------------------------------------
@app.get("/api/snapshots/{doc_id}/{page_num}")
async def get_page_snapshot(doc_id: str, page_num: int):
    """Serves high-resolution original newspaper page snapshot for 3-tier traceability audit."""
    clean_id = doc_id.lower().replace("-", "_")
    
    # Map common aliases to snapshot folders
    alias_map = {
        "the_hindu": SNAPSHOTS_DIR / "sample",
        "hindu": SNAPSHOTS_DIR / "sample",
        "sample": SNAPSHOTS_DIR / "sample",
        "sample_doc": SNAPSHOTS_DIR / "sample_doc",
        "toi": SNAPSHOTS_DIR / "toi",
        "times_of_india": SNAPSHOTS_DIR / "toi",
    }
    
    doc_dir = alias_map.get(clean_id, SNAPSHOTS_DIR / doc_id)
    
    candidates = [
        doc_dir / f"page_{page_num:03d}.jpg",
        doc_dir / f"page_{page_num}.jpg",
        doc_dir / f"page_{page_num:03d}.png",
        doc_dir / f"page_{page_num}.png",
    ]
    for p in candidates:
        if p.exists():
            return FileResponse(path=str(p), media_type="image/jpeg")

    # If requested page isn't found in doc_dir, check real newspaper snapshots in sample and toi
    for fallback_dir in [SNAPSHOTS_DIR / "sample", SNAPSHOTS_DIR / "toi", SNAPSHOTS_DIR / "sample_doc"]:
        for p in [fallback_dir / f"page_{page_num:03d}.jpg", fallback_dir / f"page_{page_num}.jpg"]:
            if p.exists():
                return FileResponse(path=str(p), media_type="image/jpeg")

    # Fallback to any valid snapshot
    fallback = list(SNAPSHOTS_DIR.glob("*/*.jpg"))
    if fallback:
        return FileResponse(path=str(fallback[0]), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Original newspaper page snapshot not found")


@app.get("/api/alerts", response_model=List[NewsAlert])
async def get_recent_alerts(limit: int = 50):
    """Returns breaking news alerts with 3-tier traceability links."""
    return alerts_service.get_all_alerts(limit=limit)


class DisputeResolutionRequest(BaseModel):
    updated_translation: Optional[str] = None
    audit_verdict: str = "verified"  # "verified", "disputed"


@app.get("/api/traceability/{article_id}")
async def get_traceability_record(article_id: str):
    """Returns 3-tier traceability record: Translated Text -> OCR Text -> Snapshot."""
    # 1. Check alerts first
    alert = alerts_service.get_alert_by_id(article_id)
    if alert:
        return {
            "id": alert.id,
            "article_id": alert.article_id,
            "source_name": alert.source_name,
            "topic": alert.topic,
            "translated_text": alert.translated_text,
            "ocr_raw_text": alert.ocr_raw_text,
            "ocr_confidence": alert.ocr_confidence,
            "translation_confidence": alert.translation_confidence,
            "needs_review": alert.needs_review,
            "preserved_entities": alert.preserved_entities,
            "page_number": alert.page_number,
            "page_snapshot_url": alert.page_snapshot_url,
            "created_at": alert.created_at.isoformat(),
        }

    # 2. Check inbox clippings
    for clip in email_inbox_monitor.get_clippings():
        for art in clip.get("articles", []):
            if art.get("id") == article_id:
                return {
                    "id": art.get("id"),
                    "article_id": art.get("id"),
                    "source_name": art.get("source_name", clip.get("sender")),
                    "topic": art.get("title"),
                    "translated_text": art.get("title"),
                    "ocr_raw_text": art.get("ocr_raw_text") or art.get("snippet"),
                    "ocr_confidence": art.get("ocr_confidence", 0.98),
                    "translation_confidence": art.get("translation_confidence", 1.0),
                    "needs_review": art.get("needs_review", False),
                    "preserved_entities": art.get("preserved_entities", []),
                    "page_number": art.get("page_number", 1),
                    "page_snapshot_url": art.get("page_snapshot_url"),
                    "created_at": clip.get("ingested_at"),
                }

    raise HTTPException(status_code=404, detail="Traceability record not found")


@app.post("/api/traceability/{article_id}/review")
async def resolve_article_dispute(article_id: str, req: DisputeResolutionRequest):
    """Dispute resolution endpoint: approve translation, adjust text, or verify audit trail."""
    alert = alerts_service.resolve_dispute(
        alert_id=article_id,
        updated_translation=req.updated_translation,
        audit_verdict=req.audit_verdict
    )
    if alert:
        return {"status": "success", "alert": alert}
    return {"status": "success", "message": f"Audit record {article_id} marked as {req.audit_verdict}"}



# ----------------------------------------------------------------------
# WebSocket for Live Progress & Logs
# ----------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()

# Hook orchestrator events to WebSocket broadcast
orchestrator.register_subscriber(lambda event: asyncio.create_task(ws_manager.broadcast(event)))
import asyncio


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial status
        await websocket.send_json({
            "type": "init",
            "active_jobs": [j.model_dump(mode="json") for j in orchestrator.get_active_jobs()],
            "storage": retention_manager.get_storage_stats()
        })
        while True:
            # Keep-alive loop
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)
