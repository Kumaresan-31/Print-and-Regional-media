import re
import json
import logging
from pathlib import Path
from typing import List, Optional, Callable
import aiohttp

from harvester.models import SourceConfig
from harvester.extractors.engines.manifest_api import ManifestApiExtractor
from harvester.registry import resolve_url
from harvester.config import settings

logger = logging.getLogger(__name__)


class DainikBhaskarExtractor(ManifestApiExtractor):
    """
    Dedicated Extractor for Dainik Bhaskar (Hindi).
    Handles DB Corp page manifest querying and CDN image harvesting.
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
        
        # Look up edition ID
        ed_obj = next((e for e in self.source.available_editions if e.code == edition), None)
        edition_id = ed_obj.edition_id if ed_obj else "44"

        api_url = f"https://epaper.bhaskar.com/api/v1/edition-page-list?edition_id={edition_id}&date={year}-{month}-{day}"
        headers = {
            "User-Agent": settings.user_agent,
            "Referer": "https://epaper.bhaskar.com/",
            "Accept": "application/json, text/plain, */*",
        }

        image_urls: List[str] = []
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)

        if progress_callback:
            progress_callback(10, 100, f"Querying DB Corp API for edition {edition} ({target_date})...")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(api_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pages = data.get("data", {}).get("pages", [])
                        for p in pages:
                            img = p.get("page_image") or p.get("high_res_image") or p.get("image")
                            if img:
                                image_urls.append(img)
            except Exception as e:
                logger.warning(f"Dainik Bhaskar direct API call failed: {e}. Falling back to web page discovery.")

        if not image_urls:
            return await super().extract_pages(target_date, edition, temp_dir, progress_callback)

        if progress_callback:
            progress_callback(25, 100, f"Found {len(image_urls)} Dainik Bhaskar pages. Downloading...")

        return await self.stitcher.download_all_pages(
            image_urls=image_urls,
            temp_dir=temp_dir,
            headers=headers,
            progress_callback=progress_callback
        )
