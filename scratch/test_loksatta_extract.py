import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'd:/Projects/VEE2/backend')

from harvester.registry import get_source
from harvester.extractors.sources.loksatta import LoksattaExtractor
from harvester.config import settings

async def test_extract_sample():
    src = get_source("loksatta")
    extractor = LoksattaExtractor(src)
    temp_dir = Path("d:/Projects/VEE2/data/temp/test_loksatta")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    print("Testing issue resolution and page 1 metadata fetch...")
    # Test on target_date 2026-09-19 edition mumbai
    pages = await extractor.extract_pages(
        target_date="2026-09-19",
        edition="mumbai",
        temp_dir=temp_dir,
        progress_callback=lambda p, t, msg: print(f"[{p}%] {msg}")
    )
    print(f"Extraction result: {len(pages)} pages extracted!")
    if pages:
        first_page = pages[0]
        print(f"Page 1: {first_page}, size: {first_page.stat().st_size} bytes")
        from PIL import Image
        img = Image.open(first_page)
        print(f"Page 1 dimensions: {img.size}, mode: {img.mode}")

if __name__ == "__main__":
    asyncio.run(test_extract_sample())
