from pathlib import Path
from rapidocr_onnxruntime import RapidOCR
from PIL import Image

rapid = RapidOCR()
img_path = "scratch/rendered_page_300dpi.jpg"
res, _ = rapid(img_path)
print(f"RapidOCR total detected boxes: {len(res) if res else 0}")
if res:
    for i in range(min(15, len(res))):
        box, text, score = res[i][0], res[i][1], res[i][2]
        print(f"[{i}] score={score:.2f} text={repr(text)} box={box}")
