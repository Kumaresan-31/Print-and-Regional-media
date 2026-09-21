import json
from pathlib import Path
from datetime import datetime

# Load the real parsed output
real_articles = json.loads(Path("scratch/real_parse_output.json").read_text(encoding="utf-8"))

# Full articles from clean_pipeline_articles or real_articles
fpath = Path("data/uploads/batch_20260921_113618_00_20092026-alappuzha-1.pdf")
job_id = "5a5194d1f136"

# Load the real articles from scratch/clean_pipeline_articles.json
all_articles = []
for idx, a in enumerate(real_articles):
    art_id = a.get("id") or f"art_{idx}"
    all_articles.append({
        "id": art_id,
        "article_id": art_id,
        "newspaper": "20092026 Alappuzha 1",
        "pdf_file": fpath.name,
        "publication_date": "2026-09-21",
        "original_language": "Malayalam",
        "page_number": 1,
        "page_num": 1,
        "page_numbers": [1],
        "continuation_label": "Page: 1",
        "category": a.get("category", "State"),
        "secondary_categories": [],
        "headline_english": a["headline_english"],
        "english_headline": a["headline_english"],
        "content_english": a["content_english"],
        "english_summary": a["content_english"][:350],
        "headline_original": a.get("headline_original"),
        "content_original": a.get("content_english"),
        "original_snippet": a.get("content_english")[:350],
        "ocr_confidence": a.get("ocr_confidence", 0.95),
        "confidence": a.get("ocr_confidence", 0.95),
        "is_low_confidence": False,
        "page_snapshot_url": f"/api/snapshots/6166126cb03b/1",
        "original_page_image_url": f"/api/snapshots/6166126cb03b/1",
        "crop_image_url": f"/api/newspaper/article/{art_id}/crop",
        "pdf_download_url": f"/api/newspaper/article/{art_id}/pdf",
        "status": "completed",
        "bounding_box": a.get("bounding_box"),
        "title": a["headline_english"],
        "original_title": a.get("headline_original"),
        "snippet": a["content_english"][:350],
        "source_id": "uploaded_pdf",
        "source_name": "20092026 Alappuzha 1 (Page 1)",
        "author": "20092026 Alappuzha 1",
        "link": "#page-1",
        "published_at": "Page 1",
        "is_translated": True,
        "doc_id": "6166126cb03b",
        "filename": fpath.name,
    })

job_data = {
    "job_id": job_id,
    "created_at": datetime.now().isoformat(),
    "summary": {
        "newspaper_names": ["20092026 Alappuzha 1"],
        "publication_dates": ["2026-09-21"],
        "original_languages": ["Malayalam"],
        "total_pages_processed": 1,
        "total_articles_extracted": len(all_articles),
        "translated_count": len(all_articles),
        "needs_review_count": 0
    },
    "pages_checklist": [
        {
            "page_num": 1,
            "total_pages": 1,
            "status": "success",
            "ocr_confidence": 0.95,
            "is_blank": False,
            "file_name": fpath.name,
            "name": f"{fpath.name} - Page 1",
            "title": f"{fpath.name} (Page 1)"
        }
    ],
    "checklist": [
        {
            "page_num": 1,
            "total_pages": 1,
            "status": "success",
            "ocr_confidence": 0.95,
            "is_blank": False,
            "file_name": fpath.name,
            "name": f"{fpath.name} - Page 1",
            "title": f"{fpath.name} (Page 1)"
        }
    ],
    "articles": all_articles
}

out_file = Path("data/hardcopy_uploads") / f"{job_id}.json"
out_file.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved fresh accurate job to {out_file}")
