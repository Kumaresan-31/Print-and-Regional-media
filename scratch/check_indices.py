import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path

for path in ['data/pdf_index/dt_next/2026-09-19.json', 'data/pdf_index/loksatta/2026-09-19.json', 'data/pdf_index/financial_express/2026-09-19.json']:
    p = Path(path)
    if not p.exists():
        print("NOT FOUND:", path)
        continue
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    print(f"\n=== {d['source_id']} ({d['source_name']}) ===")
    print('Total pages:', d.get('total_pages'))
    print('Total stories:', d.get('total_stories'))
    pages = d.get('pages', [])
    for pg in pages:
        print(f"  Page {pg['page_num']}: {len(pg.get('stories', []))} stories, OCR text len: {len(pg.get('ocr_text_en', ''))}")
        for s in pg.get('stories', [])[:3]:
            t = (s.get('title') or '')[:60]
            sn = (s.get('snippet') or '')[:60]
            print(f"    - [{s.get('category')}] {t} // {sn}")
