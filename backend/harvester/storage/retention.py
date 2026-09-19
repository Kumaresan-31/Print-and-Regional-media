import os
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pypdf import PdfReader
from PIL import Image

from harvester.config import settings
from harvester.models import ArchiveItem
from harvester.registry import get_source

logger = logging.getLogger(__name__)


class RetentionManager:
    """
    Manages local PDF archive storage, thumbnail generation,
    storage statistics, and automated retention cleanup.
    """

    def __init__(self, archive_dir: Optional[Path] = None):
        self.archive_dir = archive_dir or settings.archive_dir
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def list_archives(
        self,
        source_id: Optional[str] = None,
        target_date: Optional[str] = None,
        limit: int = 100
    ) -> List[ArchiveItem]:
        """
        Scans archive directory and returns list of harvested PDF items.
        Structure: data/archive/<source_id>/<YYYY-MM-DD>/<filename>.pdf
        """
        items: List[ArchiveItem] = []
        if not self.archive_dir.exists():
            return items

        # Walk through files
        pdf_files = list(self.archive_dir.glob("*/*/*.pdf"))
        # Sort newest first by modification time
        pdf_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for pdf_path in pdf_files:
            try:
                # e.g., data/archive/toi/2026-08-29/toi_delhi_2026-08-29.pdf
                parts = pdf_path.parts
                src_id = parts[-3]
                date_str = parts[-2]
                filename = pdf_path.name

                if source_id and src_id != source_id:
                    continue
                if target_date and date_str != target_date:
                    continue

                source_meta = get_source(src_id)
                source_name = source_meta.name if source_meta else src_id.upper()
                lang = source_meta.language.value if source_meta else "Unknown"

                # Parse edition from filename e.g., toi_delhi_2026-08-29.pdf
                stem_parts = pdf_path.stem.split("_")
                edition = stem_parts[1] if len(stem_parts) >= 3 else "main"

                stat = pdf_path.stat()
                file_size_mb = round(stat.st_size / (1024 * 1024), 2)

                # Page count
                page_count = self._get_page_count_fast(pdf_path)

                # Thumbnail
                thumb_path = pdf_path.with_suffix(".thumb.jpg")
                thumb_url = f"/api/harvest/thumbnail/{src_id}/{date_str}/{pdf_path.name}" if thumb_path.exists() else None

                archive_id = f"{src_id}_{date_str}_{edition}"
                item = ArchiveItem(
                    id=archive_id,
                    source_id=src_id,
                    source_name=source_name,
                    language=lang,
                    target_date=date_str,
                    edition=edition,
                    filename=filename,
                    filepath=str(pdf_path),
                    file_size_mb=file_size_mb,
                    page_count=page_count,
                    thumbnail_url=thumb_url,
                    download_url=f"/api/harvest/download/{src_id}/{date_str}/{pdf_path.name}",
                    created_at=datetime.fromtimestamp(stat.st_ctime)
                )
                items.append(item)
                if len(items) >= limit:
                    break
            except Exception as e:
                logger.warning(f"Error reading archive file {pdf_path}: {e}")

        return items

    def _get_page_count_fast(self, pdf_path: Path) -> int:
        """
        Fast page count retrieval without loading all page streams.
        """
        try:
            reader = PdfReader(str(pdf_path))
            return len(reader.pages)
        except Exception:
            return 1

    def purge_expired(self, retention_days: Optional[int] = None) -> int:
        """
        Deletes PDF archives and associated thumbnails older than retention_days.
        """
        days = retention_days if retention_days is not None else settings.retention_days
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0

        logger.info(f"Running retention purge for files older than {days} days (cutoff: {cutoff_date.date()})")

        for pdf_path in self.archive_dir.glob("*/*/*.pdf"):
            try:
                mtime = datetime.fromtimestamp(pdf_path.stat().st_mtime)
                if mtime < cutoff_date:
                    # Delete PDF
                    pdf_path.unlink(missing_ok=True)
                    # Delete thumbnail
                    pdf_path.with_suffix(".thumb.jpg").unlink(missing_ok=True)
                    deleted_count += 1
                    logger.info(f"Purged expired archive: {pdf_path}")
            except Exception as e:
                logger.error(f"Error purging file {pdf_path}: {e}")

        # Clean empty date folders
        for date_dir in self.archive_dir.glob("*/*"):
            if date_dir.is_dir() and not any(date_dir.iterdir()):
                try:
                    date_dir.rmdir()
                except Exception:
                    pass

        return deleted_count

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Calculates total archives, storage size, and free disk space.
        """
        total_size_bytes = 0
        total_files = 0

        for p in self.archive_dir.glob("*/*/*.pdf"):
            try:
                total_size_bytes += p.stat().st_size
                total_files += 1
            except Exception:
                pass

        total_mb = round(total_size_bytes / (1024 * 1024), 2)
        total_gb = round(total_mb / 1024, 2)

        # Disk space
        total_disk, used_disk, free_disk = shutil.disk_usage(str(self.archive_dir))

        return {
            "total_archives": total_files,
            "archive_size_mb": total_mb,
            "archive_size_gb": total_gb,
            "free_disk_gb": round(free_disk / (1024**3), 2),
            "retention_days": settings.retention_days,
        }


retention_manager = RetentionManager()
