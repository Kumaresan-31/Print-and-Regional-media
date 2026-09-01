import os
import io
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from PIL import Image
import aiohttp
from pypdf import PdfWriter, PdfReader

from harvester.config import settings

logger = logging.getLogger(__name__)


class ImageStitcher:
    """
    Downloads newspaper page images concurrently and stitches them into
    high-resolution, optimized multi-page PDFs with bookmarks and metadata.
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        max_workers: int = settings.max_page_download_workers,
        timeout_seconds: int = settings.http_timeout_seconds
    ):
        self.output_dir = output_dir or settings.archive_dir
        self.max_workers = max_workers
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def download_page(
        self,
        session: aiohttp.ClientSession,
        url: str,
        page_num: int,
        temp_dir: Path,
        headers: Optional[Dict[str, str]] = None,
        retries: int = 3
    ) -> Optional[Path]:
        """
        Downloads a single newspaper page with retry backoff.
        """
        dest_path = temp_dir / f"page_{page_num:03d}.jpg"
        if dest_path.exists() and dest_path.stat().st_size > 1000:
            return dest_path

        req_headers = {
            "User-Agent": settings.user_agent,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://google.com/",
        }
        if headers:
            req_headers.update(headers)

        for attempt in range(1, retries + 1):
            try:
                async with session.get(url, headers=req_headers, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        if len(content) > 1024:  # At least 1KB
                            # Validate image can be opened by PIL
                            with Image.open(io.BytesIO(content)) as img:
                                img.verify()
                            with open(dest_path, "wb") as f:
                                f.write(content)
                            return dest_path
                        else:
                            logger.warning(f"Page {page_num} returned empty payload ({len(content)} bytes)")
                    elif resp.status in (403, 404):
                        logger.warning(f"Page {page_num} HTTP {resp.status} on {url}")
                        if attempt == retries:
                            return None
            except Exception as e:
                logger.warning(f"Download attempt {attempt} failed for page {page_num}: {e}")
                if attempt < retries:
                    await asyncio.sleep(1.5 * attempt)

        return None

    async def download_all_pages(
        self,
        image_urls: List[str],
        temp_dir: Path,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Path]:
        """
        Concurrently downloads all page images.
        """
        temp_dir.mkdir(parents=True, exist_ok=True)
        downloaded_paths: List[Optional[Path]] = [None] * len(image_urls)
        semaphore = asyncio.Semaphore(self.max_workers)
        total = len(image_urls)
        completed_count = 0

        cookie_jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=cookie_jar) as session:
            if cookies:
                session.cookie_jar.update_cookies(cookies)

            async def _worker(idx: int, url: str):
                nonlocal completed_count
                async with semaphore:
                    page_path = await self.download_page(
                        session=session,
                        url=url,
                        page_num=idx + 1,
                        temp_dir=temp_dir,
                        headers=headers
                    )
                    downloaded_paths[idx] = page_path
                    completed_count += 1
                    if progress_callback:
                        progress_callback(
                            completed_count,
                            total,
                            f"Downloaded page {completed_count}/{total}"
                        )

            tasks = [_worker(i, url) for i, url in enumerate(image_urls)]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successfully downloaded paths in order
        valid_paths = [p for p in downloaded_paths if p is not None and p.exists()]
        return valid_paths

    def assemble_pdf(
        self,
        page_image_paths: List[Path],
        output_pdf_path: Path,
        title: str,
        author: str = "ePaper Harvester",
        generate_thumbnail: bool = True
    ) -> Optional[Path]:
        """
        Stitches page images into a single multi-page PDF with table of contents/bookmarks.
        """
        if not page_image_paths:
            logger.error("Cannot assemble PDF: No valid page images provided.")
            return None

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        temp_raw_pdf = output_pdf_path.parent / f"temp_{output_pdf_path.name}"

        # 1. Convert images to PDF using Pillow
        images = []
        try:
            first_image = None
            for p in page_image_paths:
                img = Image.open(p)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                if first_image is None:
                    first_image = img
                else:
                    images.append(img)

            if first_image:
                first_image.save(
                    temp_raw_pdf,
                    "PDF",
                    resolution=150.0,
                    save_all=True,
                    append_images=images,
                    quality=85,
                    optimize=True
                )
        except Exception as e:
            logger.error(f"Failed to stitch images via Pillow: {e}")
            if temp_raw_pdf.exists():
                temp_raw_pdf.unlink(missing_ok=True)
            return None

        # 2. Add Bookmarks, Outline, and Metadata using PyPDF
        try:
            reader = PdfReader(str(temp_raw_pdf))
            writer = PdfWriter()

            for i, page in enumerate(reader.pages):
                writer.add_page(page)
                # Add bookmark per page
                outline_title = f"Page {i + 1}"
                if i == 0:
                    outline_title = "Page 1: Front Page"
                writer.add_outline_item(outline_title, i)

            # Metadata
            writer.add_metadata({
                "/Title": title,
                "/Author": author,
                "/Subject": f"Daily Newspaper Edition - {title}",
                "/Producer": "Automated ePaper Harvester 2.0",
                "/Creator": "Automated ePaper Harvester",
            })

            with open(output_pdf_path, "wb") as f_out:
                writer.write(f_out)

            # Clean up temp
            if temp_raw_pdf.exists():
                temp_raw_pdf.unlink(missing_ok=True)

            logger.info(f"Successfully compiled PDF: {output_pdf_path} ({len(page_image_paths)} pages, {output_pdf_path.stat().st_size / 1024 / 1024:.2f} MB)")

            # 3. Generate front-page thumbnail
            if generate_thumbnail and page_image_paths:
                thumb_path = output_pdf_path.with_suffix(".thumb.jpg")
                try:
                    with Image.open(page_image_paths[0]) as thumb_img:
                        thumb_img.thumbnail((320, 480))
                        thumb_img.save(thumb_path, "JPEG", quality=85)
                except Exception as ex:
                    logger.warning(f"Failed to generate thumbnail: {ex}")

            return output_pdf_path

        except Exception as e:
            logger.error(f"Failed to post-process PDF with PyPDF: {e}")
            # If PyPDF fails, fallback to keeping temp_raw_pdf
            if temp_raw_pdf.exists():
                temp_raw_pdf.rename(output_pdf_path)
                return output_pdf_path
            return None
