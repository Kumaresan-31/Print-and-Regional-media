import pypdfium2 as pdfium
import pypdf
from pathlib import Path

files = [
    Path("data/uploads/batch_20260921_113618_00_20092026-alappuzha-1.pdf"),
    Path("data/uploads/batch_20260921_111114_00_20260918_204657_DocScanner_Hardcopy.pdf")
]

for f in files:
    print("=" * 60)
    print("FILE:", f)
    if not f.exists():
        print("DOES NOT EXIST!")
        continue
    reader = pypdf.PdfReader(str(f))
    print(f"Total pages: {len(reader.pages)}")
    for i in range(min(2, len(reader.pages))):
        p = reader.pages[i]
        text = p.extract_text() or ""
        print(f"--- Page {i+1} ---")
        print(f"pypdf extract_text length: {len(text)}")
        if text.strip():
            print(f"Sample text (first 300 chars): {repr(text[:300])}")
        else:
            print("Direct text is EMPTY (Scanned/Image PDF)")
