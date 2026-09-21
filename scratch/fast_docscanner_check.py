import pypdfium2 as pdfium
from pathlib import Path
import pytesseract
import os

tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tess_path):
    pytesseract.pytesseract.tesseract_cmd = tess_path
os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

f = Path("data/uploads/batch_20260921_111114_00_20260918_204657_DocScanner_Hardcopy.pdf")
doc = pdfium.PdfDocument(str(f))
p0 = doc[0]
img_small = p0.render(scale=1.5).to_pil()

try:
    osd = pytesseract.image_to_osd(img_small)
    print("OSD:", osd)
except Exception as e:
    print("OSD failed:", e)

# Test with eng
txt_eng = pytesseract.image_to_string(img_small, lang="eng", config="--psm 1")
print(f"ENG text length: {len(txt_eng)}")
if len(txt_eng) > 100:
    print("ENG preview:", repr(txt_eng[:200]))
