import sys
sys.path.insert(0, 'backend')
import asyncio
import time
from pathlib import Path
from harvester.news.pdf_parser import pdf_news_parser

async def main():
    pdf_path = Path('data/archive/financial_express/2026-09-19/financial_express_delhi_2026-09-19.pdf')
    print("Testing parse_and_process_pdf with max_pages=4...")
    t0 = time.time()
    res = await pdf_news_parser.parse_and_process_pdf(pdf_path, source_name="The Financial Express", max_pages=4)
    dt = time.time() - t0
    print(f"4 pages took {dt:.2f}s, extracted {res.get('total_articles')} articles, doc_id: {res.get('doc_id')}")

asyncio.run(main())
