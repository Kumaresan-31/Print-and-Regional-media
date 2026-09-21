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
print(f"DocScanner pages: {len(doc)}")
p0 = doc[0]
img = p0.render(scale=3.0).to_pil()
print(f"Page 1 rendered size: {img.size}")

# Detect script using OSD
try:
    osd = pytesseract.image_to_osd(img)
    print("OSD:", osd)
except Exception as e:
    print("OSD error:", e)

# Test OCR with eng+hin+tam+mal
txt = pytesseract.image_to_string(img, lang="eng+hin+tam+mal+tel+mar", config="--psm 1")
print(f"OCR text length: {len(txt)}")
Path("scratch/docscanner_p1_text.txt").write_text(txt, encoding="utf-8")
print("Saved to scratch/docscanner_p1_text.txt")
