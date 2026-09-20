import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import requests, json
from PIL import Image
import io

issue_id = "LOK_PULK_20260920"
url = f"https://epaperlokmat.in/eNewspaper/OutSourcingDataNew.php?operation=getThumbnailDetails&selectedIssueId={issue_id}&data=2"
headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://epaper.lokmat.com/"
}

r = requests.get(url, headers=headers, timeout=10)
pages_info = r.json()
print(f"Retrieved {len(pages_info)} pages for {issue_id}")

# Download first 4 pages and check sizes
images = []
for p in pages_info[:4]:
    thumb = p.get("ThumbnailURL", "")
    full_rel = thumb.replace("/Thumbnails/", "/").replace("Thumbnails/", "")
    full_url = f"https://images.epaperlokmat.in/eNewspaper/{full_rel}"
    img_resp = requests.get(full_url, headers=headers, timeout=15)
    print(f"Page {p['pageno']} ({full_url}): status={img_resp.status_code}, len={len(img_resp.content)}")
    if img_resp.status_code == 200:
        im = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
        images.append(im)

out_pdf = Path("../data/archive/lokmat/2026-09-20/lokmat_pune_2026-09-20.pdf")
out_pdf.parent.mkdir(parents=True, exist_ok=True)
if images:
    images[0].save(out_pdf, save_all=True, append_images=images[1:], resolution=150.0)
    print(f"Saved real PDF: {out_pdf} ({out_pdf.stat().st_size} bytes)")
