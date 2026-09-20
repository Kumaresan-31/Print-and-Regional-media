import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Tuple
import aiohttp
from PIL import Image

from harvester.models import SourceConfig
from harvester.extractors.base import BaseExtractor
from harvester.auth.session_manager import session_manager
from harvester.config import settings

logger = logging.getLogger(__name__)

LOKMAT_EDITIONS: Dict[str, str] = {
    "pune": "LOK_PULK",
    "mumbai": "LOK_MULK",
    "nagpur": "LOK_NPLK",
    "nashik": "LOK_NSLK",
    "aurangabad": "LOK_AULK",
    "kolhapur": "LOK_KLLK",
    "jalgaon": "LOK_JLLK",
    "solapur": "LOK_SOLK",
    "akola": "LOK_AKLK",
    "ahmednagar": "LOK_ANLK",
    "goa": "LOK_GOLK",
    "delhi": "LOK_NDLK",
}


class LokmatExtractor(BaseExtractor):
    """
    Dedicated High-Resolution Extractor for Lokmat ePaper.
    Harvests full broadsheet pages directly from Lokmat's official CDN API:
    https://epaperlokmat.in/eNewspaper/OutSourcingDataNew.php
    https://images.epaperlokmat.in/eNewspaper/News/...
    Stitches authentic full-resolution broadsheet issues for OCR and translation.
    """

    def _get_cookies(self, edition: str) -> Dict[str, str]:
        cookies = session_manager.get_cookie_dict(f"lokmat_{edition}")
        if not cookies:
            cookies = session_manager.get_cookie_dict("lokmat")
        return cookies

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        clean_date = target_date.replace("-", "")
        ed_lower = edition.lower()
        issue_prefix = LOKMAT_EDITIONS.get(ed_lower, "LOK_PULK")
        issue_id = f"{issue_prefix}_{clean_date}"

        logger.info(f"Harvesting Lokmat [{edition}] for date {target_date} (Issue ID: {issue_id})...")
        if progress_callback:
            progress_callback(10, 100, f"Querying Lokmat page manifest for {issue_id}...")

        cookies = self._get_cookies(edition)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Referer": "https://epaper.lokmat.com/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        manifest_url = (
            f"https://epaperlokmat.in/eNewspaper/OutSourcingDataNew.php"
            f"?operation=getThumbnailDetails&selectedIssueId={issue_id}&data=2"
        )

        timeout = aiohttp.ClientTimeout(total=60)
        connector = aiohttp.TCPConnector(limit=8, verify_ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector, cookies=cookies) as session:
            try:
                async with session.get(manifest_url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.error(f"Lokmat manifest API error: HTTP {resp.status} on {manifest_url}")
                        return []
                    pages_info = await resp.json(content_type=None)
            except Exception as me:
                logger.error(f"Failed to fetch Lokmat manifest for {issue_id}: {me}")
                return []

            if not pages_info or not isinstance(pages_info, list):
                logger.warning(f"No pages returned in Lokmat manifest for {issue_id}")
                return []

            total_pages = len(pages_info)
            logger.info(f"Lokmat [{edition}]: found {total_pages} pages to download.")

            page_image_paths: List[Path] = []
            sem = asyncio.Semaphore(4)

            async def _download_page(idx: int, p_dict: Dict[str, Any]) -> Optional[Path]:
                thumb_rel = p_dict.get("ThumbnailURL") or ""
                # Replace /Thumbnails/ with broadsheet high-res path
                high_res_rel = thumb_rel.replace("/Thumbnails/", "/").replace("Thumbnails/", "")
                page_url = f"https://images.epaperlokmat.in/eNewspaper/{high_res_rel}"
                dest_file = temp_dir / f"page_{idx:03d}.jpg"

                async with sem:
                    try:
                        async with session.get(page_url, headers=headers) as img_resp:
                            if img_resp.status == 200:
                                content = await img_resp.read()
                                if len(content) > 5000:
                                    dest_file.write_bytes(content)
                                    return dest_file
                            # Fallback to thumbnail URL if high-res fails
                            if thumb_rel:
                                fallback_url = f"https://images.epaperlokmat.in/eNewspaper/{thumb_rel}"
                                async with session.get(fallback_url, headers=headers) as fb_resp:
                                    if fb_resp.status == 200:
                                        content = await fb_resp.read()
                                        if len(content) > 5000:
                                            dest_file.write_bytes(content)
                                            return dest_file
                    except Exception as de:
                        logger.debug(f"Error downloading Lokmat page {idx}: {de}")
                return None

            tasks = [_download_page(i + 1, p) for i, p in enumerate(pages_info)]
            done_count = 0
            for fut in asyncio.as_completed(tasks):
                res_path = await fut
                done_count += 1
                if res_path and res_path.exists():
                    page_image_paths.append(res_path)
                if progress_callback:
                    pct = int(15 + (done_count / total_pages) * 75)
                    progress_callback(pct, 100, f"Downloaded {done_count}/{total_pages} Lokmat broadsheet pages...")

        page_image_paths.sort(key=lambda p: p.name)
        logger.info(f"Lokmat [{edition}]: extracted {len(page_image_paths)} pages for {target_date}")
        return page_image_paths
