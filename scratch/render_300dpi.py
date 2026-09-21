import pypdfium2 as pdfium
from pathlib import Path
from PIL import Image

pdf_path = Path("data/uploads/batch_20260921_113618_00_20092026-alappuzha-1.pdf")
doc = pdfium.PdfDocument(str(pdf_path))
page = doc[0]

# Render at scale 3.5 (~250-300 DPI)
img = page.render(scale=3.5).to_pil()
print(f"Rendered image size at scale 3.5: {img.size}")
out_path = Path("scratch/rendered_page_300dpi.jpg")
img.save(out_path, "JPEG", quality=95)
print("Saved to", out_path)
