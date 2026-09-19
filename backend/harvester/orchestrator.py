import asyncio
import uuid
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from harvester.config import settings
from harvester.models import HarvestJob, JobStatus, HarvestResult, SourceConfig
from harvester.registry import get_source, list_sources
from harvester.extractors.factory import get_extractor
from harvester.storage.retention import retention_manager

# Lazy import to avoid circular dependency — imported only after harvest completes
_pdf_search_index = None

def _get_pdf_search_index():
    global _pdf_search_index
    if _pdf_search_index is None:
        try:
            from harvester.news.pdf_search_index import pdf_search_index
            _pdf_search_index = pdf_search_index
        except Exception:
            pass
    return _pdf_search_index

logger = logging.getLogger(__name__)


class HarvestOrchestrator:
    """
    Coordinates harvest jobs, worker concurrency, retry loops,
    and event broadcasting to WebSockets and console loggers.
    """

    def __init__(self, max_concurrency: int = settings.max_concurrent_harvests):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.active_jobs: Dict[str, HarvestJob] = {}
        self.job_history: List[HarvestJob] = []
        self.subscribers: List[Callable[[Dict[str, Any]], None]] = []

    def register_subscriber(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Adds event listener (e.g. WebSocket connection or log streamer).
        """
        self.subscribers.append(callback)

    def unregister_subscriber(self, callback: Callable[[Dict[str, Any]], None]):
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    def broadcast_event(self, event_type: str, data: Any):
        """
        Broadcasts status update to all connected listeners.
        """
        payload = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        for sub in list(self.subscribers):
            try:
                sub(payload)
            except Exception as e:
                logger.debug(f"Error broadcasting to subscriber: {e}")

    def create_job(
        self,
        source_id: str,
        target_date: Optional[str] = None,
        edition: Optional[str] = None
    ) -> HarvestJob:
        """
        Creates and registers a new pending harvest job.
        """
        source = get_source(source_id)
        if not source:
            raise ValueError(f"Source '{source_id}' not found in registry.")

        t_date = target_date or datetime.now().strftime("%Y-%m-%d")
        ed = edition or source.default_edition
        job_id = f"job_{uuid.uuid4().hex[:8]}"

        job = HarvestJob(
            job_id=job_id,
            source_id=source.id,
            source_name=source.name,
            target_date=t_date,
            edition=ed,
            status=JobStatus.PENDING,
            current_step="Queued for download",
        )

        self.active_jobs[job_id] = job
        self.broadcast_event("job_created", job.model_dump(mode="json"))
        return job

    async def execute_job(self, job_id: str) -> HarvestResult:
        """
        Executes a job under concurrency semaphore control.
        """
        job = self.active_jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} does not exist.")

        source = get_source(job.source_id)
        if not source:
            job.status = JobStatus.FAILED
            job.error_message = "Source configuration missing"
            return HarvestResult(success=False, source_id=job.source_id, edition=job.edition, target_date=job.target_date, error="Missing source")

        async with self.semaphore:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now()
            job.current_step = "Starting extractor"
            self.broadcast_event("job_started", job.model_dump(mode="json"))

            extractor = get_extractor(source)

            def _on_progress(current: int, total: int, step_desc: str):
                job.downloaded_pages = current
                job.total_pages = total
                if total > 0:
                    job.progress_percentage = int((current / total) * 100)
                job.current_step = step_desc
                self.broadcast_event("job_progress", job.model_dump(mode="json"))

            # Execution with retry loop for late publishing
            result: Optional[HarvestResult] = None
            max_attempts = settings.max_retries

            for attempt in range(1, max_attempts + 1):
                try:
                    result = await extractor.harvest(
                        target_date=job.target_date,
                        edition=job.edition,
                        progress_callback=_on_progress
                    )
                    if result.success:
                        break
                    else:
                        job.retry_count = attempt
                        if attempt < max_attempts:
                            job.current_step = f"Attempt {attempt} failed ({result.error}). Retrying in {settings.retry_delay_seconds}s..."
                            self.broadcast_event("job_retry", job.model_dump(mode="json"))
                            await asyncio.sleep(settings.retry_delay_seconds)
                except Exception as ex:
                    job.retry_count = attempt
                    if attempt < max_attempts:
                        await asyncio.sleep(settings.retry_delay_seconds)
                    else:
                        result = HarvestResult(
                            success=False,
                            source_id=job.source_id,
                            edition=job.edition,
                            target_date=job.target_date,
                            error=str(ex)
                        )

            job.completed_at = datetime.now()

            if result and result.success:
                job.status = JobStatus.COMPLETED
                job.progress_percentage = 100
                job.current_step = "Completed"
                job.result_pdf_path = result.pdf_path
                job.total_pages = result.page_count
                job.file_size_bytes = result.file_size_bytes
                self.broadcast_event("job_completed", job.model_dump(mode="json"))

                # ── Auto-index harvested PDF for keyword search ──────────────
                if result.pdf_path:
                    asyncio.create_task(
                        self._auto_index_pdf(result.pdf_path, job.source_id, job.target_date)
                    )
            else:
                job.status = JobStatus.FAILED
                job.error_message = result.error if result else "Unknown error"
                job.current_step = f"Failed: {job.error_message}"
                self.broadcast_event("job_failed", job.model_dump(mode="json"))

            # Move from active to history
            self.job_history.insert(0, job)
            if len(self.job_history) > 200:
                self.job_history.pop()
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]

            return result

    async def _auto_index_pdf(self, pdf_path: str, source_id: str, target_date: str):
        """Background task: OCR-index a freshly harvested PDF for keyword search."""
        idx = _get_pdf_search_index()
        if idx is None:
            return
        try:
            pdf_p = Path(pdf_path)
            ok = await idx.index_document(pdf_p, source_id, target_date)
            if ok:
                logger.info(f"Auto-indexed PDF: {source_id}/{target_date}")
        except Exception as e:
            logger.warning(f"Auto-index failed for {source_id}/{target_date}: {e}")

    async def trigger_harvest(
        self,
        source_id: str,
        target_date: Optional[str] = None,
        edition: Optional[str] = None
    ) -> HarvestJob:
        """
        Creates and schedules a background harvest job.
        """
        job = self.create_job(source_id, target_date, edition)
        asyncio.create_task(self.execute_job(job.job_id))
        return job

    async def trigger_batch_harvest(
        self,
        language: Optional[str] = None,
        target_date: Optional[str] = None
    ) -> List[HarvestJob]:
        """
        Triggers harvest for all active sources (or filtered by language).
        """
        sources = list_sources(language=language, active_only=True)
        jobs = []
        for s in sources:
            job = await self.trigger_harvest(s.id, target_date=target_date)
            jobs.append(job)
        return jobs

    def get_job(self, job_id: str) -> Optional[HarvestJob]:
        if job_id in self.active_jobs:
            return self.active_jobs[job_id]
        for j in self.job_history:
            if j.job_id == job_id:
                return j
        return None

    def get_active_jobs(self) -> List[HarvestJob]:
        return list(self.active_jobs.values())

    def get_job_history(self, limit: int = 50) -> List[HarvestJob]:
        return self.job_history[:limit]


orchestrator = HarvestOrchestrator()
