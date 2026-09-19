import asyncio
import json
import time
from pathlib import Path
from harvester.news.pdf_parser import pdf_news_parser

async def main():
    t0 = time.time()
    pdf_path = Path("harvester/news sample.pdf")
    print(f"Reading: {pdf_path} (size: {pdf_path.stat().st_size} bytes)")
    res = await pdf_news_parser.parse_and_process_pdf(pdf_path, "News Sample", max_pages=16)
    duration = time.time() - t0
    print(f"Completed in {duration:.1f}s")
    print(f"Total pages: {res.get('total_pages')}")
    print(f"Scanned pages: {res.get('scanned_pages_count')}")
    print(f"Total articles: {res.get('total_articles')}")
    print(f"Translated articles: {res.get('translated_count')}")
    
    cats = res.get("categories", {})
    for cat_name, articles in cats.items():
        print(f"Category '{cat_name}': {len(articles)} articles")
        for a in articles[:3]:
            print(f"  - [{a.get('category')}] {a.get('title')[:60]} (Page {a.get('page_number')})")

    out_file = Path("data/processed_news_sample.json")
    out_file.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(f"Saved full results to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
