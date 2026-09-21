from pathlib import Path
from PIL import Image
import pytesseract
from rapidocr_onnxruntime import RapidOCR
from harvester.news.pdf_parser import get_paddle_ocr, run_ocr_on_image

img_path = Path("data/snapshots/6166126cb03b/page_001.jpg")
print("Image exists:", img_path.exists())
pil_img = Image.open(img_path).convert("RGB")
print("Image size:", pil_img.size)

# Test 1: What installed languages does pytesseract see?
try:
    langs = pytesseract.get_languages()
    print("Tesseract installed languages:", langs)
except Exception as e:
    print("Tesseract get_languages error:", e)

# Test 2: Run run_ocr_on_image with preferred_lang="mal"
try:
    text, conf, blocks = run_ocr_on_image(img_path, pil_img, preferred_lang="mal")
    print(f"run_ocr_on_image output text len: {len(text)}, conf: {conf}, blocks: {len(blocks)}")
    print("First 300 chars of text:")
    print(repr(text[:300]))
except Exception as e:
    import traceback
    print("run_ocr_on_image error:")
    traceback.print_exc()
