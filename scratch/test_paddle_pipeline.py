import asyncio
import os
import sys
from pathlib import Path

# Ensure paths
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
sys.path.insert(0, str(Path("backend").resolve()))

from harvester.news.pdf_parser import pdf_news_parser

async def test():
    test_pdf = Path("data/uploads/20260918_204657_DocScanner_Hardcopy.pdf")
    if not test_pdf.exists():
        print(f"File not found: {test_pdf}")
        return

    print(f"Testing parse_and_process_pdf on {test_pdf.name} (max 1 page)...")
    progress_log = []
    def cb(pnum, tot, st, conf, blank, fname):
        progress_log.append((pnum, tot, st, conf, blank, fname))
        print(f"  [Callback] Page {pnum}/{tot} - Status: {st}, Conf: {conf:.2f}, Blank: {blank}, File: {fname}")

    result = await pdf_news_parser.parse_and_process_pdf(
        file_path=test_pdf,
        source_name="Hardcopy Test",
        max_pages=1,
        progress_callback=cb
    )

    print("\n--- Processing Results ---")
    print(f"Doc ID: {result.get('doc_id')}")
    print(f"Total Pages: {result.get('total_pages')}")
    print(f"Total Articles: {result.get('total_articles')}")
    print(f"Languages: {result.get('detected_languages')}")
    print(f"Categories: {list(result.get('categories', {}).keys())}")
    
    articles = result.get("articles", [])
    if articles:
        a0 = articles[0]
        print(f"\nSample Article:")
        print(f"  Title: {a0.get('title')}")
        print(f"  English Headline: {a0.get('english_headline')}")
        print(f"  Category: {a0.get('category')}")
        print(f"  Confidence: {a0.get('confidence')}")
        print(f"  Page Num: {a0.get('page_num')}")
        print(f"  Snippet: {a0.get('snippet')[:100]}...")
        print(f"  Bounding Box: {a0.get('bounding_box')}")
    print("\nSUCCESS: PaddleOCR parsed and extracted hardcopy page cleanly!")

if __name__ == "__main__":
    asyncio.run(test())
