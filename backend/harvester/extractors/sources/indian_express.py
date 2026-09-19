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


class IndianExpressExtractor(ManifestApiExtractor):
    """
    Dedicated Extractor for The Indian Express.
    Parses manifest page references and downloads high-res page JPGs.
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
            "Referer": "https://epaper.indianexpress.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        image_urls: List[str] = []
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)

        if progress_callback:
            progress_callback(10, 100, f"Resolving Indian Express edition manifest for {edition}...")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(landing_url, headers=headers) as resp:
                    html = await resp.text(errors="ignore")

                # Match page array in Javascript
                match = re.search(r'var\s+edition_pages\s*=\s*(\[.*?\]);', html, re.DOTALL)
                if not match:
                    match = re.search(r'\"pages\":\s*(\[.*?\])', html, re.DOTALL)

                if match:
                    page_items = json.loads(match.group(1))
                    for item in page_items:
                        if isinstance(item, dict):
                            img = item.get("large") or item.get("high_res") or item.get("image") or item.get("src")
                            if img:
                                image_urls.append(img)
                        elif isinstance(item, str) and ("http" in item):
                            image_urls.append(item)
            except Exception as e:
                logger.warning(f"Indian Express manifest scrape error: {e}")

        if not image_urls:
            return await super().extract_pages(target_date, edition, temp_dir, progress_callback)

        if progress_callback:
            progress_callback(25, 100, f"Found {len(image_urls)} Indian Express pages. Downloading...")

        return await self.stitcher.download_all_pages(
            image_urls=image_urls,
            temp_dir=temp_dir,
            headers=headers,
            progress_callback=progress_callback
        )
