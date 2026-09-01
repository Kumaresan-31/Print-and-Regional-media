import logging
from pathlib import Path
from typing import List, Optional, Callable

from harvester.models import SourceConfig
from harvester.extractors.engines.browser_engine import BrowserFlipbookExtractor
from harvester.auth.session_manager import session_manager

logger = logging.getLogger(__name__)


class ToiExtractor(BrowserFlipbookExtractor):
    """
    Dedicated Extractor for The Times of India (TOI).
    Leverages Playwright stealth automation, session cookie injection,
    and high-DPI canvas/page container capture.
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
                "Notice: Running TOI extractor without saved session cookies. "
                "Preview pages will be harvested. To harvest complete editions, "
                "import your TOI+ subscription cookies via the dashboard."
            )
            if progress_callback:
                progress_callback(5, 100, "Starting TOI harvest (using session cookies if present)...")

        return await super().extract_pages(target_date, edition, temp_dir, progress_callback)
