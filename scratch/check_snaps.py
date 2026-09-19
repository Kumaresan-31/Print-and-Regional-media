import json, pathlib

for src, fname in [
    ("financial_express", "data/pdf_index/financial_express/2026-09-19.json"),
    ("dt_next", "data/pdf_index/dt_next/2026-09-19.json"),
]:
    data = json.load(open(fname, encoding='utf-8'))
    pages = data.get('pages', [])
    ok = sum(1 for p in pages if p.get('snapshot_path') and pathlib.Path(p.get('snapshot_path')).exists())
    missing = len(pages) - ok
    doc_id = data.get('doc_id', '')
    print(f"{src}: {ok} ok, {missing} missing, doc_id={doc_id}, total_pages={len(pages)}")
