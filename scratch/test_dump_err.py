import sys
sys.path.insert(0, "backend")
from pathlib import Path
from PIL import Image
from harvester.news.pdf_parser import run_ocr_on_image, _clean_box_coords
import json

img_p = Path("data/snapshots/70126b9cd65c/page_001.jpg")
img = Image.open(img_p)
t, c, blocks = run_ocr_on_image(img_p, img)
print("Blocks count:", len(blocks))
try:
    clean_blocks = [
        {"text": str(b.get("text", "")), "score": round(float(b.get("score", 0.9)), 4), "box": _clean_box_coords(b.get("box"))}
        for b in blocks
    ]
    with open("data/snapshots/70126b9cd65c/page_001.boxes_test.json", "w", encoding="utf-8") as bf:
        json.dump(clean_blocks, bf, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    print("SUCCESS! Size:", Path("data/snapshots/70126b9cd65c/page_001.boxes_test.json").stat().st_size)
except Exception as e:
    import traceback
    traceback.print_exc()
