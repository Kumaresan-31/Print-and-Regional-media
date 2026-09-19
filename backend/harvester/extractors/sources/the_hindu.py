import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
import requests

from harvester.models import SourceConfig
from harvester.extractors.engines.browser_engine import BrowserFlipbookExtractor
from harvester.auth.session_manager import session_manager

logger = logging.getLogger(__name__)

EDITION_MAP = {
    "chennai": "th_chennai",
    "delhi": "th_delhi",
    "bengaluru": "th_bangalore",
    "bangalore": "th_bangalore",
    "mumbai": "th_mumbai",
    "hyderabad": "th_hyderabad",
    "coimbatore": "th_coimbatore",
    "madurai": "th_madurai",
    "kolkata": "th_kolkata",
    "national": "th_international",
    "international": "th_international",
}


class TheHinduExtractor(BrowserFlipbookExtractor):
    """
    Dedicated Extractor for The Hindu ePaper.
    Primary extraction uses the fast high-fidelity CCI Distribution API.
    Gracefully falls back to the Playwright stealth flipbook reader.
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        cookies = session_manager.get_cookie_dict(self.source.id)
        if not cookies:
            logger.info(
                "Notice: Running The Hindu extractor without saved session cookies. "
                "Import The Hindu subscription cookies via the dashboard for complete access."
            )

        if progress_callback:
            progress_callback(10, 100, "Checking The Hindu ePaper manifest...")

        # 1. Attempt High-Fidelity API page retrieval
        try:
            loop = asyncio.get_event_loop()
            page_paths = await loop.run_in_executor(
                None,
                self._extract_via_cci_api,
                target_date,
                edition,
                cookies,
                temp_dir,
                progress_callback
            )
            if page_paths and len(page_paths) > 0:
                logger.info(f"Successfully extracted {len(page_paths)} authentic pages for The Hindu via CCI API.")
                return page_paths
        except Exception as e:
            logger.warning(f"The Hindu CCI API extraction skipped: {e}. Falling back to Browser Flipbook engine...")

        # 2. Fallback to Browser Flipbook reader
        if progress_callback:
            progress_callback(20, 100, "Launching browser reader session for The Hindu...")
        return await super().extract_pages(target_date, edition, temp_dir, progress_callback)

    def _extract_via_cci_api(
        self,
        target_date: str,
        edition: str,
        cookies: Dict[str, str],
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Referer": "https://epaper.thehindu.com/reader",
            "Accept": "application/json, text/plain, */*",
        }

        # Match publication code
        pub_id = EDITION_MAP.get(edition.lower(), f"th_{edition.lower()}")

        # 1. Discover active issue
        list_url = (
            f"https://epaper.thehindu.com/ccidist-ws/th/?json=true"
            f"&fromDate={target_date}&toDate={target_date}&skipSections=true&os=web"
        )
        resp = requests.get(list_url, cookies=cookies, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise ValueError(f"Issue catalog returned HTTP {resp.status_code}")

        data = resp.json()
        publications = data.get("publications", [])

        # Find requested publication or fall back to national/international
        target_pub = None
        for p in publications:
            if p.get("id") == pub_id:
                target_pub = p
                break

        if not target_pub and pub_id != "th_international":
            for p in publications:
                if p.get("id") == "th_international":
                    target_pub = p
                    pub_id = "th_international"
                    break

        if not target_pub and publications:
            target_pub = publications[0]
            pub_id = target_pub.get("id")

        if not target_pub:
            raise ValueError(f"No active publication found for {edition} on {target_date}")

        issues = target_pub.get("issues", {}).get("web", [])
        if not issues:
            raise ValueError(f"No web issue found for publication {pub_id}")

        issue_id = issues[0].get("id")
        logger.info(f"Targeting The Hindu issue {issue_id} ({pub_id}) for {target_date}")

        # 2. Fetch page list from manifest
        manifest_url = f"https://epaper.thehindu.com/ccidist-ws/th/{pub_id}/issues/{issue_id}/OPS/cciobjects.json"
        m_resp = requests.get(manifest_url, cookies=cookies, headers=headers, timeout=20)
        if m_resp.status_code != 200:
            raise ValueError(f"cciobjects.json returned HTTP {m_resp.status_code}")

        manifest = m_resp.json()
        pages = [c for c in manifest.get("children", []) if c.get("kind") == "Page"]
        if not pages:
            raise ValueError(f"No pages declared in manifest for issue {issue_id}")

        total_pages = len(pages)
        logger.info(f"Discovered {total_pages} pages for The Hindu {pub_id}")
        page_paths: List[Path] = []

        base_ops_url = f"https://epaper.thehindu.com/ccidist-ws/th/{pub_id}/issues/{issue_id}/OPS/"

        for idx, page in enumerate(pages):
            page_num = idx + 1
            if progress_callback:
                progress_callback(
                    int(20 + (page_num / total_pages) * 70),
                    100,
                    f"Downloading The Hindu page {page_num} of {total_pages}..."
                )

            resources = page.get("resources", {})
            # Rank available resource keys by preferred quality
            resource_keys = list(resources.keys())
            candidate_keys = []

            # 1st priority: background-2048 (Full-DPI original page render)
            for k in resource_keys:
                if "background-2048" in k or "background" in k:
                    candidate_keys.append(k)
            # 2nd priority: medium-900 (High-res preview)
            for k in resource_keys:
                if "medium-900" in k:
                    candidate_keys.append(k)
            # 3rd priority: small-500 or thumbnail-284 (Public preview)
            for k in resource_keys:
                if "small-500" in k or "thumbnail-284" in k:
                    candidate_keys.append(k)

            page_saved = False
            for k in candidate_keys:
                img_url = base_ops_url + k
                try:
                    img_resp = requests.get(img_url, cookies=cookies, headers=headers, timeout=25, allow_redirects=False)
                    # If 307 redirect, it is restricted to paid subscribers; continue to next fallback candidate
                    if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                        ct = img_resp.headers.get("content-type", "").lower()
                        ext = ".png" if "png" in ct or k.endswith(".png") else ".jpg"
                        dest = temp_dir / f"page_{page_num:03d}{ext}"
                        with open(dest, "wb") as f:
                            f.write(img_resp.content)
                        page_paths.append(dest)
                        page_saved = True
                        break
                except Exception as ex:
                    logger.debug(f"Failed downloading {img_url}: {ex}")

            if not page_saved:
                logger.warning(f"Could not download page {page_num} for The Hindu {pub_id}")

        return page_paths
