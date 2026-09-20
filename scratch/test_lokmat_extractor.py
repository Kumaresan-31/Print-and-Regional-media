import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from harvester.extractors.engines.manifest_api import ManifestApiExtractor
from harvester.registry import get_source
import requests, asyncio

async def test():
    source = get_source("lokmat")
    extractor = ManifestApiExtractor(source=source)
    resp = requests.get("https://epaper.lokmat.com/articlepage.php?catid=1&eddate=2026-09-20", timeout=15)
    imgs = await extractor.discover_page_images(resp.text, "https://epaper.lokmat.com", "2026-09-20", "pune")
    print("Found images count:", len(imgs))
    for img in imgs[:5]:
        print("Image:", img)

asyncio.run(test())
