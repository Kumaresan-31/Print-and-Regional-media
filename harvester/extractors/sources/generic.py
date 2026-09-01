import logging
from pathlib import Path
from typing import List, Optional, Callable

from harvester.models import SourceConfig, EngineType
from harvester.extractors.engines.manifest_api import ManifestApiExtractor
from harvester.extractors.engines.browser_engine import BrowserFlipbookExtractor
from harvester.extractors.engines.direct_pdf import DirectPdfExtractor

logger = logging.getLogger(__name__)


class GenericUniversalExtractor(ManifestApiExtractor):
    """
    Universal extractor capable of handling all configured sources.
    Features automatic engine fallback:
    1. If source config specifies BROWSER_FLIPBOOK -> launches Playwright stealth.
    2. If source config specifies DIRECT_PDF -> downloads direct PDF.
    3. If source config specifies MANIFEST_API -> attempts lightweight manifest/HTML scrape,
       and automatically falls back to Playwright if manifest cannot be parsed statically.
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        # If explicitly marked as flipbook
        if self.source.engine_type == EngineType.PLAYWRIGHT_FLIPBOOK:
            browser_ext = BrowserFlipbookExtractor(self.source)
            return await browser_ext.extract_pages(target_date, edition, temp_dir, progress_callback)

        # If explicitly marked as direct PDF
        if self.source.engine_type == EngineType.DIRECT_PDF:
            pdf_ext = DirectPdfExtractor(self.source)
            return await pdf_ext.extract_pages(target_date, edition, temp_dir, progress_callback)

        # Otherwise, try high-speed Manifest/API first
        try:
            pages = await super().extract_pages(target_date, edition, temp_dir, progress_callback)
            if pages:
                return pages
        except Exception as e:
            logger.warning(
                f"Manifest extraction failed for {self.source.name} ({e}). "
                "Engaging Playwright stealth browser fallback..."
            )

        # Fallback to Playwright browser engine
        if progress_callback:
            progress_callback(30, 100, "Falling back to Playwright stealth browser engine...")

        browser_ext = BrowserFlipbookExtractor(self.source)
        return await browser_ext.extract_pages(target_date, edition, temp_dir, progress_callback)
