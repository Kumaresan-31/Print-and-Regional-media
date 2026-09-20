import sys, os, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

import asyncio
from harvester.config import settings
from harvester.news.pdf_search_index import pdf_search_index
from harvester.news.pdf_parser import pdf_news_parser

async def main():
    date_str = "2026-09-20"
    loksatta_pdf = settings.archive_dir / "loksatta" / date_str / "loksatta_pune_2026-09-20.pdf"
    print(f"Testing Loksatta indexing for: {loksatta_pdf}")
    t0 = time.time()
    # Let's index with max_pages=6 first to see speed and output
    result = await pdf_news_parser.parse_and_process_pdf(
        file_path=loksatta_pdf,
        source_name="Loksatta",
        max_pages=2
    )
    t1 = time.time()
    print(f"Parsing 6 pages completed in {t1-t0:.2f}s")
    stories = result.get("categories", {}).get("all", [])
    print(f"Total articles extracted: {len(stories)}")
    for i, s in enumerate(stories[:5]):
        print(f"[{i+1}] Title (EN): {s.get('title')}")
        print(f"    Category: {s.get('category')}")
        print(f"    Orig lang: {s.get('original_language')}")
        print(f"    Orig title: {s.get('original_title')}")

asyncio.run(main())
