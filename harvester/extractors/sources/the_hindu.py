import logging
from pathlib import Path
from typing import List, Optional, Callable

from harvester.models import SourceConfig
from harvester.extractors.engines.browser_engine import BrowserFlipbookExtractor
from harvester.auth.session_manager import session_manager

logger = logging.getLogger(__name__)


class TheHinduExtractor(BrowserFlipbookExtractor):
    """
    Dedicated Extractor for The Hindu ePaper.
    Supports authenticated cookie sessions and page image extraction.
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        cookies = session_manager.load_cookies(self.source.id)
        if not cookies:
            logger.info(
                "Notice: Running The Hindu extractor without saved session cookies. "
                "Import The Hindu subscription cookies via the dashboard for complete access."
            )
            if progress_callback:
                progress_callback(5, 100, "Starting The Hindu harvest...")

        return await super().extract_pages(target_date, edition, temp_dir, progress_callback)
