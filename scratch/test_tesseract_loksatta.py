import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from harvester.config import BASE_DIR
import pytesseract
import pypdfium2 as pdfium
import asyncio
from harvester.translation.llm_translator import llm_translator

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
tessdata_dir = (BASE_DIR / "data" / "tessdata").resolve()
os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)

pdf_path = BASE_DIR / "data" / "archive" / "loksatta" / "2026-09-20" / "loksatta_pune_2026-09-20.pdf"
doc = pdfium.PdfDocument(str(pdf_path))

async def main():
    for p_idx in [1, 2, 3]: # pages 2, 3, 4
        page = doc[p_idx]
        img = page.render(scale=2.0).to_pil()
        text = pytesseract.image_to_string(img, lang="mar+hin+eng")
        regional = any(0x0900 <= ord(c) <= 0x0DFF for c in text)
        print(f"--- Page {p_idx+1}: {len(text)} chars, regional={regional} ---")
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 30]
        for line in lines[:3]:
            tr = await llm_translator.translate(line, source_lang="mr")
            print("ORIGINAL (encoded):", line.encode("ascii", "replace").decode())
            print("ENGLISH:", tr.translated_text)

asyncio.run(main())
