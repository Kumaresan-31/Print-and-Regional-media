import asyncio
import json
from pathlib import Path
from harvester.news.pdf_parser import pdf_news_parser
from harvester.news.news_cropper import generate_news_crop

async def run_test():
    fpath = Path("data/uploads/batch_20260921_113618_00_20092026-alappuzha-1.pdf")
    print("Testing parse_and_process_pdf on:", fpath.name)
    
    res = await pdf_news_parser.parse_and_process_pdf(
        file_path=fpath,
        source_name="20092026 Alappuzha 1"
    )
    
    articles = res.get("articles", [])
    print(f"Total articles extracted & translated: {len(articles)}")
    
    out = []
    for idx, a in enumerate(articles[:6]):
        print(f"\n[{idx+1}] ID: {a['id']} | CAT: {a['category']} | BBOX: {a['bounding_box']}")
        print(f"     ENG HL: {a['headline_english']}")
        print(f"     ENG BD: {a['content_english'][:120]}...")
        
        # Test crop generation
        snap_path = Path("data/snapshots") / a["doc_id"] / f"page_{a['page_number']:03d}.jpg"
        if snap_path.exists():
            crop_p = generate_news_crop(snap_path, a["headline_english"], story=a)
            print(f"     CROP GENERATED: {crop_p.name} (size: {crop_p.stat().st_size} bytes)")
        
        out.append({
            "id": a["id"],
            "headline_original": a.get("headline_original"),
            "headline_english": a["headline_english"],
            "content_english": a["content_english"][:200],
            "category": a["category"],
            "bounding_box": a["bounding_box"],
            "ocr_confidence": a["ocr_confidence"],
        })
        
    Path("scratch/real_parse_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSaved output to scratch/real_parse_output.json")

asyncio.run(run_test())
