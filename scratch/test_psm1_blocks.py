import cv2
from pathlib import Path
import pytesseract
import os
import json

tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tess_path):
    pytesseract.pytesseract.tesseract_cmd = tess_path
os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

img_path = Path("scratch/rendered_page_300dpi.jpg")
img = cv2.imread(str(img_path))
h, w = img.shape[:2]

# Run image_to_data with PSM 1 (Automatic page segmentation with OSD) and PSM 3
data = pytesseract.image_to_data(img, lang="mal", config="--psm 1", output_type=pytesseract.Output.DICT)

# Group words by (block_num, par_num)
blocks_dict = {}
n = len(data["level"])
for i in range(n):
    txt = (data["text"][i] or "").strip()
    if not txt:
        continue
    b_num = data["block_num"][i]
    p_num = data["par_num"][i]
    key = (b_num, p_num)
    x, y, bw, bh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
    if key not in blocks_dict:
        blocks_dict[key] = {
            "words": [txt],
            "x1": x, "y1": y, "x2": x + bw, "y2": y + bh,
            "block_num": b_num,
            "par_num": p_num
        }
    else:
        blocks_dict[key]["words"].append(txt)
        blocks_dict[key]["x1"] = min(blocks_dict[key]["x1"], x)
        blocks_dict[key]["y1"] = min(blocks_dict[key]["y1"], y)
        blocks_dict[key]["x2"] = max(blocks_dict[key]["x2"], x + bw)
        blocks_dict[key]["y2"] = max(blocks_dict[key]["y2"], y + bh)

print(f"Total paragraphs/blocks detected: {len(blocks_dict)}")
res = []
for k, v in sorted(blocks_dict.items(), key=lambda item: (item[1]["y1"], item[1]["x1"])):
    full_p = " ".join(v["words"])
    if len(full_p) > 20:
        res.append({
            "block": v["block_num"],
            "par": v["par_num"],
            "box": [v["x1"], v["y1"], v["x2"], v["y2"]],
            "text": full_p[:150]
        })

Path("scratch/blocks_psm1.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved {len(res)} substantial paragraphs to scratch/blocks_psm1.json")
