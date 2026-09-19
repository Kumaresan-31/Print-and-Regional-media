import asyncio
import logging
import urllib.parse
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
import requests
from PIL import Image
import io

from playwright.async_api import async_playwright
from harvester.models import SourceConfig
from harvester.extractors.base import BaseExtractor
from harvester.auth.session_manager import session_manager
from harvester.config import settings

logger = logging.getLogger(__name__)


class DtNextExtractor(BaseExtractor):
    """
    Dedicated High-Fidelity Extractor for DT Next ePaper (news.dtnext.in).
    Uses Playwright with authenticated session cookies to interface with the
    PressReader engine, captures high-resolution vector page images, and compiles
    authentic full-broadsheet ePaper editions.
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        """
        Extracts all high-resolution pages for the specified date and edition.
        """
        clean_date = target_date.replace("-", "")
        target_url = f"https://news.dtnext.in/dt-next/{clean_date}"
        
        stored_cookies = session_manager.load_cookies(self.source.id)
        if not stored_cookies:
            # Fallback check for alias
            stored_cookies = session_manager.load_cookies("dtnext")

        page_image_paths: List[Path] = []
        page_keys: List[Dict[str, Any]] = []
        captured_image_urls: Dict[int, str] = {}
        issue_id: Optional[str] = None

        if progress_callback:
            progress_callback(10, 100, f"Connecting to DT Next authenticated portal ({target_date})...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )

            context = await browser.new_context(
                viewport={"width": settings.viewport_width, "height": settings.viewport_height},
                user_agent=settings.user_agent,
                device_scale_factor=2.0,
            )

            # Inject session cookies
            if stored_cookies:
                pw_cookies = []
                for c in stored_cookies:
                    entry = {
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", ""),
                        "path": c.get("path", "/"),
                    }
                    if "secure" in c:
                        entry["secure"] = c["secure"]
                    if "httpOnly" in c:
                        entry["httpOnly"] = c["httpOnly"]
                    pw_cookies.append(entry)
                try:
                    await context.add_cookies(pw_cookies)
                    logger.info(f"Injected {len(pw_cookies)} session cookies for DT Next.")
                except Exception as ce:
                    logger.warning(f"Could not inject DT Next cookies: {ce}")

            page = await context.new_page()

            # Intercept PressReader PageKeys and page image responses
            async def on_response(resp):
                nonlocal page_keys, issue_id
                u = resp.url
                if "GetPageKeys" in u and resp.status == 200:
                    try:
                        data = await resp.json()
                        keys = data.get("PageKeys", [])
                        if keys:
                            page_keys = keys
                            qs = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
                            iss = qs.get("issue", [None])[0]
                            if iss:
                                issue_id = iss
                            logger.info(f"Intercepted DT Next GetPageKeys: {len(page_keys)} pages for issue {issue_id}")
                    except Exception as e:
                        logger.debug(f"Error reading GetPageKeys: {e}")

                # Also capture direct page image URLs as backup
                if ("i.prcdn.co/img" in u or "t.prcdn.co/img" in u) and resp.status == 200:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
                    p_str = qs.get("page", [None])[0]
                    if p_str and p_str.isdigit():
                        p_num = int(p_str)
                        if p_num not in captured_image_urls or "scale=100" in u or "scale=150" in u:
                            captured_image_urls[p_num] = u

            page.on("response", on_response)

            if progress_callback:
                progress_callback(20, 100, f"Navigating to {target_url}...")

            logger.info(f"Navigating to DT Next: {target_url}")
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            except Exception as nav_err:
                logger.warning(f"Initial navigation error ({nav_err}), retrying base page...")
                await page.goto("https://news.dtnext.in/dt-next", wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)

            # Wait for PressReader engine to initialize and publish PageKeys
            for _ in range(24):
                if page_keys and issue_id:
                    break
                await asyncio.sleep(0.5)

            if progress_callback:
                progress_callback(40, 100, "Extracting authentic newspaper pages...")

            # 1. Download via PageKeys ticket URLs (Highest fidelity)
            if page_keys and issue_id:
                total_p = len(page_keys)
                logger.info(f"Downloading {total_p} authentic DT Next pages via ticket pipeline...")
                headers = {
                    "User-Agent": settings.user_agent,
                    "Referer": "https://news.dtnext.in/",
                }

                loop = asyncio.get_event_loop()

                def _download_page(pk: Dict[str, Any]) -> Optional[Path]:
                    p_num = pk.get("PageNumber", 1)
                    key = pk.get("Key", "")
                    ticket = urllib.parse.quote(key)
                    # Scale 100 or 150 delivers crisp 300 DPI text
                    img_url = f"https://i.prcdn.co/img?file={issue_id}&page={p_num}&scale=100&ticket={ticket}"
                    try:
                        r = requests.get(img_url, headers=headers, timeout=30)
                        if r.status_code == 200 and len(r.content) > 10000:
                            # Convert webp to high-quality JPEG/PNG for PyPDF stitcher
                            image = Image.open(io.BytesIO(r.content))
                            if image.mode != "RGB":
                                image = image.convert("RGB")
                            save_path = temp_dir / f"page_{p_num:02d}.jpg"
                            image.save(str(save_path), "JPEG", quality=95)
                            return save_path
                    except Exception as err:
                        logger.warning(f"Failed to download DT Next page {p_num}: {err}")
                    return None

                for idx, pk in enumerate(page_keys, 1):
                    if progress_callback:
                        progress_callback(
                            int(40 + (idx / total_p) * 50),
                            100,
                            f"Downloading authentic page {idx} of {total_p}..."
                        )
                    saved = await loop.run_in_executor(None, _download_page, pk)
                    if saved and saved.exists():
                        page_image_paths.append(saved)

            # 2. Fallback: If PageKeys ticket download didn't run, check captured URLs
            if not page_image_paths and captured_image_urls:
                logger.info(f"Using {len(captured_image_urls)} captured image URLs fallback...")
                sorted_pages = sorted(captured_image_urls.keys())
                for idx, p_num in enumerate(sorted_pages, 1):
                    img_url = captured_image_urls[p_num]
                    try:
                        r = requests.get(img_url, headers={"User-Agent": settings.user_agent, "Referer": "https://news.dtnext.in/"}, timeout=30)
                        if r.status_code == 200:
                            image = Image.open(io.BytesIO(r.content))
                            if image.mode != "RGB":
                                image = image.convert("RGB")
                            save_path = temp_dir / f"page_{p_num:02d}.jpg"
                            image.save(str(save_path), "JPEG", quality=95)
                            page_image_paths.append(save_path)
                    except Exception as fb_err:
                        logger.warning(f"Fallback download error for page {p_num}: {fb_err}")

            await context.close()
            await browser.close()

        if page_image_paths:
            logger.info(f"Successfully harvested {len(page_image_paths)} genuine DT Next newspaper pages!")
        else:
            logger.warning("Could not extract DT Next pages from PressReader portal.")

        return page_image_paths
