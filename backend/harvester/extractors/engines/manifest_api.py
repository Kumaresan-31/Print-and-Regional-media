import re
import json
import logging
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
from bs4 import BeautifulSoup
import aiohttp

from harvester.config import settings
from harvester.models import SourceConfig
from harvester.extractors.base import BaseExtractor
from harvester.registry import resolve_url
from harvester.auth.session_manager import session_manager

logger = logging.getLogger(__name__)


class ManifestApiExtractor(BaseExtractor):
    """
    Extractor for ePapers that provide or embed page manifests (JSON / HTML attributes).
    Fast, concurrent, lightweight, and bypasses heavyweight browser rendering.
    """

    async def discover_page_images(
        self,
        html_or_json: str,
        base_page_url: str,
        target_date: str,
        edition: str
    ) -> List[str]:
        """
        Heuristic discovery of page image URLs from manifest responses or embedded states.
        """
        urls: List[str] = []
        parts = target_date.split("-")
        year, month, day = parts[0], parts[1], parts[2]

        # 1. Try parsing JSON directly
        try:
            data = json.loads(html_or_json)
            if isinstance(data, dict):
                # Search for pages list
                for key in ["pages", "Pages", "pageList", "items", "data"]:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            if isinstance(item, dict):
                                img_url = item.get("highResImage") or item.get("imageUrl") or item.get("src") or item.get("large") or item.get("image") or item.get("PageImage")
                                if img_url and isinstance(img_url, str):
                                    urls.append(img_url)
                            elif isinstance(item, str) and (item.endswith(".jpg") or item.endswith(".png") or item.endswith(".webp")):
                                urls.append(item)
            if urls:
                return urls
        except json.JSONDecodeError:
            pass

        # 2. Look for JSON embedded in script tags (e.g. window.__INITIAL_STATE__, editionData, pages)
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'var\s+editionData\s*=\s*({.*?});',
            r'var\s+pages\s*=\s*(\[.*?\]);',
            r'pageImages\s*:\s*(\[.*?\])',
            r'\"pages\":\s*(\[.*?\])',
        ]
        for pat in patterns:
            match = re.search(pat, html_or_json, re.DOTALL)
            if match:
                try:
                    payload = json.loads(match.group(1))
                    if isinstance(payload, list):
                        for p in payload:
                            if isinstance(p, str) and ("http" in p):
                                urls.append(p)
                            elif isinstance(p, dict):
                                val = p.get("src") or p.get("image") or p.get("highRes") or p.get("large") or p.get("url")
                                if val:
                                    urls.append(val)
                    elif isinstance(payload, dict):
                        # Deep search in dict for image urls
                        def _find_urls(d):
                            if isinstance(d, dict):
                                for k, v in d.items():
                                    if k in ["large", "highRes", "imageUrl", "pageImage", "src"] and isinstance(v, str) and v.startswith("http"):
                                        urls.append(v)
                                    else:
                                        _find_urls(v)
                            elif isinstance(d, list):
                                for elem in d:
                                    _find_urls(elem)
                        _find_urls(payload)
                except Exception:
                    pass
                if urls:
                    return list(dict.fromkeys(urls))

        # 3. HTML parsing: look for high-res img tags or zoom canvas data
        soup = BeautifulSoup(html_or_json, "html.parser")

        # Find img tags with data-highres, data-large, data-src, or src
        for img in soup.find_all("img"):
            candidate = img.get("data-highres") or img.get("data-large") or img.get("data-src") or img.get("data-original")
            if not candidate and img.get("src"):
                src = img.get("src")
                if "page" in src.lower() or "edition" in src.lower() or "epaper" in src.lower():
                    candidate = src
            if candidate and candidate.startswith("http") and not candidate.endswith(".svg"):
                urls.append(candidate)

        # 4. Fallback pattern: predictable CDN structure with standard sequence
        if not urls:
            # Common pattern for several Indian regional publishers:
            # e.g., https://epapercdn.example.com/{edition}/{year}/{month}/{day}/page_{1..N}.jpg
            logger.info("Manifest not explicitly found, checking for dynamic sequence pattern")

        return list(dict.fromkeys(urls))

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        """
        Executes manifest fetching and concurrent page download.
        """
        target_url = resolve_url(self.source, target_date, edition)
        cookies = session_manager.get_cookie_dict(f"{self.source.id}_{edition}")
        if not cookies:
            cookies = session_manager.get_cookie_dict(self.source.id)

        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": self.source.base_url,
        }
        headers.update(self.source.headers)

        if progress_callback:
            progress_callback(10, 100, f"Fetching edition manifest from {target_url}...")

        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(target_url, headers=headers, cookies=cookies) as resp:
                    if resp.status != 200:
                        logger.warning(f"Manifest URL returned status {resp.status}")
                    content_text = await resp.text(errors="ignore")
            except Exception as e:
                logger.error(f"Failed to fetch manifest from {target_url}: {e}")
                raise RuntimeError(f"Failed to load edition page: {e}")

        # Extract page image URLs
        image_urls = await self.discover_page_images(content_text, target_url, target_date, edition)
        
        # If discovery found pages, download them
        if image_urls:
            if progress_callback:
                progress_callback(20, 100, f"Found {len(image_urls)} pages. Downloading images...")
            
            paths = await self.stitcher.download_all_pages(
                image_urls=image_urls,
                temp_dir=temp_dir,
                headers=headers,
                cookies=cookies,
                progress_callback=progress_callback
            )
            return paths

        # If zero discovered via manifest, throw informative error for fallback
        raise ValueError(f"Could not discover page images from {target_url}")
