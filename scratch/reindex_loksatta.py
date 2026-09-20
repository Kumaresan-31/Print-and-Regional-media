import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

import asyncio
from harvester.config import settings
from harvester.news.pdf_search_index import pdf_search_index

async def main():
    date_str = "2026-09-20"
    loksatta_pdf = settings.archive_dir / "loksatta" / date_str / "loksatta_pune_2026-09-20.pdf"
    if loksatta_pdf.exists():
        print(f"Indexing Loksatta ({loksatta_pdf.name}) with 4 broadsheet pages...")
        ok = await pdf_search_index.index_document(loksatta_pdf, "loksatta", date_str, force=True, max_pages=4)
        print(f"Indexing result: {ok}")
        stories = pdf_search_index.get_categorized_stories("loksatta", category="all", limit=10)
        print(f"Extracted {len(stories)} stories for Loksatta:")
        for i, s in enumerate(stories[:6]):
            print(f"[{i+1}] [{s.get('category').upper()}] Page {s.get('page_number')}")
            print(f"    EN Title: {s.get('title')}")
            print(f"    Orig: {s.get('original_title')}")
            print(f"    Snippet: {s.get('snippet')[:100]}...")

asyncio.run(main())
