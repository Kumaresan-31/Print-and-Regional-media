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


class EenaduExtractor(ManifestApiExtractor):
    """
    Dedicated Extractor for Eenadu (Telugu).
    Scrapes the daily edition manifest and downloads high-definition page images.
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        parts = target_date.split("-")
        year, month, day = parts[0], parts[1], parts[2]
        landing_url = resolve_url(self.source, target_date, edition)

        if progress_callback:
            progress_callback(10, 100, f"Querying Eenadu portal for {edition} edition ({target_date})...")

        headers = {
            "User-Agent": settings.user_agent,
            "Referer": "https://epaper.eenadu.net/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        image_urls: List[str] = []
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(landing_url, headers=headers) as resp:
                    html = await resp.text(errors="ignore")

                # 1. Search for embedded page JSON
                match = re.search(r'var\s+allPages\s*=\s*(\[.*?\]);', html, re.DOTALL)
                if match:
                    pages_data = json.loads(match.group(1))
                    for p in pages_data:
                        img = p.get("HighImage") or p.get("PageImage") or p.get("Image")
                        if img:
                            image_urls.append(img)

                # 2. Heuristic search in page images
                if not image_urls:
                    soup = BeautifulSoup(html, "html.parser")
                    for img in soup.find_all("img"):
                        src = img.get("data-src") or img.get("src") or ""
                        if "epaper" in src and any(ext in src for ext in [".jpg", ".png", ".webp"]):
                            image_urls.append(src)

            except Exception as e:
                logger.warning(f"Eenadu HTML scrape failed: {e}")

        # Fallback to base manifest discovery if empty
        if not image_urls:
            return await super().extract_pages(target_date, edition, temp_dir, progress_callback)

        if progress_callback:
            progress_callback(25, 100, f"Discovered {len(image_urls)} Eenadu pages. Downloading...")

        return await self.stitcher.download_all_pages(
            image_urls=image_urls,
            temp_dir=temp_dir,
            headers=headers,
            progress_callback=progress_callback
        )
