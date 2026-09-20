import sys
sys.path.insert(0, 'backend')
from pathlib import Path
import json

archive_dir = Path('data/archive')
index_dir = Path('data/pdf_index')

sources = ['the_hindu', 'lokmat', 'loksatta', 'dt_next', 'financial_express']

print('=== ARCHIVE FILES ===')
for s in sources:
    s_dir = archive_dir / s
    if s_dir.exists():
        pdfs = list(s_dir.rglob('*.pdf'))
        print(f'{s}: {len(pdfs)} PDFs')
        for p in pdfs:
            print(f'   {p} ({p.stat().st_size} bytes)')
    else:
        print(f'{s}: no archive dir')

print('\n=== PDF INDEX FILES ===')
for s in sources:
    s_dir = index_dir / s
    if s_dir.exists():
        idxs = list(s_dir.glob('*.json'))
        print(f'{s}: {len(idxs)} index files')
        for i in idxs:
            try:
                with open(i, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                print(f'   {i.name}: {d.get("total_pages")} pages, {d.get("total_stories")} stories, doc_id={d.get("doc_id")}')
            except Exception as e:
                print(f'   {i.name}: error reading {e}')
    else:
        print(f'{s}: no index dir')
