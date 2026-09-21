import pytesseract
import os
from PIL import Image
from pathlib import Path

tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tess_path):
    pytesseract.pytesseract.tesseract_cmd = tess_path
os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

img = Image.open("scratch/rendered_page_300dpi.jpg").resize((800, 1100))
osd = pytesseract.image_to_osd(img)
print("OSD Result on Malayalam page:")
print(osd)
