import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import asyncio
from harvester.config import settings
from harvester.news.pdf_search_index import pdf_search_index

async def main():
    date_str = "2026-09-20"
    
    # 1. Lokmat
    lokmat_pdf = settings.archive_dir / "lokmat" / date_str / "lokmat_pune_2026-09-20.pdf"
    if lokmat_pdf.exists():
        print(f"Indexing Lokmat: {lokmat_pdf}...")
        ok = await pdf_search_index.index_document(lokmat_pdf, "lokmat", date_str, force=True)
        print("Lokmat indexed:", ok)
        stories = pdf_search_index.get_categorized_stories("lokmat", limit=5)
        print(f"Lokmat stories found: {len(stories)}")
        for s in stories[:3]:
            print("  Title (EN):", s.get("title"))
            print("  Category:", s.get("category"))
            print("  Orig title:", s.get("original_title"))

    # 2. Loksatta
    loksatta_pdf = settings.archive_dir / "loksatta" / date_str / "loksatta_pune_2026-09-20.pdf"
    if loksatta_pdf.exists():
        # Clear old snapshot boxes so Tesseract Marathi OCR runs
        import hashlib
        doc_id = hashlib.md5(f"{loksatta_pdf.name}_{loksatta_pdf.stat().st_mtime}".encode()).hexdigest()[:12]
        snap_dir = settings.snapshots_dir / doc_id
        if snap_dir.exists():
            for bf in snap_dir.glob("*.boxes.json"):
                try:
                    bf.unlink()
                except Exception:
                    pass
        print(f"Indexing Loksatta: {loksatta_pdf}...")
        ok = await pdf_search_index.index_document(loksatta_pdf, "loksatta", date_str, force=True)
        print("Loksatta indexed:", ok)
        stories = pdf_search_index.get_categorized_stories("loksatta", limit=5)
        print(f"Loksatta stories found: {len(stories)}")
        for s in stories[:3]:
            print("  Title (EN):", s.get("title"))
            print("  Category:", s.get("category"))
            print("  Orig title:", s.get("original_title"))

asyncio.run(main())
