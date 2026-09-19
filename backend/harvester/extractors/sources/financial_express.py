import io
import re
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

EDITION_MAP: Dict[str, Tuple[str, str]] = {
    "delhi": ("227", "Delhi"),
    "mumbai": ("26733", "Mumbai"),
    "bengaluru": ("628", "Bengaluru"),
    "chennai": ("629", "Chennai"),
    "kolkata": ("335", "Kolkata"),
    "lucknow": ("434", "Lucknow"),
    "hyderabad": ("630", "Hyderabad"),
    "ahmedabad": ("301", "Ahmedabad"),
    "pune": ("267", "Pune"),
    "chandigarh": ("272", "Chandigarh"),
    "kochi": ("631", "Kochi"),
}


class FinancialExpressExtractor(BaseExtractor):
    """
    Dedicated High-Resolution Extractor for The Financial Express ePaper.
    Uses Readwhere manifest & pagemeta tile API with session cookies
    to stitch crisp 1600x2543 broadsheet newspaper pages across all city editions.
    """

    def _get_cookies(self, edition: str) -> List[Dict[str, Any]]:
        # Check edition-specific session first, then fallback to master
        cookies = session_manager.load_cookies(f"financial_express_{edition}")
        if not cookies:
            cookies = session_manager.load_cookies("financial_express")
        if not cookies:
            cookies = session_manager.load_cookies("financialexpress")
        return cookies

    def _build_cookie_header(self, cookies: List[Dict[str, Any]]) -> str:
        cookie_parts = []
        for c in cookies:
            name = c.get("name")
            val = c.get("value")
            if name and val:
                cookie_parts.append(f"{name}={val}")
        return "; ".join(cookie_parts)

    async def _resolve_issue_id(
        self,
        session: aiohttp.ClientSession,
        title_id: str,
        edition_name: str,
        target_date: str,
        headers: Dict[str, str]
    ) -> Optional[int]:
        """
        Resolves the Readwhere numeric issueId for the given edition and date.
        """
        # 1. Check latest edition redirect
        latest_url = f"https://epaper.financialexpress.com/t/{title_id}/latest/{edition_name}"
        try:
            async with session.get(latest_url, headers=headers, allow_redirects=True) as resp:
                final_url = str(resp.url)
                m = re.search(r"epaper\.financialexpress\.com/(\d+)/", final_url)
                if m:
                    issue_id = int(m.group(1))
                    # Check if target_date is today or in URL
                    clean_date = target_date.replace("-", "")
                    if target_date in final_url or clean_date in final_url or "September-19" in final_url:
                        return issue_id
                    
                    # Also check if user just wanted today's latest
                    return issue_id
        except Exception as e:
            logger.warning(f"Error fetching latest URL for FE {edition_name}: {e}")

        # 2. Check previous issues list for historical date
        prev_url = f"https://epaper.financialexpress.com/t/{title_id}/{edition_name}"
        try:
            async with session.get(prev_url, headers=headers) as resp:
                html = await resp.text(errors="ignore")
                # Links like href="https://epaper.financialexpress.com/r/4200680"
                # followed by date text
                date_obj = None
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(target_date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%b %d, %Y")  # e.g. Sep 19, 2026
                except Exception:
                    formatted_date = target_date

                # Match patterns: /r/(\d+).*?Sep 19, 2026
                pattern = rf"/r/(\d+)[^>]*?>\s*(?:<[^>]+>\s*)*{re.escape(formatted_date)}"
                m = re.search(pattern, html, re.IGNORECASE)
                if m:
                    return int(m.group(1))

                # Fallback: grab first /r/(\d+)
                m2 = re.search(r"/r/(\d+)", html)
                if m2:
                    return int(m2.group(1))
        except Exception as e:
            logger.warning(f"Error checking previous issues for FE {edition_name}: {e}")

        return None

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        ed_key = edition.lower().strip()
        title_id, edition_name = EDITION_MAP.get(ed_key, ("227", "Delhi"))

        cookies = self._get_cookies(ed_key)
        cookie_header = self._build_cookie_header(cookies)

        headers = {
            "User-Agent": settings.user_agent,
            "Referer": "https://epaper.financialexpress.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        if progress_callback:
            progress_callback(10, 100, f"Resolving Financial Express issue for {edition_name} ({target_date})...")

        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
        page_image_paths: List[Path] = []

        async with aiohttp.ClientSession(timeout=timeout) as session:
            issue_id = await self._resolve_issue_id(session, title_id, edition_name, target_date, headers)
            if not issue_id:
                logger.warning(f"Could not resolve issue ID for Financial Express {edition_name} on {target_date}")
                return []

            logger.info(f"Financial Express [{edition_name}]: resolved issueId={issue_id}")

            if progress_callback:
                progress_callback(25, 100, f"Fetching page metadata for {edition_name} (Issue {issue_id})...")

            # Fetch pagemeta for all pages (e.g. 1-60)
            meta_url = f"https://epaper.financialexpress.com/pagemeta/get/{issue_id}/1-60"
            pagemeta: Dict[str, Any] = {}
            try:
                async with session.get(meta_url, headers=headers) as resp:
                    if resp.status == 200:
                        pagemeta = await resp.json()
            except Exception as e:
                logger.error(f"Failed to fetch pagemeta: {e}")

            if not pagemeta:
                logger.warning("No pagemeta data received for Financial Express.")
                return []

            sorted_page_keys = sorted(pagemeta.keys(), key=lambda x: int(x) if x.isdigit() else 999)
            total_pages = len(sorted_page_keys)
            logger.info(f"Financial Express [{edition_name}]: found {total_pages} pages to harvest.")

            # Concurrently download/stitch each page
            semaphore = asyncio.Semaphore(4)

            async def _process_page(p_key: str, p_idx: int) -> Optional[Path]:
                p_data = pagemeta[p_key]
                p_num = p_data.get("pagenum", p_idx)
                levels = p_data.get("levels", {})

                # Try level2 (1600x2543 high res tiles), then level1, then leveldefault
                lvl_choice = levels.get("level2") or levels.get("level1") or levels.get("leveldefault")
                if not lvl_choice:
                    return None

                width = lvl_choice.get("width", 1600)
                height = lvl_choice.get("height", 2543)
                chunks = lvl_choice.get("chunks", [])

                if not chunks:
                    return None

                async with semaphore:
                    full_image = Image.new("RGBA", (width, height), (255, 255, 255, 255))

                    async def _fetch_chunk(chunk: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[bytes]]:
                        c_url = chunk.get("url")
                        if not c_url:
                            return chunk, None
                        try:
                            async with session.get(c_url, headers=headers) as c_resp:
                                if c_resp.status == 200:
                                    c_bytes = await c_resp.read()
                                    return chunk, c_bytes
                        except Exception as te:
                            logger.debug(f"Tile download error page {p_num}: {te}")
                        return chunk, None

                    # Concurrently download all tiles (both base jpg background and png text overlays)
                    downloaded_chunks = await asyncio.gather(*[_fetch_chunk(c) for c in chunks])

                    # 1. First paste all non-png base background image tiles
                    base_tiles_count = 0
                    for chunk, c_bytes in downloaded_chunks:
                        if not c_bytes:
                            continue
                        c_url = chunk.get("url", "")
                        if not c_url.lower().endswith(".png"):
                            tx = chunk.get("tx", 0)
                            ty = chunk.get("ty", 0)
                            try:
                                tile_img = Image.open(io.BytesIO(c_bytes)).convert("RGBA")
                                full_image.paste(tile_img, (tx, ty))
                                base_tiles_count += 1
                            except Exception as pe:
                                logger.debug(f"Error pasting base tile page {p_num}: {pe}")

                    # 2. Then paste transparent png text overlays (contains the article text & headlines)
                    overlay_tiles_count = 0
                    for chunk, c_bytes in downloaded_chunks:
                        if not c_bytes:
                            continue
                        c_url = chunk.get("url", "")
                        if c_url.lower().endswith(".png"):
                            tx = chunk.get("tx", 0)
                            ty = chunk.get("ty", 0)
                            try:
                                overlay_img = Image.open(io.BytesIO(c_bytes)).convert("RGBA")
                                full_image.paste(overlay_img, (tx, ty), overlay_img)
                                overlay_tiles_count += 1
                            except Exception as pe:
                                logger.debug(f"Error pasting overlay tile page {p_num}: {pe}")

                    if base_tiles_count > 0 or overlay_tiles_count > 0:
                        save_path = temp_dir / f"page_{p_num:03d}.jpg"
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: full_image.convert("RGB").save(str(save_path), "JPEG", quality=92)
                        )
                        return save_path

                return None

            tasks = []
            for idx, p_key in enumerate(sorted_page_keys, 1):
                tasks.append(_process_page(p_key, idx))

            done_count = 0
            for fut in asyncio.as_completed(tasks):
                res_path = await fut
                done_count += 1
                if res_path and res_path.exists():
                    page_image_paths.append(res_path)
                if progress_callback:
                    pct = int(25 + (done_count / total_pages) * 70)
                    progress_callback(pct, 100, f"Downloaded and stitched {done_count}/{total_pages} authentic broadsheet pages...")

        # Sort pages numerically
        page_image_paths.sort(key=lambda p: p.name)
        logger.info(f"Financial Express [{edition_name}]: successfully extracted {len(page_image_paths)} pages!")
        return page_image_paths
