import asyncio
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from harvester.news.pdf_search_index import pdf_search_index

async def main():
    fe_pdf = Path("data/archive/financial_express/2026-09-19/financial_express_delhi_2026-09-19.pdf")
    print(f"Indexing Financial Express: {fe_pdf} (size: {fe_pdf.stat().st_size / 1024 / 1024:.2f} MB)...")
    t0 = time.time()
    res = await pdf_search_index.index_document(fe_pdf, "financial_express", "2026-09-19", force=False)
    print(f"Financial Express indexed: {res} in {time.time() - t0:.2f}s")

    lok_pdf = Path("data/archive/loksatta/2026-09-19/loksatta_mumbai_2026-09-19.pdf")
    print(f"\nIndexing Loksatta: {lok_pdf} (size: {lok_pdf.stat().st_size / 1024 / 1024:.2f} MB)...")
    t0 = time.time()
    res = await pdf_search_index.index_document(lok_pdf, "loksatta", "2026-09-19", force=True)
    print(f"Loksatta indexed: {res} in {time.time() - t0:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
