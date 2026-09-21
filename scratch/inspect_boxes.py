import json
from pathlib import Path

bf = Path("data/snapshots/6166126cb03b/page_001.boxes.json")
if bf.exists():
    boxes = json.loads(bf.read_text(encoding="utf-8"))
    print(f"Total boxes in {bf}: {len(boxes)}")
    for i, b in enumerate(boxes[:10]):
        print(f"[{i}] score: {b.get('score')} | box: {b.get('box')} | text: {repr(b.get('text'))}")
else:
    print("Boxes file not found!")
