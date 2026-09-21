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
img = p0.render(scale=3.0).to_pil()

txt_tam = pytesseract.image_to_string(img, lang="tam", config="--psm 1")
print(f"Tamil text length: {len(txt_tam)}")
Path("scratch/docscanner_tamil_text.txt").write_text(txt_tam, encoding="utf-8")
print("Saved Tamil text to scratch/docscanner_tamil_text.txt")
