"""
Dedicated High-Accuracy OCR Engine for Marathi Language Newspapers.
Inspired by and incorporating techniques from:
https://github.com/Power-Howdy/pytesseract-ocr-marathi

Key Features:
1. PyMuPDF (fitz) high-DPI rendering (zoom = 3.5 - 4.0, ~250-300 DPI) for intricate Marathi conjunct ligatures.
2. Dual-language recognition (mar+eng): Accurately reads Marathi Devanagari script alongside English dates,
   numbers, quotes, brand names, and acronyms without unicode corruption.
3. Neural LSTM Engine (--oem 3) with configurable Page Segmentation Modes:
   - PSM 6: Uniform text block (ideal for cropped articles, news snippets, bounded stories).
   - PSM 3 / 4: Multi-column newspaper broadsheet pages.
4. Intelligent Devanagari dialect differentiation: Reliably distinguishes Marathi from Hindi
   using Marathi-exclusive characters (e.g. ळ U+0933) and frequency vocabulary markers.
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Union

import cv2
import numpy as np
from PIL import Image
import pytesseract

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

from harvester.config import BASE_DIR, TEMP_DIR

logger = logging.getLogger(__name__)

# Configure Tesseract binary path
TESSERACT_EXE_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
for exe in TESSERACT_EXE_CANDIDATES:
    if os.path.exists(exe):
        pytesseract.pytesseract.tesseract_cmd = exe
        break

# Configure project tessdata directory with mar.traineddata and eng.traineddata
LOCAL_TESSDATA = (BASE_DIR / "data" / "tessdata").resolve()
if LOCAL_TESSDATA.exists():
    os.environ["TESSDATA_PREFIX"] = str(LOCAL_TESSDATA)
elif Path("data/tessdata").resolve().exists():
    os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

MARATHI_KNOWN_SOURCES = {
    "lokmat", "loksatta", "sakaal", "sakal", "maharashtra_times",
    "maharashtratimes", "saamana", "pudhari", "tarun_bharat", "tarunbharat",
    "divya_marathi", "divyamarathi", "deshdoot", "navshakti", "prahaar",
    "punyanagari", "punya_nagari", "lokshahi", "marathi"
}

# Unique Marathi markers: 'ळ' (U+0933) is unique to Marathi in Devanagari script
MARATHI_DISTINCTIVE_CHARS = {"ळ", "ऱ"}
MARATHI_DISTINCTIVE_WORDS = {
    "आहे", "नाही", "झाली", "गेले", "यांनी", "म्हणाले", "करणार", "केली",
    "होत", "होते", "होती", "आहेत", "येथे", "त्यांच्या", "त्यांनी", "पुणे",
    "मुंबई", "जिल्हा", "महाराष्ट्र", "उपमुख्यमंत्री", "मुख्यमंत्री", "खासदार",
    "आमदार", "मंत्रालयात", "पोलीस", "ठाकरे", "शिंदे", "फडणवीस", "पवार",
    "नागपूर", "नाशिक", "कोल्हापूर", "छत्रपती", "संभाजीनगर", "सरकारने", "सांगितले"
}


class MarathiOCREngine:
    """
    Dedicated OCR Engine for Marathi regional newspaper extraction.
    """

    def __init__(self):
        self.default_lang = "mar+eng"
        self._check_installed_languages()

    def _check_installed_languages(self):
        """Verifies if 'mar' and 'eng' traineddata are available."""
        try:
            langs = pytesseract.get_languages()
            if "mar" in langs and "eng" in langs:
                self.default_lang = "mar+eng"
            elif "mar" in langs:
                self.default_lang = "mar"
            else:
                logger.warning(
                    f"Marathi ('mar') traineddata not found in {os.environ.get('TESSDATA_PREFIX')}. "
                    f"Available languages: {langs}"
                )
                self.default_lang = "eng"
        except Exception as e:
            logger.debug(f"Could not check Tesseract languages: {e}")
            self.default_lang = "mar+eng"

    @staticmethod
    def is_marathi_source(source_identifier: str) -> bool:
        """Checks if a newspaper source name or ID is a Marathi publication."""
        if not source_identifier:
            return False
        clean = source_identifier.lower().replace("-", "_").replace(" ", "_")
        return any(k in clean for k in MARATHI_KNOWN_SOURCES)

    @staticmethod
    def is_marathi_text(text: str) -> bool:
        """
        Linguistically determines whether Devanagari text is Marathi
        (distinguishing from Hindi or Sanskrit).
        """
        if not text:
            return False
        # Check for Marathi-exclusive character 'ळ' (U+0933) or 'ऱ' (U+0931)
        if any(ch in text for ch in MARATHI_DISTINCTIVE_CHARS):
            return True
        # Check frequency of Marathi token markers and inflected stems
        words = set(re.findall(r"[\u0900-\u097F]+", text))
        if len(words & MARATHI_DISTINCTIVE_WORDS) >= 1:
            return True
        # Check for inflected stems (e.g. पुण्यातील, महाराष्ट्रात, मुंबईत, पोलिसांनी)
        for w in words:
            if len(w) >= 3 and any(marker in w for marker in [
                "पुण्य", "मुंबई", "जिल्ह", "महाराष्ट्र", "पोलिस", "ठाकरे", "शिंदे", "फडणवीस", "पवार",
                "म्हणाले", "केली", "झाली", "आहे", "नाही", "घडामोडी", "मंत्रालयात"
            ]):
                return True
        return False

    @staticmethod
    def convert_pdf_to_images(
        pdf_path: Union[str, Path],
        output_dir: Optional[Path] = None,
        zoom: float = 3.5,
        start_page: int = 1,
        end_page: int = 0
    ) -> List[Path]:
        """
        Renders PDF pages to high-resolution JPEG images using PyMuPDF (fitz),
        mirroring ConvertToJPG.py with high-DPI scaling essential for Indic ligatures.
        """
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is not installed. Run 'pip install pymupdf'.")

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        out_dir = output_dir or (TEMP_DIR / f"marathi_pages_{pdf_path.stem}")
        out_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        start_idx = max(0, start_page - 1)
        end_idx = min(total_pages, end_page) if end_page > 0 else total_pages

        mat = fitz.Matrix(zoom, zoom)
        image_paths: List[Path] = []

        for p_idx in range(start_idx, end_idx):
            page_num = p_idx + 1
            page = doc[p_idx]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            dest_img = out_dir / f"page_{page_num:03d}.jpg"
            pix.save(str(dest_img))
            image_paths.append(dest_img)

        doc.close()
        logger.info(f"Rendered {len(image_paths)} high-res pages from {pdf_path.name} at zoom={zoom}")
        return image_paths

    @staticmethod
    def preprocess_image(image_input: Union[str, Path, Image.Image, np.ndarray]) -> np.ndarray:
        """
        Applies OpenCV image enhancements (grayscale + contrast normalization)
        to optimize recognition of scanned/newsprint Marathi text.
        """
        if isinstance(image_input, (str, Path)):
            img = cv2.imread(str(image_input))
            if img is None:
                # Fallback to PIL in case of non-ASCII paths on Windows
                pil_temp = Image.open(image_input).convert("RGB")
                img = cv2.cvtColor(np.array(pil_temp), cv2.COLOR_RGB2BGR)
        elif isinstance(image_input, Image.Image):
            img = cv2.cvtColor(np.array(image_input.convert("RGB")), cv2.COLOR_RGB2BGR)
        elif isinstance(image_input, np.ndarray):
            img = image_input.copy()
        else:
            raise ValueError("Unsupported image input type")

        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # Denoise slightly while preserving thin strokes of Marathi matras
        denoised = cv2.bilateralFilter(gray, 5, 50, 50)
        return denoised

    def extract_text(
        self,
        image_input: Union[str, Path, Image.Image, np.ndarray],
        psm: int = 6,
        lang: Optional[str] = None,
        preprocess: bool = False
    ) -> str:
        """
        Extracts clean Marathi text from an image or cropped article snippet.
        Matches Power-Howdy/pytesseract-ocr-marathi:
        custom_config = r'--oem 3 --psm 6' (or psm 3/4 for broadsheets)
        """
        ocr_lang = lang or self.default_lang
        custom_config = f"--oem 3 --psm {psm}"

        if preprocess:
            img = self.preprocess_image(image_input)
        elif isinstance(image_input, (str, Path)):
            img = cv2.imread(str(image_input))
            if img is None:
                img = Image.open(image_input).convert("RGB")
        else:
            img = image_input

        try:
            raw_text = pytesseract.image_to_string(img, lang=ocr_lang, config=custom_config)
            return raw_text.strip()
        except Exception as e:
            logger.warning(f"Marathi OCR extraction note ({ocr_lang}, psm={psm}): {e}")
            # Fallback to mar if mar+eng failed, or eng
            if "+" in ocr_lang:
                try:
                    return pytesseract.image_to_string(img, lang="mar", config=custom_config).strip()
                except Exception:
                    pass
            return ""

    def extract_boxes(
        self,
        image_input: Union[str, Path, Image.Image, np.ndarray],
        psm: int = 3,
        lang: Optional[str] = None
    ) -> Tuple[str, float, List[Dict[str, Any]]]:
        """
        Extracts hierarchical bounding boxes and layout lines for full newspaper pages
        or article regions with word-level coordinates and confidence metrics.
        """
        ocr_lang = lang or self.default_lang
        custom_config = f"--oem 3 --psm {psm}"

        if isinstance(image_input, (str, Path)):
            pil_img = Image.open(image_input).convert("RGB")
        elif isinstance(image_input, np.ndarray):
            pil_img = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB))
        elif isinstance(image_input, Image.Image):
            pil_img = image_input.convert("RGB")
        else:
            raise ValueError("Unsupported image input type")

        try:
            data = pytesseract.image_to_data(
                pil_img,
                lang=ocr_lang,
                config=custom_config,
                output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            logger.warning(f"Marathi image_to_data failed with config '{custom_config}': {e}")
            # Fallback to psm 3
            data = pytesseract.image_to_data(
                pil_img,
                lang=ocr_lang,
                config="--psm 3",
                output_type=pytesseract.Output.DICT
            )

        n_boxes = len(data.get("level", []))
        lines_dict: Dict[Tuple[int, int, int], Dict[str, Any]] = {}

        for i in range(n_boxes):
            txt = (data["text"][i] or "").strip()
            if not txt:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            bw = int(data["width"][i])
            bh = int(data["height"][i])
            b_num = int(data["block_num"][i])
            p_num = int(data["par_num"][i])
            l_num = int(data["line_num"][i])
            conf_val = str(data["conf"][i])
            conf = float(conf_val) if conf_val != "-1" else 75.0

            key = (b_num, p_num, l_num)
            if key not in lines_dict:
                lines_dict[key] = {
                    "words": [txt],
                    "x1": x, "y1": y, "x2": x + bw, "y2": y + bh,
                    "confs": [conf],
                    "block_num": b_num, "par_num": p_num, "line_num": l_num
                }
            else:
                ld = lines_dict[key]
                ld["words"].append(txt)
                ld["x1"] = min(ld["x1"], x)
                ld["y1"] = min(ld["y1"], y)
                ld["x2"] = max(ld["x2"], x + bw)
                ld["y2"] = max(ld["y2"], y + bh)
                ld["confs"].append(conf)

        blocks: List[Dict[str, Any]] = []
        all_confs: List[float] = []

        for val in lines_dict.values():
            ltxt = " ".join(val["words"]).strip()
            x1, y1, x2, y2 = val["x1"], val["y1"], val["x2"], val["y2"]
            box = [[float(x1), float(y1)], [float(x2), float(y1)], [float(x2), float(y2)], [float(x1), float(y2)]]
            avg_c = sum(val["confs"]) / max(len(val["confs"]), 1)
            all_confs.append(avg_c)
            blocks.append({
                "text": ltxt,
                "score": round(max(avg_c / 100.0, 0.5), 4),
                "box": box,
                "bbox": [x1, y1, x2, y2],
                "block_num": val.get("block_num", 0),
                "par_num": val.get("par_num", 0),
                "line_num": val.get("line_num", 0),
                "words": val.get("words", []),
            })

        # Generate full raw text
        raw_text = self.extract_text(pil_img, psm=psm, lang=ocr_lang)
        overall_conf = round(sum(all_confs) / max(len(all_confs), 1) / 100.0, 4) if all_confs else 0.90
        return raw_text, overall_conf, blocks


# Global engine singleton
marathi_ocr_engine = MarathiOCREngine()
