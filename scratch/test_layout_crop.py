import cv2
import numpy as np
from PIL import Image
from pathlib import Path
import pytesseract
import os

tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tess_path):
    pytesseract.pytesseract.tesseract_cmd = tess_path
os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

img_path = Path("scratch/rendered_page_300dpi.jpg")
img = cv2.imread(str(img_path))
h, w = img.shape[:2]
print(f"Page size: width={w}, height={h}")

# Crop top-left headline & article
crop = img[int(h*0.08):int(h*0.45), int(w*0.05):int(w*0.55)]
cv2.imwrite("scratch/test_crop.jpg", crop)

txt_psm3 = pytesseract.image_to_string(crop, lang="mal", config="--psm 3")
txt_psm6 = pytesseract.image_to_string(crop, lang="mal", config="--psm 6")

out = []
out.append("=== PSM 3 ON TOP-LEFT CROP ===")
out.append(txt_psm3)
out.append("=== PSM 6 ON TOP-LEFT CROP ===")
out.append(txt_psm6)

Path("scratch/crop_ocr_comparison.txt").write_text("\n".join(out), encoding="utf-8")
print("Saved comparison to scratch/crop_ocr_comparison.txt")
