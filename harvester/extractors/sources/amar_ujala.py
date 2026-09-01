import re
import json
import logging
from pathlib import Path
from typing import List, Optional, Callable
import aiohttp
from bs4 import BeautifulSoup

from harvester.models import SourceConfig
from harvester.extractors.engines.manifest_api import ManifestApiExtractor
from harvester.registry import resolve_url
from harvester.config import settings

logger = logging.getLogger(__name__)


class AmarUjalaExtractor(ManifestApiExtractor):
    """
    Dedicated Extractor for Amar Ujala (Hindi).
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        landing_url = resolve_url(self.source, target_date, edition)
        headers = {
            "User-Agent": settings.user_agent,
            "Referer": "https://epaper.amarujala.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        image_urls: List[str] = []
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)

        if progress_callback:
            progress_callback(10, 100, f"Resolving Amar Ujala edition manifest for {edition}...")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(landing_url, headers=headers) as resp:
                    html = await resp.text(errors="ignore")

                # Match page array in Javascript or JSON-LD
                match = re.search(r'\"pages\"\s*:\s*(\[.*?\])', html, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    for p in data:
                        if isinstance(p, dict):
                            img = p.get("large") or p.get("image") or p.get("highRes")
                            if img:
                                image_urls.append(img)
                        elif isinstance(p, str) and ("http" in p):
                            image_urls.append(p)
            except Exception as e:
                logger.warning(f"Amar Ujala manifest scrape error: {e}")

        if not image_urls:
            return await super().extract_pages(target_date, edition, temp_dir, progress_callback)

        if progress_callback:
            progress_callback(25, 100, f"Found {len(image_urls)} Amar Ujala pages. Downloading...")

        return await self.stitcher.download_all_pages(
            image_urls=image_urls,
            temp_dir=temp_dir,
            headers=headers,
            progress_callback=progress_callback
        )
