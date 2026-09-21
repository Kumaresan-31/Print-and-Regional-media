import json
from pathlib import Path

f = Path("data/hardcopy_uploads/5a5194d1f136.json")
data = json.loads(f.read_text(encoding="utf-8"))
out = []
for i, a in enumerate(data.get("articles", [])):
    out.append(f"[{i}] ENG: {a.get('headline_english')}")
    out.append(f"     ORIG: {repr(a.get('headline_original'))}")
    out.append(f"     SNIP: {repr(a.get('original_snippet'))[:100]}")
    out.append(f"     BBOX: {a.get('bounding_box')}")

Path("scratch/all_5a5194d1f136_articles.txt").write_text("\n".join(out), encoding="utf-8")
print("Wrote scratch/all_5a5194d1f136_articles.txt")
