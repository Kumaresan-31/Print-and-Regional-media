import urllib.request
import json
from pathlib import Path

url = "http://localhost:8000/api/newspaper/hardcopy-news?limit=6"
req = urllib.request.urlopen(url)
data = json.loads(req.read().decode("utf-8"))
articles = data.get("articles", [])
out = [f"Total articles returned from /api/newspaper/hardcopy-news: {len(articles)}"]

for i, a in enumerate(articles[:5]):
    out.append(f"\n[{i+1}] Newspaper: {a.get('newspaper')} | Category: {a.get('category')}")
    out.append(f"     Headline ENG: {a.get('headline_english')}")
    out.append(f"     Headline ORIG: {repr(a.get('headline_original'))}")
    out.append(f"     BBox: {a.get('bounding_box')}")
    crop_url = f"http://localhost:8000{a.get('crop_image_url')}"
    try:
        c_req = urllib.request.urlopen(crop_url)
        out.append(f"     Crop URL HTTP status: {c_req.getcode()} (type: {c_req.headers.get('Content-Type')})")
    except Exception as e:
        out.append(f"     Crop URL test failed: {e}")

Path("scratch/verify_api_out.txt").write_text("\n".join(out), encoding="utf-8")
print("Saved verification output to scratch/verify_api_out.txt")
