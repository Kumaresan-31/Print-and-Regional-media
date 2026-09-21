from pathlib import Path
from PIL import Image
import json
from harvester.news.pdf_parser import run_ocr_on_image, NewspaperPDFParser, PageData

img_path = Path("data/snapshots/6166126cb03b/page_001.jpg")
pil_img = Image.open(img_path).convert("RGB")
text, conf, blocks = run_ocr_on_image(img_path, pil_img, preferred_lang="mal")

Path("scratch/ocr_extracted_text.txt").write_text(text, encoding="utf-8")
print(f"Extracted OCR text length: {len(text)}. Written to scratch/ocr_extracted_text.txt")

# Now let's test segment_text_into_stories
pdata = PageData(
    page_num=1,
    raw_text=text,
    is_scanned=True,
    ocr_confidence=conf,
    snapshot_path=img_path,
    snapshot_url="/api/snapshots/6166126cb03b/1",
    blocks=blocks,
    publication_date="2026-09-21"
)

parser = NewspaperPDFParser()
stories = parser.segment_text_into_stories([pdata])
print(f"Total stories segmented: {len(stories)}")
dump = []
for i, s in enumerate(stories):
    dump.append({
        "index": i,
        "title": s.get("title"),
        "body_len": len(s.get("body", "")),
        "snippet": s.get("snippet", "")[:100],
        "ocr_raw_text_len": len(s.get("ocr_raw_text", "")),
        "bbox": s.get("bounding_box")
    })

Path("scratch/segmented_stories.json").write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
print("Written scratch/segmented_stories.json")
