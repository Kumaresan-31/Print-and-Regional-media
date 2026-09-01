import io
import logging
from pathlib import Path
from typing import List, Optional, Callable
import aiohttp
from pypdf import PdfReader, PdfWriter

from harvester.config import settings
from harvester.models import SourceConfig
from harvester.extractors.base import BaseExtractor
from harvester.registry import resolve_url
from harvester.auth.session_manager import session_manager

logger = logging.getLogger(__name__)


class DirectPdfExtractor(BaseExtractor):
    """
    Extractor for sources providing downloadable PDF files directly.
    """

    async def extract_pages(
        self,
        target_date: str,
        edition: str,
        temp_dir: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        """
        Extracts PDF pages directly by downloading the edition PDF and splitting pages to images.
        """
        target_url = resolve_url(self.source, target_date, edition)
        cookies = session_manager.get_cookie_dict(self.source.id)
        raw_pdf_path = temp_dir / "full_edition_raw.pdf"

        if progress_callback:
            progress_callback(15, 100, f"Downloading direct PDF from {target_url}...")

        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/pdf,*/*",
        }
        headers.update(self.source.headers)

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(target_url, headers=headers, cookies=cookies) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status} downloading PDF from {target_url}")
                
                content = await resp.read()
                with open(raw_pdf_path, "wb") as f:
                    f.write(content)

        if not raw_pdf_path.exists() or raw_pdf_path.stat().st_size < 10000:
            raise ValueError(f"Downloaded PDF from {target_url} is empty or invalid.")

        # Convert PDF pages to high-resolution JPEG images in temp_dir
        if progress_callback:
            progress_callback(50, 100, "Rendering PDF pages into high-res images...")

        image_paths: List[Path] = []
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(raw_pdf_path), dpi=150)
            for idx, img in enumerate(images):
                img_path = temp_dir / f"page_{idx + 1:03d}.jpg"
                img.save(img_path, "JPEG", quality=90)
                image_paths.append(img_path)
        except Exception as e:
            logger.warning(f"pdf2image render failed: {e}. Fallback to direct raw PDF copy.")
            # If pdf2image (poppler) is not installed, output the raw PDF directly
            dest_pdf = self.get_output_pdf_path(target_date, edition)
            raw_pdf_path.rename(dest_pdf)
            # Create a single placeholder path for base flow
            return []

        return image_paths
