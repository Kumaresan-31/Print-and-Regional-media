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


class SakshiExtractor(ManifestApiExtractor):
    """
    Dedicated Extractor for Sakshi (Telugu).
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
            "Referer": "https://epaper.sakshi.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        image_urls: List[str] = []
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)

        if progress_callback:
            progress_callback(10, 100, f"Resolving Sakshi edition manifest for {edition}...")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(landing_url, headers=headers) as resp:
                    html = await resp.text(errors="ignore")

                # Match script page array
                match = re.search(r'var\s+editionData\s*=\s*({.*?});', html, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    for p in data.get("pages", []):
                        img = p.get("HighResolution") or p.get("ImagePath") or p.get("Url")
                        if img:
                            image_urls.append(img)
                
                # HTML img search
                if not image_urls:
                    soup = BeautifulSoup(html, "html.parser")
                    for img in soup.find_all("img"):
                        src = img.get("data-src") or img.get("src") or ""
                        if "sakshi" in src and any(ext in src for ext in [".jpg", ".png"]):
                            image_urls.append(src)
            except Exception as e:
                logger.warning(f"Sakshi manifest scrape error: {e}")

        if not image_urls:
            return await super().extract_pages(target_date, edition, temp_dir, progress_callback)

        if progress_callback:
            progress_callback(25, 100, f"Found {len(image_urls)} Sakshi pages. Downloading...")

        return await self.stitcher.download_all_pages(
            image_urls=image_urls,
            temp_dir=temp_dir,
            headers=headers,
            progress_callback=progress_callback
        )
