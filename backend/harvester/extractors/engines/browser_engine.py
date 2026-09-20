import asyncio
import base64
import logging
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from harvester.config import settings
from harvester.models import SourceConfig
from harvester.extractors.base import BaseExtractor
from harvester.registry import resolve_url
from harvester.auth.session_manager import session_manager
from harvester.captcha.solver import captcha_solver

logger = logging.getLogger(__name__)


class BrowserFlipbookExtractor(BaseExtractor):
    """
    Playwright-based stealth extractor for dynamic SPA flipbooks, HTML5 canvas viewers,
    and paywalled ePaper portals (e.g. TOI PressDisplay, The Hindu, Readwhere).
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        """
        Launches Playwright headless browser, injects cookies/stealth, and captures pages.
        """
        target_url = resolve_url(self.source, target_date, edition)
        page_image_paths: List[Path] = []
        captured_urls: List[str] = []

        if progress_callback:
            progress_callback(10, 100, "Launching stealth browser session...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ]
            )

            context = await browser.new_context(
                viewport={"width": settings.viewport_width, "height": settings.viewport_height},
                user_agent=settings.user_agent,
                accept_downloads=True,
                device_scale_factor=2.0,  # High-DPI capture
            )

            # 1. Apply stealth script
            await context.add_init_script(captcha_solver.get_stealth_scripts())

            # 2. Inject stored session cookies if available
            stored_cookies = session_manager.load_cookies(f"{self.source.id}_{edition}")
            if not stored_cookies:
                stored_cookies = session_manager.load_cookies(self.source.id)
            if stored_cookies:
                pw_cookies = []
                for c in stored_cookies:
                    cookie_entry = {
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", ""),
                        "path": c.get("path", "/"),
                    }
                    if "secure" in c:
                        cookie_entry["secure"] = c["secure"]
                    if "httpOnly" in c:
                        cookie_entry["httpOnly"] = c["httpOnly"]
                    pw_cookies.append(cookie_entry)
                try:
                    await context.add_cookies(pw_cookies)
                    logger.info(f"Injected {len(pw_cookies)} session cookies into browser context.")
                except Exception as e:
                    logger.warning(f"Could not inject cookies: {e}")

            page = await context.new_page()

            # 3. Intercept high-resolution page image requests
            async def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "").lower()
                    if "image" in ct and response.status == 200:
                        url = response.url.lower()
                        # Filter candidate newspaper page images (large dimensions / page naming)
                        if any(term in url for term in ["page", "edition", "epaper", "article", "render"]):
                            if url not in captured_urls:
                                captured_urls.append(response.url)
                except Exception:
                    pass

            page.on("response", handle_response)

            if progress_callback:
                progress_callback(20, 100, f"Navigating to {target_url}...")

            try:
                resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
                await page.wait_for_timeout(3000)  # Allow initial JS flipbook to boot

                # 1. Check HTTP response status
                if resp and resp.status in (404, 403, 500, 502, 503):
                    raise ValueError(f"Portal returned HTTP {resp.status} for {target_url}")

                # 2. Check title and body for 404/invalid portal errors
                title = (await page.title() or "").lower()
                if "404" in title or "not found" in title:
                    raise ValueError(f"Portal returned 404 page: {title}")

                try:
                    body_snippet = (await page.inner_text("body") or "")[:400].lower()
                    if "404 not found" in body_snippet or "address is invalid" in body_snippet or "page not found" in body_snippet:
                        raise ValueError(f"Portal error page detected: {body_snippet[:80]}")
                except Exception as b_ex:
                    if "error page detected" in str(b_ex):
                        raise b_ex

                # Check for auth redirect or login required
                current_url = page.url
                if "login" in current_url.lower() or "signin" in current_url.lower():
                    logger.warning(f"Source {self.source.name} redirected to login page: {current_url}")
                    if self.source.auth_required and not stored_cookies:
                        raise PermissionError(
                            f"Authentication required for {self.source.name}. "
                            f"Please import cookies via the Web Dashboard."
                        )

                # Check for Cloudflare or Captcha challenge in page title
                if "Just a moment..." in title or "Cloudflare" in title or "Attention Required" in title:
                    logger.warning("Bot challenge detected on page. Waiting for stealth bypass...")
                    await page.wait_for_timeout(5000)

                # 4. Flip through pages or extract canvases
                # Detect total page count if available in DOM
                page_count = await self._detect_page_count(page)
                logger.info(f"Detected page count for {self.source.name}: {page_count}")

                max_pages = min(page_count, 48)  # Cap at reasonable max
                for idx in range(1, max_pages + 1):
                    if progress_callback:
                        progress_callback(
                            int(20 + (idx / max_pages) * 60),
                            100,
                            f"Capturing page {idx} of {max_pages}..."
                        )

                    # Try extracting high-res canvas or image element
                    saved_path = await self._capture_current_page(page, idx, temp_dir)
                    if saved_path:
                        page_image_paths.append(saved_path)

                    # Navigate to next page (simulate PageDown or click next button)
                    has_next = await self._advance_to_next_page(page)
                    if not has_next and idx >= 4:
                        break

                    await page.wait_for_timeout(1200)

            except Exception as e:
                logger.error(f"Browser navigation/capture error: {e}")
                # Save screenshot of error page for debugging
                err_screenshot = temp_dir / "error_page.png"
                await page.screenshot(path=str(err_screenshot))
                if not page_image_paths:
                    raise e
            finally:
                await context.close()
                await browser.close()

        return page_image_paths

    async def _detect_page_count(self, page: Page) -> int:
        """
        Attempts to read page count from typical UI selectors (e.g. '1 / 24', dropdowns).
        """
        try:
            # Check for dropdown options
            options_count = await page.evaluate("""() => {
                const select = document.querySelector('select.page-select, select#pageSelect, select[name="page"]');
                if (select && select.options) return select.options.length;
                const textElems = Array.from(document.querySelectorAll('span, div, p'));
                for (const el of textElems) {
                    const match = el.innerText.match(/\\/\\s*(\\d{1,2})\\b/);
                    if (match && parseInt(match[1]) > 3 && parseInt(match[1]) < 64) {
                        return parseInt(match[1]);
                    }
                }
                return 16;
            }""")
            if options_count and options_count > 0:
                return options_count
        except Exception:
            pass
        return 16  # sensible default

    async def _capture_current_page(self, page: Page, page_num: int, temp_dir: Path) -> Optional[Path]:
        """
        Captures the newspaper page view: first tries HTML5 canvas export,
        then the main reader element, or full viewport.
        """
        dest_path = temp_dir / f"page_{page_num:03d}.jpg"

        # 1. Try extracting from canvas if reader uses Canvas flipbook
        try:
            canvas_data = await page.evaluate("""() => {
                const canvases = Array.from(document.querySelectorAll('canvas'));
                if (canvases.length > 0) {
                    // Find largest canvas
                    let best = canvases[0];
                    let maxArea = best.width * best.height;
                    for (const c of canvases) {
                        const area = c.width * c.height;
                        if (area > maxArea) {
                            maxArea = area;
                            best = c;
                        }
                    }
                    if (maxArea > 200000) {
                        return best.toDataURL('image/jpeg', 0.92);
                    }
                }
                return null;
            }""")

            if canvas_data and canvas_data.startswith("data:image"):
                header, b64_data = canvas_data.split(",", 1)
                img_bytes = base64.b64decode(b64_data)
                with open(dest_path, "wb") as f:
                    f.write(img_bytes)
                return dest_path
        except Exception as ex:
            logger.debug(f"Canvas extraction skipped: {ex}")

        # 2. Try screenshotting the main reader container element
        selectors = [
            ".page-container",
            "#pageContainer",
            ".newspaper-page",
            ".edition-page",
            ".viewer-container",
            "#flipbook",
            ".main-content",
        ]
        for sel in selectors:
            try:
                elem = await page.query_selector(sel)
                if elem:
                    await elem.screenshot(path=str(dest_path), quality=90, type="jpeg")
                    if dest_path.stat().st_size > 10000:
                        return dest_path
            except Exception:
                continue

        # 3. Fallback: screenshot viewport
        try:
            await page.screenshot(path=str(dest_path), quality=88, type="jpeg")
            return dest_path
        except Exception as e:
            logger.error(f"Failed to screenshot page {page_num}: {e}")
            return None

    async def _advance_to_next_page(self, page: Page) -> bool:
        """
        Advances the flipbook to the next page.
        """
        # Try keyboard Right arrow
        try:
            await page.keyboard.press("ArrowRight")
            return True
        except Exception:
            pass

        # Try next button selectors
        next_selectors = [
            "button.next",
            ".btn-next",
            "a.next",
            "#nextPage",
            "[aria-label='Next page']",
            "[title='Next']",
        ]
        for sel in next_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    return True
            except Exception:
                continue

        return False
