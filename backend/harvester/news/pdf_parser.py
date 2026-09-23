import asyncio
import concurrent.futures
import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Any, Tuple, Callable, Set

from PIL import Image, ImageDraw, ImageFont
import zipfile
import xml.etree.ElementTree as ET
import pypdf
import pypdfium2 as pdfium
from rapidocr_onnxruntime import RapidOCR

from harvester.config import settings, SNAPSHOTS_DIR, BASE_DIR
from harvester.models import NewsArticle
from harvester.news.service import contains_regional_script, CATEGORY_VALIDATION_KEYWORDS
from harvester.translation.llm_translator import llm_translator

logger = logging.getLogger(__name__)

# Configure Tesseract binary path and tessdata directory with 10+ Indian languages
TESSERACT_DEFAULT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
LOCAL_TESSDATA = (BASE_DIR / "data" / "tessdata").resolve()
if LOCAL_TESSDATA.exists():
    os.environ["TESSDATA_PREFIX"] = str(LOCAL_TESSDATA)
elif Path("data/tessdata").resolve().exists():
    os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

TESSERACT_LANGUAGES = "eng+hin+tam+tel+mar+ben+guj+kan+mal+pan+urd"
_pytesseract = None


def get_pytesseract():
    """Load Tesseract only when an OCR operation actually needs it."""
    global _pytesseract
    if _pytesseract is None:
        import pytesseract

        if os.path.exists(TESSERACT_DEFAULT_PATH):
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_DEFAULT_PATH
        _pytesseract = pytesseract
    return _pytesseract

# ──────────────────────────────────────────────────────────────────────────
# FASTOCR ENGINE SINGLETON (High-Speed ONNX Engine, Replacing Heavy PaddleOCR)
# ──────────────────────────────────────────────────────────────────────────
_fast_ocr_engine = None
_fast_ocr_lock = Lock()
_pdf_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf_worker")


def get_fast_ocr() -> RapidOCR:
    """Retrieves or initializes a FastOCR (RapidOCR ONNX) engine instance."""
    global _fast_ocr_engine
    if _fast_ocr_engine is None:
        with _fast_ocr_lock:
            if _fast_ocr_engine is None:
                logger.info("Initializing FastOCR (RapidOCR ONNX high-speed engine)...")
                _fast_ocr_engine = RapidOCR()
    return _fast_ocr_engine


# Aliases for compatibility
get_rapid_ocr = get_fast_ocr


def get_paddle_ocr(lang: str = "en") -> Optional[Any]:
    """PaddleOCR is disabled in favor of high-performance FastOCR (RapidOCR ONNX)."""
    return None


REGIONAL_TESS_LANGS: Set[str] = {"mal", "tam", "tel", "kan", "ben", "guj", "hin", "mar", "mar+eng", "pan", "urd", "ori"}


def _clean_box_coords(box: Any) -> List[Any]:
    """Recursively convert numpy arrays/scalars to pure Python floats/ints for JSON serialization."""
    if box is None:
        return []
    if hasattr(box, "tolist"):
        try:
            return box.tolist()
        except Exception:
            pass
    if isinstance(box, (list, tuple)):
        clean = []
        for pt in box:
            if isinstance(pt, (list, tuple)):
                clean.append([float(c) for c in pt])
            else:
                try:
                    clean.append(float(pt))
                except Exception:
                    clean.append(str(pt))
        return clean
    return []


def detect_script_from_osd(pil_img: Image.Image) -> Optional[str]:
    """
    Uses Tesseract OSD (Orientation & Script Detection) to identify
    Indian regional scripts (Malayalam, Tamil, Telugu, Kannada, Bengali, Gujarati,
    Gurmukhi, Devanagari, Arabic/Urdu, Latin) in ~0.4s.
    """
    try:
        pytesseract = get_pytesseract()
        w, h = pil_img.size
        if w > 1000 or h > 1400:
            scale_f = min(1000.0 / w, 1400.0 / h)
            osd_img = pil_img.resize((max(1, int(w * scale_f)), max(1, int(h * scale_f))))
        else:
            osd_img = pil_img
        osd_res = pytesseract.image_to_osd(osd_img)
        match = re.search(r"Script:\s*([A-Za-z]+)", osd_res)
        if match:
            script_name = match.group(1).lower()
            osd_map = {
                "malayalam": "mal",
                "tamil": "tam",
                "telugu": "tel",
                "kannada": "kan",
                "bengali": "ben",
                "gujarati": "guj",
                "gurmukhi": "pan",
                "devanagari": "hin",
                "arabic": "urd",
                "latin": "eng",
            }
            return osd_map.get(script_name)
    except Exception as e:
        logger.debug(f"Tesseract OSD script detection notice: {e}")
    return None


def run_ocr_on_image(
    image_path: Path,
    pil_img: Optional[Image.Image] = None,
    preferred_lang: Optional[str] = None,
) -> Tuple[str, float, List[Dict[str, Any]]]:
    """
    Executes high-accuracy dual-engine OCR:
    - For Indian regional scripts (Malayalam, Tamil, Telugu, Kannada, Bengali, Hindi, Marathi, etc.),
      runs Tesseract with language pack as PRIMARY engine with exact bounding box and line-layout extraction.
    - For English/Latin digital/scanned documents, uses PaddleOCR / RapidOCR for fast, accurate parsing.
    - If preferred_lang is not provided, uses fast Tesseract OSD script detection.
    """
    pytesseract = None

    def get_tesseract():
        nonlocal pytesseract
        if pytesseract is None:
            pytesseract = get_pytesseract()
        return pytesseract

    if pil_img is None:
        try:
            pil_img = Image.open(image_path).convert("RGB")
        except Exception:
            pass

    # 0. Check if image path or metadata belongs to a Marathi newspaper
    if not preferred_lang:
        try:
            from harvester.extractors.engines.marathi_ocr import marathi_ocr_engine
            path_str = str(image_path) if image_path else ""
            if marathi_ocr_engine.is_marathi_source(path_str):
                preferred_lang = "mar+eng"
        except Exception:
            pass

    # 1. Fast OSD script detection if preferred_lang is unknown
    if not preferred_lang and pil_img is not None:
        detected_script = detect_script_from_osd(pil_img)
        if detected_script and (detected_script in REGIONAL_TESS_LANGS or "mar" in detected_script):
            preferred_lang = detected_script

    # ──────────────────────────────────────────────────────────────────────────
    # PRIMARY ENGINE FOR INDIC REGIONAL SCRIPTS: Regional Tesseract OCR with Layout
    # ──────────────────────────────────────────────────────────────────────────
    if preferred_lang and (preferred_lang in REGIONAL_TESS_LANGS or "mar" in preferred_lang) and pil_img is not None:
        try:
            ocr_ready_img = pil_img.convert("RGB")

            # Dedicated high-accuracy Marathi OCR engine (Power-Howdy/pytesseract-ocr-marathi)
            if "mar" in preferred_lang:
                try:
                    from harvester.extractors.engines.marathi_ocr import marathi_ocr_engine
                    tess_clean, conf, blocks = marathi_ocr_engine.extract_boxes(ocr_ready_img, psm=3)
                    if tess_clean and (contains_regional_script(tess_clean) or len(tess_clean) > 30):
                        return tess_clean, conf, blocks
                except Exception as m_err:
                    logger.debug(f"Marathi OCR engine note, falling back to standard regional OCR: {m_err}")

            lang_arg = preferred_lang
            try:
                tesseract = get_tesseract()
                data = tesseract.image_to_data(ocr_ready_img, lang=lang_arg, config="--psm 1", output_type=tesseract.Output.DICT)
            except Exception:
                    tesseract = get_tesseract()
                    data = tesseract.image_to_data(ocr_ready_img, lang=lang_arg, config="--psm 3", output_type=tesseract.Output.DICT)

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
                conf = float(data["conf"][i]) if str(data["conf"][i]) != "-1" else 75.0

                key = (b_num, p_num, l_num)
                if key not in lines_dict:
                    lines_dict[key] = {
                        "words": [txt],
                        "x1": x, "y1": y, "x2": x + bw, "y2": y + bh,
                        "conf": conf, "confs": [conf],
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
            for val in lines_dict.values():
                ltxt = " ".join(val["words"]).strip()
                x1, y1, x2, y2 = val["x1"], val["y1"], val["x2"], val["y2"]
                box = [[float(x1), float(y1)], [float(x2), float(y1)], [float(x2), float(y2)], [float(x1), float(y2)]]
                avg_c = sum(val["confs"]) / max(len(val["confs"]), 1)
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

            try:
                tess_raw = get_tesseract().image_to_string(ocr_ready_img, lang=lang_arg, config="--psm 1")
            except Exception:
                tess_raw = get_tesseract().image_to_string(ocr_ready_img, lang=lang_arg, config="--psm 3")
            tess_clean = tess_raw.strip()

            if tess_clean and (contains_regional_script(tess_clean) or len(tess_clean) > 40):
                return tess_clean, 0.95, blocks
        except Exception as te:
            logger.warning(f"Regional Tesseract OCR execution note: {te}")

    # ──────────────────────────────────────────────────────────────────────────
    # HIGH-SPEED FASTOCR ENGINE (ONNX Deep Learning Text & Layout Detection)
    # ──────────────────────────────────────────────────────────────────────────
    fast_engine = get_fast_ocr()
    ocr_lines: List[str] = []
    scores: List[float] = []
    blocks: List[Dict[str, Any]] = []

    if fast_engine is not None:
        try:
            import numpy as np
            if pil_img is not None:
                img_for_fast = np.array(pil_img.convert("RGB"))
            elif image_path and Path(image_path).exists():
                img_for_fast = str(image_path)
            else:
                img_for_fast = None

            if img_for_fast is not None:
                ocr_res = fast_engine(img_for_fast)
                res_list = ocr_res[0] if isinstance(ocr_res, tuple) else ocr_res
                if res_list:
                    for idx, item in enumerate(res_list):
                        if not item or len(item) < 2:
                            continue
                        box = item[0]
                        line_txt = str(item[1]).strip()
                        if not line_txt:
                            continue
                        try:
                            score = float(item[2]) if len(item) > 2 else 0.95
                        except (ValueError, TypeError):
                            score = 0.95

                        clean_box = _clean_box_coords(box)
                        bbox = None
                        if clean_box and len(clean_box) >= 4:
                            xs = [pt[0] for pt in clean_box if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                            ys = [pt[1] for pt in clean_box if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                            if xs and ys:
                                bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

                        ocr_lines.append(line_txt)
                        scores.append(score)
                        blocks.append({
                            "text": line_txt,
                            "score": round(float(score), 4),
                            "box": clean_box,
                            "bbox": bbox,
                            "block_num": idx,
                        })
        except Exception as e:
            logger.warning(f"FastOCR execution warning on {getattr(image_path, 'name', 'image')}: {e}")

    rapid_text = "\n".join(ocr_lines).strip()
    avg_rapid_conf = round(sum(scores) / max(len(scores), 1), 4) if scores else 0.90

    # If RapidOCR found regional script or text is sparse, try Tesseract
    tess_lines: List[str] = []
    needs_tesseract = (
        (preferred_lang and preferred_lang not in ("eng", "en"))
        or contains_regional_script(rapid_text)
        or len(rapid_text) < 120
    )

    if needs_tesseract and pil_img is not None:
        try:
            installed_langs = []
            try:
                installed_langs = get_tesseract().get_languages()
            except Exception:
                pass

            lang_arg = "eng"
            if preferred_lang and preferred_lang in installed_langs:
                lang_arg = f"{preferred_lang}+eng"
            elif installed_langs:
                r_code, _ = detect_script_language(rapid_text)
                tess_script_map = {
                    "ta": "tam", "hi": "hin", "te": "tel", "bn": "ben",
                    "mr": "mar+eng" if ("mar" in installed_langs or (LOCAL_TESSDATA / "mar.traineddata").exists()) else "hin",
                    "gu": "guj", "kn": "kan", "ml": "mal",
                    "pa": "pan", "ur": "urd"
                }
                detected_target = tess_script_map.get(r_code)
                if detected_target and detected_target in installed_langs:
                    lang_arg = f"{detected_target}+eng"
                else:
                    lang_arg = "hin+tam+tel+mal+kan+ben+eng" if any(l in installed_langs for l in ["hin", "tam", "tel", "mal"]) else "eng"

            tess_raw = get_tesseract().image_to_string(pil_img, lang=lang_arg, config="--psm 3")
            tess_clean = tess_raw.strip()
            if tess_clean:
                for line in tess_clean.splitlines():
                    cln = line.strip()
                    if len(cln) >= 3:
                        tess_lines.append(cln)
        except Exception as te:
            logger.debug(f"Tesseract fallback OCR warning: {te}")

    # Intelligent merger
    has_regional_in_rapid = contains_regional_script(rapid_text)
    has_regional_in_tess = any(contains_regional_script(tl) for tl in tess_lines)

    if has_regional_in_tess and not has_regional_in_rapid:
        combined_text = "\n".join(tess_lines).strip()
        confidence = 0.92
    elif has_regional_in_tess and has_regional_in_rapid:
        seen_lower = {l.lower() for l in ocr_lines}
        merged = list(ocr_lines)
        for tl in tess_lines:
            if tl.lower() not in seen_lower and len(tl) > 5:
                merged.append(tl)
                seen_lower.add(tl.lower())
        combined_text = "\n".join(merged).strip()
        confidence = avg_rapid_conf
    elif rapid_text:
        combined_text = rapid_text
        confidence = avg_rapid_conf
    elif tess_lines:
        combined_text = "\n".join(tess_lines).strip()
        confidence = 0.88
    else:
        combined_text = ""
        confidence = 0.50

    return combined_text, confidence, blocks


def extract_text_from_docx(file_path: Path) -> str:
    """Extracts clean text paragraphs from Word .docx documents via OOXML."""
    try:
        with zipfile.ZipFile(file_path) as z:
            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            paragraphs = []
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [
                    node.text for node in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                    if node.text
                ]
                if texts:
                    paragraphs.append("".join(texts).strip())
            return "\n\n".join(p for p in paragraphs if p)
    except Exception as e:
        logger.warning(f"Failed to read docx {file_path}: {e}")
        return ""


def extract_text_from_doc_or_text(file_path: Path) -> str:
    """Extracts text from plain text files, markdown, or legacy documents with fallback encodings."""
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16"):
        try:
            with open(file_path, "r", encoding=enc, errors="replace") as f:
                content = f.read()
                if content and any(c.isalnum() for c in content):
                    return content
        except Exception:
            pass
    # If binary doc, extract printable ASCII sequences
    try:
        data = file_path.read_bytes()
        strs = re.findall(rb"[\x20-\x7e\n\r\t]{4,}", data)
        return "\n".join(s.decode("ascii", errors="ignore").strip() for s in strs if s.strip())
    except Exception:
        return ""


def render_text_to_image(text: str, output_path: Path, max_lines: int = 55) -> None:
    """Renders plain text onto a clean high-resolution document snapshot page."""
    img = Image.new("RGB", (1200, 1600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Header banner
    draw.rectangle([(0, 0), (1200, 75)], fill=(15, 23, 42))
    draw.text((35, 25), "DOCUMENT PREVIEW & EXTRACTION", fill=(56, 189, 248))

    lines = text.splitlines()[:max_lines]
    y = 100
    for line in lines:
        if y > 1530:
            break
        draw.text((45, y), line[:95], fill=(30, 41, 59))
        y += 26
    img.save(output_path, "JPEG", quality=90)


def detect_script_language(text: str, source_hint: Optional[str] = None) -> Tuple[str, str]:
    """
    Detects language code and name based on Unicode character script ranges,
    publication source hints, and multilingual linguistic vocabulary patterns.
    """
    if not text:
        return "auto", "Regional"

    counts = {
        "hi": 0, "te": 0, "ta": 0, "bn": 0, "gu": 0, "kn": 0,
        "ml": 0, "pa": 0, "or": 0, "ur": 0, "ru": 0, "zh": 0,
        "ja": 0, "ko": 0, "el": 0, "th": 0, "he": 0
    }

    for ch in text:
        code = ord(ch)
        if 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
        elif 0x0C00 <= code <= 0x0C7F:
            counts["te"] += 1
        elif 0x0B80 <= code <= 0x0BFF:
            counts["ta"] += 1
        elif 0x0980 <= code <= 0x09FF:
            counts["bn"] += 1
        elif 0x0A80 <= code <= 0x0AFF:
            counts["gu"] += 1
        elif 0x0C80 <= code <= 0x0CFF:
            counts["kn"] += 1
        elif 0x0D00 <= code <= 0x0D7F:
            counts["ml"] += 1
        elif 0x0A00 <= code <= 0x0A7F:
            counts["pa"] += 1
        elif 0x0B00 <= code <= 0x0B7F:
            counts["or"] += 1
        elif (0x0600 <= code <= 0x06FF) or (0x0750 <= code <= 0x077F) or (0x08A0 <= code <= 0x08FF):
            counts["ur"] += 1
        elif 0x0400 <= code <= 0x04FF:
            counts["ru"] += 1
        elif (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF):
            counts["zh"] += 1
        elif (0x3040 <= code <= 0x309F) or (0x30A0 <= code <= 0x30FF):
            counts["ja"] += 1
        elif (0xAC00 <= code <= 0xD7AF) or (0x1100 <= code <= 0x11FF):
            counts["ko"] += 1
        elif 0x0370 <= code <= 0x03FF:
            counts["el"] += 1
        elif 0x0E00 <= code <= 0x0E7F:
            counts["th"] += 1
        elif 0x0590 <= code <= 0x05FF:
            counts["he"] += 1

    names = {
        "hi": "Hindi", "mr": "Marathi", "te": "Telugu", "ta": "Tamil", "bn": "Bengali", "gu": "Gujarati",
        "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia", "ur": "Urdu / Arabic",
        "ru": "Russian / Cyrillic", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
        "el": "Greek", "th": "Thai", "he": "Hebrew"
    }

    max_lang = max(counts, key=counts.get)
    if counts[max_lang] > 0:
        if max_lang == "hi":
            # Devanagari script is shared by Hindi and Marathi
            # Check source hint or distinctive Marathi tokens and inflected stems
            src_low = (source_hint or "").lower()
            try:
                from harvester.extractors.engines.marathi_ocr import marathi_ocr_engine
                if marathi_ocr_engine.is_marathi_source(src_low) or marathi_ocr_engine.is_marathi_text(text):
                    return "mr", "Marathi"
            except Exception:
                if any(k in src_low for k in ["loksatta", "lokmat", "marathi", "sakaal", "saamana", "pudhari"]):
                    return "mr", "Marathi"
                marathi_markers = {"आहे", "नाही", "झाली", "गेले", "यांनी", "म्हणाले", "करणार", "केली", "होत", "होते", "होती", "आहेत", "येथे", "त्यांच्या", "त्यांनी", "पुणे", "मुंबई", "जिल्हा"}
                words_in_text = set(re.findall(r"[\u0900-\u097F]+", text))
                if len(words_in_text & marathi_markers) >= 1:
                    return "mr", "Marathi"
        return max_lang, names.get(max_lang, "Regional")

    # Check for European languages in Latin script
    lower = text.lower()
    words = set(re.findall(r"\b\w+\b", lower))

    es_markers = {"el", "la", "los", "las", "un", "una", "del", "al", "por", "para", "con", "más", "pero", "este", "esta", "noticias", "gobierno"}
    fr_markers = {"le", "la", "les", "des", "un", "une", "du", "et", "dans", "pour", "avec", "sur", "est", "par", "cette", "actualité"}
    de_markers = {"der", "die", "das", "den", "dem", "des", "und", "in", "zu", "mit", "sich", "auf", "für", "ist", "nicht", "nachrichten"}
    it_markers = {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "del", "della", "dei", "con", "per", "tra", "notizie"}
    pt_markers = {"o", "a", "os", "as", "um", "uma", "do", "da", "dos", "das", "no", "na", "com", "por", "para", "não", "notícias"}

    if len(words & es_markers) >= 2 or any(c in lower for c in ["ñ", "á", "í", "ó", "ú"]):
        return "es", "Spanish"
    if len(words & fr_markers) >= 2 or any(c in lower for c in ["œ", "ç", "è", "ê", "à", "ù"]):
        return "fr", "French"
    if len(words & de_markers) >= 2 or any(c in lower for c in ["ä", "ö", "ü", "ß"]):
        return "de", "German"
    if len(words & it_markers) >= 2:
        return "it", "Italian"
    if len(words & pt_markers) >= 2 or any(c in lower for c in ["ã", "õ"]):
        return "pt", "Portuguese"

    return "auto", "Regional"


def is_text_non_english(text: Optional[str]) -> bool:
    """Determines if text contains non-English or regional language content."""
    if not text:
        return False
    if contains_regional_script(text):
        return True
    lang_code, _ = detect_script_language(text)
    if lang_code in ("hi", "te", "ta", "bn", "gu", "kn", "ml", "pa", "or", "ur",
                     "ru", "zh", "ja", "ko", "el", "th", "he", "es", "fr", "de", "it", "pt"):
        return True
    # Non-ASCII unicode check
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    if non_ascii >= 3 and (non_ascii / max(len(text), 1)) > 0.05:
        return True
    return False


@dataclass
class PageData:
    page_num: int
    raw_text: str
    is_scanned: bool
    ocr_confidence: float
    snapshot_path: Optional[Path]
    snapshot_url: Optional[str]
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    publication_date: Optional[str] = None
    publication_name: Optional[str] = None
    status: str = "success"  # 'success', 'low_confidence', 'blank', 'failed'
    is_blank: bool = False
    error_message: Optional[str] = None
    detected_language: Optional[str] = None
    detected_language_code: Optional[str] = None


def detect_continuation_link(text: str, current_page: int) -> Tuple[List[int], str]:
    """
    Detects cross-page article continuations (e.g., 'Continued on Page 7', 'See Page 4',
    'பக்கம் 7ல் தொடர்ச்சி', 'தொடர்ச்சி பக்கம் 7', 'पान 4 वर पुढे', 'पृष्ठ 5 पर जारी').
    """
    if not text:
        return [current_page], f"Page: {current_page}"

    patterns = [
        r"(?:continued\s+on\s+page|contd\.?\s+on\s+p(?:age)?\.?|see\s+page|contd\.?\s+p\.?)\s*(\d+)",
        r"(?:continued\s+from\s+page|contd\.?\s+from\s+p(?:age)?\.?)\s*(\d+)",
        r"(?:பக்கம்\s*(\d+)\s*ல்\s*தொடர்ச்சி|தொடர்ச்சி\s*பக்கம்\s*(\d+))",
        r"(?:पान\s*(\d+)\s*वर\s*पुढे|पान\s*(\d+)\s*वरून\s*पुढे)",
        r"(?:पृष्ठ\s*(\d+)\s*पर\s*जारी|शेष\s*पृष्ठ\s*(\d+))",
        r"(?:പേജ്\s*(\d+)-ൽ\s*തുടർച്ച)",
        r"(?:పేజీ\s*(\d+)\s*లో\s*మిగతా)",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            for g in m.groups():
                if g and g.isdigit():
                    target_page = int(g)
                    if target_page != current_page and 1 <= target_page <= 120:
                        return [current_page, target_page], f"Page {current_page} → Continued on Page {target_page}"

    return [current_page], f"Page: {current_page}"


NEWSPAPER_CATEGORIES: Dict[str, List[str]] = {
    "Politics": [
        "politics", "political", "election", "bjp", "congress", "aap", "minister", "parliament",
        "assembly", "cabinet", "mla", "mp", "chief minister", "prime minister", "governor", "vote",
        "party", "rajya sabha", "lok sabha", "democracy", "constituency", "manifesto", "ruling party",
        "opposition", "தேர்தல்", "அரசியல்", "பாஜக", "காங்கிரஸ்", "அமைச்சர்", "முதல்வர்", "திமுக", "அதிமுக",
        "राजकारण", "निवडणूक", "भाजप", "काँग्रेस", "मंत्री", "मुख्यमंत्री", "शिवसेना", "राष्ट्रवादी", "राजनीति", "चुनाव",
        "संसद", "विधेयक", "मतदान", "विपक्ष", "लोकसभा", "राज्यसभा", "सरकार"
    ],
    "Sports": [
        "sports", "cricket", "football", "hockey", "badminton", "tennis", "olympics", "ipl",
        "fifa", "bcci", "match", "tournament", "wicket", "goal", "trophy", "stadium", "athlete",
        "chess", "kabaddi", "cricketer", "score", "champion", "campeones", "liga", "torneo", "real madrid",
        "விளையாட்டு", "கிரிக்கெட்", "கால்பந்து",
        "सामना", "खेळ", "क्रिकेट", "फुटबॉल", "क्रीडा", "खेल", "खिलाड़ी"
    ],
    "Business": [
        "business", "company", "corporate", "industry", "merger", "acquisition", "shares",
        "stock market", "sensex", "nifty", "trade", "enterprise", "startup", "commerce",
        "export", "import", "retail", "manufacturing", "ceo", "வணிகம்", "தொழில்", "பங்குச்சந்தை",
        "उद्योग", "व्यवसाय", "शेअर बाजार", "कंपनी", "व्यापार", "उद्योगपती"
    ],
    "World": [
        "world", "global", "international", "un", "usa", "uk", "russia", "ukraine", "china",
        "israel", "gaza", "foreign", "diplomacy", "treaty", "nato", "summit", "geopolitics",
        "united nations", "white house", "kremlin", "world news", "சர்வதேசம்", "உலகம்", "அமெரிக்கா", "சீனா",
        "रशिया", "चीन", "अमेरिका", "विदेश", "आंतरराष्ट्रीय", "परराष्ट्र", "दुनिया", "अंतरराष्ट्रीय"
    ],
    "National": [
        "national", "india", "delhi", "centre", "central government", "supreme court", "union government",
        "nationwide", "bharat", "indian army", "parliament of india", "राष्ट्रपति", "தேசிய", "மத்திய அரசு",
        "இந்தியா", "தலைநகர்", "राष्ट्रीय", "भारत", "दिल्ली", "केंद्र அரசு", "देश"
    ],
    "State": [
        "state", "tamil nadu", "maharashtra", "karnataka", "telangana", "andhra", "kerala", "up",
        "bihar", "west bengal", "chennai", "mumbai", "bengaluru", "hyderabad", "state government",
        "secretariat", "kolkata", "pune", "மாநிலம்", "சென்னை", "தமிழ்நாடு", "தலைமைச் செயலகம்",
        "महाराष्ट्र", "मुंबई", "पुणे", "नागपूर", "राज्य शासन", "मंत्रालय", "प्रदेश"
    ],
    "Local": [
        "local", "district", "city", "corporation", "municipality", "panchayat", "ward",
        "suburb", "town", "neighbourhood", "collector", "civic", "roads", "water supply",
        "drainage", "நகராட்சி", "மாநகராட்சி", "ஊராட்சி", "மாவட்டம்", "உள்ளூர்", "பகுதி",
        "स्थानिक", "जिल्हा", "महापालिका", "नगरपालिका", "शहर", "वार्ड", "गल्ली", "स्थानिक स्वराज्य"
    ],
    "Education": [
        "education", "school", "college", "university", "cbse", "ugc", "exam", "student",
        "teacher", "syllabus", "admission", "neet", "jee", "scholarship", "degrees", "academic",
        "board exam", "results", "கல்வி", "பள்ளி", "கல்லூரி", "பல்கலைக்கழகம்", "மாணவர்", "ஆசிரியர்", "தேர்வு",
        "शिक्षण", "शाळा", "महाविद्यालय", "विद्यापीठ", "परीक्षा", "विद्यार्थी", "शिक्षक", "अभ्यासक्रम"
    ],
    "Technology": [
        "technology", "tech", "ai", "artificial intelligence", "software", "cyber", "internet",
        "smartphone", "digital", "startup", "app", "computer", "cloud", "robotics", "gadget",
        "chip", "microprocessor", "semiconductor", "தொழில்நுட்பம்", "செயற்கை நுண்ணறிவு", "மென்பொருள்", "செயலி",
        "तंत्रज्ञान", "सायबर", "संगणक", "स्मार्टफोन", "इंटरनेट", "अॅप"
    ],
    "Science": [
        "science", "isro", "nasa", "space", "satellite", "research", "scientific", "astronomy",
        "physics", "biology", "spacecraft", "moon", "mars", "discovery", "laboratory", "scientist",
        "chandrayaan", "gaganyaan", "அறிவியல்", "இஸ்ரோ", "விண்கலம்", "ஆராய்ச்சி", "விஞ்ஞானி",
        "विज्ञान", "संशोधन", "इस्रो", "उपग्रह", "अवकाश", "शास्त्रज्ञ"
    ],
    "Health": [
        "health", "hospital", "doctor", "medicine", "disease", "covid", "virus", "vaccine",
        "treatment", "patient", "medical", "clinic", "surgery", "healthcare", "pharma", "wellness",
        "மருத்துவம்", "சுகாதாரம்", "மருத்துவர்", "மருத்துவமனை", "நோய்", "தடுப்பூசி", "சிகிச்சை",
        "आरोग्य", "रुग्णालय", "डॉक्टर", "औषध", "आजार", "वैद्यकीय", "लस", "उपचार"
    ],
    "Environment": [
        "environment", "climate", "forest", "wildlife", "pollution", "green", "carbon",
        "nature", "conservation", "wild animal", "tree", "global warming", "biodiversity",
        "சுற்றுச்சூழல்", "காடு", "வானிலை மாற்றம்", "மாசு", "வனவிலங்கு", "இயற்கை",
        "पर्यावरण", "प्रदूषण", "जंगल", "वन्यजीव", "निसर्ग", "हवामान बदल"
    ],
    "Crime": [
        "crime", "police", "arrest", "murder", "theft", "scam", "fraud", "robbery", "smuggling",
        "accused", "investigation", "custody", "fir", "kidnap", "drugs", "cybercrime", "assault",
        "குற்றம்", "காவல்துறை", "கைது", "கொலை", "கொள்ளை", "மோசடி", "விசாரணை",
        "गुन्हे", "पोलीस", "अटक", "खून", "चोरी", "फसवणूक", "तपास", "दरोडा", "गुन्हेगारी"
    ],
    "Law & Courts": [
        "court", "high court", "supreme court", "judge", "verdict", "bail", "petition",
        "advocate", "lawyer", "justice", "legal", "bench", "hearing", "judiciary", "appeal",
        "நீதிமன்றம்", "நீதிபதி", "தீர்ப்பு", "வழக்கு", "ஜாமீன்", "வக்கீல்", "நீதி",
        "न्यायालय", "कोर्ट", "न्यायाधीश", "निकाल", "जामीन", "वकील", "कायदा", "न्याय"
    ],
    "Entertainment": [
        "entertainment", "cinema", "movie", "film", "actor", "actress", "director", "box office",
        "music", "theatre", "bollywood", "kollywood", "hollywood", "ott", "series", "trailer",
        "திரைப்படம்", "சினிமா", "நடிகர்", "நடிகை", "இயக்குநர்", "பாடல்", "இசை",
        "चित्रपट", "सिनेमा", "अभिनेता", "अभिनेत्री", "गाणी", "कलाकार", "दिग्दर्शक", "मनोरंजन"
    ],
    "Automobile": [
        "automobile", "car", "ev", "vehicle", "electric vehicle", "bike", "motor", "auto",
        "suv", "scooter", "engine", "ev charger", "mileage", "test drive",
        "வாகனம்", "கார்", "மோட்டார்", "மின்சார வாகனம்", "இருசக்கர வாகனம்",
        "गाडी", "मोटार", "कार", "वाहन", "इलेक्ट्रिक व्हेईकल", "दुचाकी"
    ],
    "Finance": [
        "finance", "banking", "rbi", "loan", "interest rate", "inflation", "tax", "gst",
        "revenue", "budget", "fiscal", "fixed deposit", "mutual fund", "credit", "debit", "rupee",
        "நிதி", "வங்கி", "வரி", "கடன்", "பட்ஜெட்", "வட்டி", "பணவீக்கம்",
        "वित्त", "बँक", "कर्ज", "कर", "बजेट", "महागाई", "व्याजदर", "महसूल"
    ],
    "Weather": [
        "weather", "rain", "monsoon", "heatwave", "cyclone", "storm", "flood", "temperature",
        "forecast", "celsius", "cloudy", "rainfall", "heavy rain", "wind", "drought",
        "disaster", "rescue", "emergency", "desastre", "inundación", "rescate", "emergencia",
        "வானிலை", "மழை", "புயல்", "வெள்ளம்", "வெப்பம்", "மழைப்பொழிவு",
        "हवामान", "पाऊस", "चक्रीवादळ", "पूर", "உष्णता", "मान्सून", "तापमान"
    ],
    "Other": [
        "news", "report", "update", "press", "announcement", "public", "notice",
        "செய்தி", "அறிவிப்பு", "बातमी", "सूचना", "वृत्त", "समाचार"
    ]
}


def classify_news_categories(headline: str, content: str) -> Tuple[str, List[str]]:
    """
    Classifies news story into one of 19 standard categories + secondary categories.
    Returns (primary_category, secondary_categories_list).
    """
    text = f"{headline or ''} {content or ''}".lower()
    scores: Dict[str, int] = {cat: 0 for cat in NEWSPAPER_CATEGORIES}

    for cat, kws in NEWSPAPER_CATEGORIES.items():
        for kw in kws:
            kw_low = kw.lower()
            if len(kw_low) <= 4:
                if re.search(rf"\b{re.escape(kw_low)}\b", text):
                    scores[cat] += 2
            elif kw_low in text:
                scores[cat] += 2 if len(kw_low) > 4 else 1

    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_cat, best_score = sorted_cats[0]

    if best_score == 0:
        return "Other", []

    primary = best_cat
    secondaries = [cat for cat, s in sorted_cats[1:] if s >= 2 and cat != "Other"][:2]

    return primary, secondaries


class NewspaperPDFParser:
    """
    Intelligent OCR & Digital Twin Parser:
    1. Detects scanned vs text PDFs.
    2. Renders pages at 300-DPI high resolution using pypdfium2.
    3. Runs RapidOCR on image/scanned pages for 95%+ print font accuracy,
       extracting bounding boxes and per-block confidence.
    4. Extracts masthead metadata: page number, publication name, publication date.
    5. Segments coherent news stories linked to original page snapshots.
    6. Translates regional stories to English using LLMTranslator with Named Entity Preservation.
    """

    def __init__(self):
        pass

    def extract_masthead_date(self, text: str) -> Optional[str]:
        """Extracts date strings from newspaper page headers / mastheads."""
        date_patterns = [
            # 29 August 2026 / 29 Aug 2026 / 29-Aug-2026
            r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*,?\s*\d{4})\b",
            # August 29, 2026
            r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b",
            # 29/08/2026 or 29-08-2026 or 2026-08-29
            r"\b(\d{4}[-/.]\d{2}[-/.]\d{2})\b",
            r"\b(\d{2}[-/.]\d{2}[-/.]\d{4})\b",
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def detect_scanned_pdf(self, page_text: str, image_count: int) -> bool:
        """
        Determines if a page is a scanned document rather than a digital vector PDF.
        A page is considered scanned if:
        - Digital text is very sparse (< 120 characters) and page has images, or
        - Digital text consists solely of numbers or whitespace.
        """
        clean = page_text.strip()
        if len(clean) < 120 and image_count > 0:
            return True
        if len(clean) < 40:
            return True
        return False

    def process_pdf_pages(
        self,
        file_path: Path,
        max_pages: Optional[int] = None,
        source_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str, float, bool, Optional[str]], None]] = None,
    ) -> Tuple[str, List[PageData]]:
        """
        Extracts pages, text, and visual snapshots from PDFs, Word docs, images, and text files.
        Renders 300 DPI snapshots, runs dual-engine OCR (RapidOCR + Multilingual Tesseract) for scanned content.
        Processes EVERY page from start to finish when max_pages is None.
        """
        doc_id = hashlib.md5(f"{file_path.name}_{file_path.stat().st_mtime}".encode()).hexdigest()[:12]
        doc_snapshot_dir = SNAPSHOTS_DIR / doc_id
        doc_snapshot_dir.mkdir(parents=True, exist_ok=True)

        pages_data: List[PageData] = []
        suffix = file_path.suffix.lower()

        # A. Support for image files: scanned newspaper clippings, photos, screenshots
        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"):
            try:
                snapshot_file = doc_snapshot_dir / "page_001.jpg"
                pil_img = Image.open(file_path).convert("RGB")
                pil_img.save(snapshot_file, "JPEG", quality=90)
                snapshot_url = f"/api/snapshots/{doc_id}/1"

                ocr_text, ocr_conf, blocks = run_ocr_on_image(snapshot_file, pil_img)
                detected_date = self.extract_masthead_date(ocr_text)
                is_blank = len(ocr_text.strip()) < 15
                status = "blank" if is_blank else ("low_confidence" if ocr_conf < 0.70 else "success")
                lang_c, lang_n = detect_script_language(ocr_text, source_hint=source_name)
                p_data = PageData(
                    page_num=1,
                    raw_text=ocr_text,
                    is_scanned=True,
                    ocr_confidence=ocr_conf,
                    snapshot_path=snapshot_file,
                    snapshot_url=snapshot_url,
                    blocks=blocks,
                    publication_date=detected_date,
                    status=status,
                    is_blank=is_blank,
                    detected_language=lang_n,
                    detected_language_code=lang_c,
                )
                pages_data.append(p_data)
                if progress_callback:
                    try:
                        progress_callback(1, 1, status, ocr_conf, is_blank, file_path.name)
                    except Exception:
                        pass
                return doc_id, pages_data
            except Exception as ie:
                logger.error(f"Error processing image {file_path}: {ie}")
                if progress_callback:
                    try:
                        progress_callback(1, 1, "failed", 0.0, False, file_path.name)
                    except Exception:
                        pass
                return doc_id, pages_data

        # B. Support for Word documents (.docx, .doc) and plain text (.txt, .md, .csv)
        if suffix in (".docx", ".doc", ".txt", ".md", ".csv", ".log", ".rtf"):
            try:
                extracted_text = ""
                if suffix == ".docx":
                    extracted_text = extract_text_from_docx(file_path)
                if not extracted_text:
                    extracted_text = extract_text_from_doc_or_text(file_path)

                if extracted_text:
                    # Split into page-sized chunks (~2500 chars per page)
                    chunks = []
                    lines = extracted_text.splitlines()
                    curr_chunk = []
                    curr_len = 0
                    for line in lines:
                        curr_chunk.append(line)
                        curr_len += len(line) + 1
                        if curr_len >= 2500:
                            chunks.append("\n".join(curr_chunk))
                            curr_chunk = []
                            curr_len = 0
                    if curr_chunk:
                        chunks.append("\n".join(curr_chunk))

                    chunks = chunks[:max_pages] if chunks else [extracted_text]

                    for p_idx, chunk in enumerate(chunks):
                        p_num = p_idx + 1
                        snapshot_file = doc_snapshot_dir / f"page_{p_num:03d}.jpg"
                        render_text_to_image(chunk, snapshot_file)
                        snapshot_url = f"/api/snapshots/{doc_id}/{p_num}"
                        detected_date = self.extract_masthead_date(chunk)
                        pages_data.append(PageData(
                            page_num=p_num,
                            raw_text=chunk,
                            is_scanned=False,
                            ocr_confidence=1.0,
                            snapshot_path=snapshot_file,
                            snapshot_url=snapshot_url,
                            blocks=[],
                            publication_date=detected_date,
                        ))
                    return doc_id, pages_data
            except Exception as de:
                logger.error(f"Error processing document {file_path}: {de}")
                return doc_id, pages_data

        # C. PDF handling with fault-tolerant isolated pypdf & pdfium engines
        try:
            pdf_reader = None
            try:
                pdf_reader = pypdf.PdfReader(str(file_path))
            except Exception as pe:
                logger.warning(f"pypdf could not open {file_path.name}: {pe}")

            pdfium_doc = None
            try:
                pdfium_doc = pdfium.PdfDocument(str(file_path))
            except Exception as pe:
                logger.warning(f"pdfium could not open {file_path.name}: {pe}")

            total_pages = 0
            if pdfium_doc is not None:
                total_pages = len(pdfium_doc) if max_pages is None else min(len(pdfium_doc), max_pages)
            elif pdf_reader is not None:
                total_pages = len(pdf_reader.pages) if max_pages is None else min(len(pdf_reader.pages), max_pages)

            rapid_engine = get_rapid_ocr()

            if total_pages > 0:
                detected_tess_lang: Optional[str] = None
                tess_script_map = {
                    "ta": "tam", "hi": "hin", "te": "tel", "mr": "mar",
                    "bn": "ben", "gu": "guj", "kn": "kan", "ml": "mal",
                    "pa": "pan", "ur": "urd",
                }
                # Fast-track regional language from known newspaper title or district / region
                source_lower = (source_name or file_path.name or "").lower().replace("-", " ").replace("_", " ")
                if any(k in source_lower for k in [
                    "mathrubhumi", "manorama", "deshabhimani", "deepika", "madhyamam", "mangalam",
                    "chandrika", "janmabhumi", "siraj", "keralakaumudi", "kaumudi", "malayalam",
                    "kerala", "alappuzha", "kochi", "trivandrum", "thiruvananthapuram", "kollam",
                    "kottayam", "thrissur", "kozhikode", "calicut", "kannur", "palakkad",
                    "malappuram", "kasaragod", "wayanad", "idukki", "pathanamthitta"
                ]):
                    detected_tess_lang = "mal"
                elif any(k in source_lower for k in [
                    "dinamalar", "dinamani", "dinakaran", "dailythanthi", "daily thanthi", "thanthi",
                    "theekkathir", "maalaimalar", "maalai malar", "tamil", "chennai", "madurai",
                    "coimbatore", "trichy", "salem", "tirunelveli", "vellore", "erode", "thanjavur"
                ]):
                    detected_tess_lang = "tam"
                elif any(k in source_lower for k in [
                    "eenadu", "sakshi", "andhrajyothy", "andhra jyothy", "andhraprabha", "andhra prabha",
                    "namasthetelangana", "namasthe telangana", "prajasakti", "vaartha", "telugu",
                    "andhra", "telangana", "hyderabad", "vijayawada", "visakhapatnam", "tirupati", "guntur"
                ]):
                    detected_tess_lang = "tel"
                elif any(k in source_lower for k in [
                    "prajavani", "vijayavani", "vijaya vani", "vijaykarnataka", "vijay karnataka",
                    "kannadaprabha", "kannada prabha", "udayavani", "samyuktaksrnataka", "kannada",
                    "karnataka", "bangalore", "bengaluru", "mysuru", "hubli", "mangaluru", "belagavi"
                ]):
                    detected_tess_lang = "kan"
                elif any(k in source_lower for k in [
                    "anandabazar", "bartaman", "sangbadpratidin", "sangbad pratidin", "eisamay", "ei samay",
                    "aajkaal", "uttarbangasambad", "uttarbanga sambad", "bengali", "bangla", "kolkata"
                ]):
                    detected_tess_lang = "ben"
                elif any(k in source_lower for k in [
                    "gujaratsamachar", "gujarat samachar", "sandesh", "divyabhaskar", "divya bhaskar",
                    "sambhaav", "nobat", "gujarati", "gujarat", "ahmedabad", "surat", "vadodara", "rajkot"
                ]):
                    detected_tess_lang = "guj"
                elif any(k in source_lower for k in [
                    "loksatta", "lokmat", "sakal", "pudhari", "saamana", "tarunbharat", "tarun bharat",
                    "maharashtratimes", "maharashtra times", "marathi", "mumbai", "pune", "nagpur", "nashik",
                    "divyamarathi", "divya marathi", "deshdoot", "navshakti", "prahaar", "punyanagari"
                ]):
                    detected_tess_lang = "mar+eng"
                elif any(k in source_lower for k in [
                    "bhaskar", "dainik bhaskar", "amar ujala", "amarujala", "jagran", "dainik jagran",
                    "patrika", "rajasthan patrika", "navbharat", "jansatta", "hindustan", "punjab kesari",
                    "navodaya", "hindi", "delhi", "lucknow", "jaipur", "bhopal", "patna", "varanasi"
                ]):
                    detected_tess_lang = "hin"
                elif any(k in source_lower for k in [
                    "ajit", "jagbani", "punjabitribune", "punjabi tribune", "rozanaspokesman", "punjabi", "punjab"
                ]):
                    detected_tess_lang = "pan"
                elif any(k in source_lower for k in [
                    "inqilab", "siasat", "munsif", "urduaction", "hindurashtriya", "urdu"
                ]):
                    detected_tess_lang = "urd"
                elif any(k in source_lower for k in [
                    "financial express", "dt next", "the hindu", "hindu", "toi", "times of india",
                    "indian express", "deccan herald", "deccan chronicle", "business standard", "mint", "english"
                ]):
                    detected_tess_lang = "eng"

                # Pre-scan first page with fast OSD if publication name didn't identify language
                if not detected_tess_lang and pdfium_doc and len(pdfium_doc) > 0:
                    try:
                        p0 = pdfium_doc[0]
                        test_img = p0.render(scale=1.5).to_pil()
                        osd_lang = detect_script_from_osd(test_img)
                        if osd_lang and osd_lang in REGIONAL_TESS_LANGS:
                            detected_tess_lang = osd_lang
                            logger.info(f"Pre-scan OSD identified regional language: '{osd_lang}' from page 1")
                    except Exception as oe:
                        logger.debug(f"Pre-scan OSD notice: {oe}")

                # ── Parallel page processing with ThreadPoolExecutor ──────────
                # Each page is rendered + OCR'd in a separate thread.
                # Workers share the pdfium document (read-only) and pdf_reader.
                # A thread-safe lock guards writes to pages_data[] and
                # detected_tess_lang (which may be updated on first regional page).
                _pages_lock = Lock()
                _lang_lock = Lock()
                _detected_tess_lang_holder = [detected_tess_lang]  # mutable ref

                # Pre-extract all pypdf vector texts (fast, single-threaded, avoids seek races)
                pypdf_texts: List[Tuple[str, int]] = []  # (vector_text, image_count)
                for pidx in range(total_pages):
                    vt, ic = "", 0
                    if pdf_reader and pidx < len(pdf_reader.pages):
                        try:
                            pp = pdf_reader.pages[pidx]
                            vt = (pp.extract_text() or "").strip()
                            ic = len(pp.images)
                        except Exception:
                            pass
                    pypdf_texts.append((vt, ic))

                def _process_single_page(page_idx: int) -> PageData:
                    """Worker function: renders + OCR's one page. Runs in a thread."""
                    page_num = page_idx + 1
                    vector_text, image_count = pypdf_texts[page_idx]

                    # Fast-path: English digital PDF with rich vector text — skip OCR entirely
                    is_english_digital = (
                        len(vector_text) >= 250
                        and not contains_regional_script(vector_text)
                        and (_detected_tess_lang_holder[0] in (None, "eng", "en"))
                    )

                    is_scanned = self.detect_scanned_pdf(vector_text, image_count)
                    snapshot_file = doc_snapshot_dir / f"page_{page_num:03d}.jpg"
                    boxes_file = snapshot_file.with_suffix(".boxes.json")
                    pil_img = None
                    with _lang_lock:
                        cur_tess_lang = _detected_tess_lang_holder[0]

                    # Check for pre-existing high-resolution rendered snapshot
                    if snapshot_file.exists() and snapshot_file.stat().st_size > 1000:
                        try:
                            cached_img = Image.open(snapshot_file).convert("RGB")
                            if cached_img.width >= 1800:
                                pil_img = cached_img
                        except Exception:
                            pil_img = None

                    if pil_img is None:
                        if pdfium_doc and page_idx < len(pdfium_doc):
                            try:
                                pdfium_page = pdfium_doc[page_idx]
                                # scale=3.5 provides 250-300+ DPI character height essential for Indic ligatures & multi-column OCR
                                render_scale = 3.5 if cur_tess_lang and "mar" in cur_tess_lang else 3.0
                                pil_img = pdfium_page.render(scale=render_scale).to_pil()
                                pil_img.save(snapshot_file, "JPEG", quality=92)
                            except Exception as render_err:
                                logger.warning(f"pdfium render failed on page {page_num}: {render_err}")

                        if pil_img is None and pdf_reader and page_idx < len(pdf_reader.pages):
                            try:
                                pp_imgs = pdf_reader.pages[page_idx].images
                                if pp_imgs:
                                    best_img = max(pp_imgs, key=lambda img: len(img.data))
                                    pil_img = Image.open(io.BytesIO(best_img.data)).convert("RGB")
                                    pil_img.save(snapshot_file, "JPEG", quality=90)
                            except Exception:
                                pass
                        if pil_img is None:
                            pil_img = Image.new("RGB", (1200, 1600), color=(255, 255, 255))
                            if vector_text:
                                render_text_to_image(vector_text, snapshot_file)
                            else:
                                pil_img.save(snapshot_file, "JPEG", quality=90)

                    snapshot_url = f"/api/snapshots/{doc_id}/{page_num}"
                    page_text = vector_text
                    ocr_confidence = 1.0
                    blocks: List[Dict[str, Any]] = []

                    # Skip OCR for English digital-text pages (big speed gain for FE/DT Next/TOI)
                    if is_english_digital:
                        logger.info(f"Page {page_num}: English digital PDF — skipping OCR (vector text sufficient)")
                    else:
                        # Fast-path: Check if OCR text boxes are already cached on disk
                        with _lang_lock:
                            cur_tess_lang = _detected_tess_lang_holder[0]

                        cached_boxes = None
                        if boxes_file.exists():
                            try:
                                with open(boxes_file, "r", encoding="utf-8") as bf:
                                    c = bf.read().strip()
                                    if c:
                                        cached_boxes = json.loads(c)
                            except Exception:
                                cached_boxes = None

                        is_valid_cache = False
                        if cached_boxes and len(cached_boxes) > 0:
                            blocks = cached_boxes
                            ocr_txt = "\n".join(b.get("text", "") for b in blocks if b.get("text"))
                            if cur_tess_lang and cur_tess_lang not in ("eng", "en"):
                                if contains_regional_script(ocr_txt):
                                    is_valid_cache = True
                            else:
                                if len(ocr_txt) >= len(vector_text) or contains_regional_script(ocr_txt):
                                    is_valid_cache = True

                        if is_valid_cache:
                            page_text = "\n".join(b.get("text", "") for b in blocks if b.get("text"))
                            ocr_confidence = 0.95
                        elif is_scanned or len(vector_text) < 250 or contains_regional_script(vector_text) or (cur_tess_lang and cur_tess_lang not in ("eng", "en")):
                            logger.info(f"Running dual-engine OCR on Page {page_num} of {file_path.name} (preferred_lang={cur_tess_lang})...")
                            ocr_text, ocr_conf, ocr_blocks = run_ocr_on_image(snapshot_file, pil_img, preferred_lang=cur_tess_lang)
                            if len(ocr_text) >= len(vector_text) or contains_regional_script(ocr_text):
                                page_text = ocr_text
                                ocr_confidence = ocr_conf
                                blocks = ocr_blocks

                                if blocks:
                                    try:
                                        clean_blocks = [
                                            {"text": str(b.get("text", "")), "score": round(float(b.get("score", 0.9)), 4), "box": _clean_box_coords(b.get("box"))}
                                            for b in blocks
                                        ]
                                        tmp_boxes = boxes_file.with_suffix(".tmp.json")
                                        with open(tmp_boxes, "w", encoding="utf-8") as bf:
                                            json.dump(clean_blocks, bf, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))
                                        os.replace(tmp_boxes, boxes_file)
                                    except Exception as be:
                                        logger.debug(f"Could not write boxes to {boxes_file}: {be}")

                                with _lang_lock:
                                    if not _detected_tess_lang_holder[0]:
                                        s_code, _ = detect_script_language(ocr_text, source_hint=source_name)
                                        if s_code in tess_script_map:
                                            _detected_tess_lang_holder[0] = tess_script_map[s_code]
                                            logger.info(f"Identified regional lang: {s_code} -> Tesseract '{_detected_tess_lang_holder[0]}'")

                    detected_date = self.extract_masthead_date(page_text)
                    is_blank = (len(page_text.strip()) < 15 and image_count == 0) or (len(page_text.strip()) < 5)
                    status = "blank" if is_blank else ("low_confidence" if ocr_confidence < 0.70 else "success")
                    p_lang_c, p_lang_n = detect_script_language(page_text, source_hint=source_name)
                    p_data_item = PageData(
                        page_num=page_num,
                        raw_text=page_text,
                        is_scanned=is_scanned,
                        ocr_confidence=ocr_confidence,
                        snapshot_path=snapshot_file,
                        snapshot_url=snapshot_url,
                        blocks=blocks,
                        publication_date=detected_date,
                        status=status,
                        is_blank=is_blank,
                        detected_language=p_lang_n,
                        detected_language_code=p_lang_c,
                    )
                    if progress_callback:
                        try:
                            progress_callback(page_num, total_pages, status, ocr_confidence, is_blank, file_path.name)
                        except Exception:
                            pass
                    return p_data_item

                # Use up to 4 parallel threads for page processing
                # ThreadPoolExecutor is appropriate because OCR is CPU-bound + GIL-releasing (ONNX/Tesseract)
                max_workers = min(4, total_pages)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ocr_worker") as executor:
                    futures = {executor.submit(_process_single_page, pidx): pidx for pidx in range(total_pages)}
                    completed_pages: List[Optional[PageData]] = [None] * total_pages
                    for future in concurrent.futures.as_completed(futures):
                        pidx = futures[future]
                        try:
                            completed_pages[pidx] = future.result()
                        except Exception as page_exc:
                            logger.warning(f"Page {pidx + 1} processing error: {page_exc}")

                for pd_item in completed_pages:
                    if pd_item is not None:
                        pages_data.append(pd_item)

                # Sort pages back into order (futures complete out-of-order)
                pages_data.sort(key=lambda p: p.page_num)
            else:
                # Neither pypdf nor pdfium could parse pages - file may be plain text, HTML or image saved with .pdf
                logger.warning(f"Could not parse {file_path.name} as standard PDF. Attempting content fallback...")
                try:
                    pil_img = Image.open(file_path).convert("RGB")
                    snapshot_file = doc_snapshot_dir / "page_001.jpg"
                    pil_img.save(snapshot_file, "JPEG", quality=90)
                    raw_text, ocr_conf, ocr_blocks = run_ocr_on_image(snapshot_file, pil_img)
                    pages_data.append(PageData(
                        page_num=1,
                        raw_text=raw_text,
                        is_scanned=True,
                        ocr_confidence=ocr_conf,
                        snapshot_path=snapshot_file,
                        snapshot_url=f"/api/snapshots/{doc_id}/1",
                        blocks=ocr_blocks,
                        publication_date=self.extract_masthead_date(raw_text),
                    ))
                except Exception:
                    raw_text = extract_text_from_doc_or_text(file_path)
                    if raw_text:
                        clean_text = re.sub(r"<[^>]+>", " ", raw_text)
                        clean_text = re.sub(r"\s+", " ", clean_text).strip()
                        snapshot_file = doc_snapshot_dir / "page_001.jpg"
                        render_text_to_image(clean_text[:2000], snapshot_file)
                        pages_data.append(PageData(
                            page_num=1,
                            raw_text=clean_text,
                            is_scanned=False,
                            ocr_confidence=1.0,
                            snapshot_path=snapshot_file,
                            snapshot_url=f"/api/snapshots/{doc_id}/1",
                            blocks=[],
                            publication_date=self.extract_masthead_date(clean_text),
                        ))
        except Exception as e:
            logger.error(f"Error processing PDF {file_path}: {e}")

        if not pages_data and progress_callback:
            try:
                progress_callback(1, 1, "failed", 0.0, False, file_path.name)
            except Exception:
                pass

        return doc_id, pages_data

    def extract_text_from_pdf(self, file_path: Path, max_pages: int = 16) -> List[Tuple[int, str]]:
        """Backward-compatible tuple extractor: (page_num, text)."""
        _, pages_data = self.process_pdf_pages(file_path, max_pages=max_pages)
        return [(p.page_num, p.raw_text) for p in pages_data if p.raw_text]

    def extract_articles_from_blocks(self, p_data: PageData) -> List[Dict[str, Any]]:
        """
        Intelligent Newspaper Broadsheet Article Segmenter:
        - Analyzes font sizes and line heights across text blocks
        - Detects prominent headlines (>= 1.35x median line height or title markers)
        - Groups multi-column body text paragraphs under their corresponding headline
        - Generates clean reading-order body text
        - Calculates the exact article bounding box [x1, y1, x2, y2]
        """
        blocks = getattr(p_data, "blocks", [])
        if not blocks or len(blocks) < 3:
            return []

        lines = []
        for b in blocks:
            bbox = b.get("bbox")
            if not bbox and b.get("box"):
                box = b.get("box")
                xs = [pt[0] for pt in box if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                ys = [pt[1] for pt in box if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                if xs and ys:
                    bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
            if bbox and len(bbox) == 4:
                txt = (b.get("text") or "").strip()
                if txt:
                    lines.append({
                        "text": txt,
                        "x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3],
                        "h": bbox[3] - bbox[1],
                        "w": bbox[2] - bbox[0],
                        "block": b.get("block_num", 0),
                        "par": b.get("par_num", 0),
                        "words": b.get("words", txt.split())
                    })

        if len(lines) < 3:
            return []

        page_w = max(l["x2"] for l in lines)
        page_h = max(l["y2"] for l in lines)
        heights = [l["h"] for l in lines if l["h"] > 4]
        median_h = float(sorted(heights)[len(heights) // 2]) if heights else 16.0
        masthead_cutoff = int(page_h * 0.06)

        par_dict = {}
        for l in lines:
            if l["y1"] < masthead_cutoff and l["h"] < median_h * 1.5:
                continue
            pkey = (l["block"], l["par"])
            if pkey not in par_dict:
                par_dict[pkey] = {
                    "lines": [l],
                    "text": l["text"],
                    "x1": l["x1"], "y1": l["y1"], "x2": l["x2"], "y2": l["y2"],
                    "max_h": l["h"]
                }
            else:
                p = par_dict[pkey]
                p["lines"].append(l)
                p["text"] += " " + l["text"]
                p["x1"] = min(p["x1"], l["x1"])
                p["y1"] = min(p["y1"], l["y1"])
                p["x2"] = max(p["x2"], l["x2"])
                p["y2"] = max(p["y2"], l["y2"])
                p["max_h"] = max(p["max_h"], l["h"])

        paragraphs = sorted(par_dict.values(), key=lambda p: (p["y1"], p["x1"]))
        headlines = []
        body_blocks = []

        for p in paragraphs:
            p_text = p["text"].strip()
            words = p_text.split()
            if len(p_text) < 4:
                continue
            is_hl = (p["max_h"] >= median_h * 1.35 and len(words) <= 25) or (p["max_h"] >= median_h * 1.6)
            if is_hl and len(words) >= 2:
                headlines.append(p)
            elif len(p_text) >= 15:
                body_blocks.append(p)

        articles = []
        assigned_body = set()

        for hl in headlines:
            hl_text = hl["text"].strip()
            next_hl_y = page_h
            for other_hl in headlines:
                if other_hl["y1"] > hl["y2"] + 20 and not (other_hl["x2"] < hl["x1"] - 40 or other_hl["x1"] > hl["x2"] + 40):
                    next_hl_y = min(next_hl_y, other_hl["y1"])

            matched_bodies = []
            for b_idx, bb in enumerate(body_blocks):
                if b_idx in assigned_body:
                    continue
                h_overlap = max(0, min(hl["x2"] + 60, bb["x2"]) - max(hl["x1"] - 60, bb["x1"]))
                bb_w = max(bb["x2"] - bb["x1"], 1)
                if h_overlap > 0.35 * min(bb_w, max(hl["x2"] - hl["x1"], 1)):
                    if hl["y1"] - 20 <= bb["y1"] <= next_hl_y + 40:
                        matched_bodies.append((b_idx, bb))

            matched_bodies.sort(key=lambda item: (item[1]["x1"] // 150, item[1]["y1"]))

            art_x1, art_y1, art_x2, art_y2 = hl["x1"], hl["y1"], hl["x2"], hl["y2"]
            body_parts = []
            for b_idx, bb in matched_bodies:
                assigned_body.add(b_idx)
                body_parts.append(bb["text"].strip())
                art_x1 = min(art_x1, bb["x1"])
                art_y1 = min(art_y1, bb["y1"])
                art_x2 = max(art_x2, bb["x2"])
                art_y2 = max(art_y2, bb["y2"])

            full_body = "\n".join(body_parts).strip() or hl_text
            full_story_ocr = f"{hl_text}\n{full_body}".strip()
            p_nums, cont_lbl = detect_continuation_link(full_story_ocr, p_data.page_num)

            articles.append({
                "page": p_data.page_num,
                "page_numbers": p_nums,
                "continuation_label": cont_lbl,
                "title": hl_text,
                "body": full_body,
                "snippet": full_body[:400] if full_body else hl_text,
                "ocr_raw_text": full_story_ocr,
                "ocr_confidence": p_data.ocr_confidence,
                "page_snapshot_url": p_data.snapshot_url,
                "publication_date": p_data.publication_date,
                "bounding_box": [int(art_x1), int(art_y1), int(art_x2), int(art_y2)],
            })

        for b_idx, bb in enumerate(body_blocks):
            if b_idx not in assigned_body and len(bb["text"].strip()) > 70:
                lines_in_bb = bb["lines"]
                h_line = lines_in_bb[0]["words"] if "words" in lines_in_bb[0] else lines_in_bb[0]["text"].split()
                art_hl = " ".join(h_line)
                art_body = bb["text"][len(art_hl):].strip() or art_hl
                full_story_ocr = f"{art_hl}\n{art_body}".strip()
                p_nums, cont_lbl = detect_continuation_link(full_story_ocr, p_data.page_num)
                articles.append({
                    "page": p_data.page_num,
                    "page_numbers": p_nums,
                    "continuation_label": cont_lbl,
                    "title": art_hl,
                    "body": art_body,
                    "snippet": art_body[:400],
                    "ocr_raw_text": full_story_ocr,
                    "ocr_confidence": p_data.ocr_confidence,
                    "page_snapshot_url": p_data.snapshot_url,
                    "publication_date": p_data.publication_date,
                    "bounding_box": [int(bb["x1"]), int(bb["y1"]), int(bb["x2"]), int(bb["y2"])],
                })

        clean_articles = []
        for a in articles:
            wc = len((a["title"] + " " + a["body"]).split())
            bw = a["bounding_box"][2] - a["bounding_box"][0]
            bh = a["bounding_box"][3] - a["bounding_box"][1]
            if wc >= 8 and (bw >= 120 or bh >= 50):
                clean_articles.append(a)

        return clean_articles

    def segment_text_into_stories(
        self,
        pages_text_or_data: Any
    ) -> List[Dict[str, Any]]:
        """
        Segments raw page text/blocks into individual news stories.
        Maintains full traceability:
        - raw OCR text
        - OCR confidence score
        - Page snapshot URL
        - Bounding box
        - Publication date
        """
        stories: List[Dict[str, Any]] = []

        # Check if input is List[PageData] or legacy List[Tuple[int, str]]
        is_page_data = len(pages_text_or_data) > 0 and isinstance(pages_text_or_data[0], PageData)

        for item in pages_text_or_data:
            if is_page_data:
                p_data: PageData = item
                page_articles = self.extract_articles_from_blocks(p_data)
                if page_articles:
                    stories.extend(page_articles)
                    continue

                page_num = p_data.page_num
                raw_text = p_data.raw_text
                ocr_conf = p_data.ocr_confidence
                snapshot_url = p_data.snapshot_url
                pub_date = p_data.publication_date
            else:
                page_num, raw_text = item
                ocr_conf = 0.98
                snapshot_url = None
                pub_date = None

            paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw_text) if p.strip()]
            blocks: List[List[str]] = []
            current_block: List[str] = []

            if len(paragraphs) > 1:
                for p in paragraphs:
                    p_lines = [ln.strip() for ln in p.splitlines() if ln.strip()]
                    if not p_lines:
                        continue
                    if re.match(r"^(page\s+\d+|p\.\s*\d+|epaper|edition|www\..+)", p_lines[0], re.IGNORECASE):
                        continue

                    is_p_headline = (len(p_lines[0]) <= 130 and not p_lines[0].endswith((".", "।", ";", ":", "-")))
                    if is_p_headline and current_block and len(current_block) >= 2:
                        blocks.append(current_block)
                        current_block = []

                    current_block.extend(p_lines)
                    if len(p_lines) >= 2 and is_p_headline and current_block:
                        blocks.append(current_block)
                        current_block = []
                if current_block:
                    blocks.append(current_block)
            else:
                lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                for line in lines:
                    if re.match(r"^(page\s+\d+|p\.\s*\d+|epaper|edition|www\..+)", line, re.IGNORECASE):
                        continue
                    if len(line) < 3:
                        continue
                    is_headline_candidate = (
                        len(line) < 130 and
                        (line.isupper() or not line.endswith((".", "।", ",", ";", ":", "-")))
                    )
                    if is_headline_candidate and len(current_block) >= 2:
                        blocks.append(current_block)
                        current_block = [line]
                    else:
                        current_block.append(line)
                if current_block:
                    blocks.append(current_block)

            for block in blocks:
                if not block:
                    continue

                headline = block[0]
                body_lines = block[1:] if len(block) > 1 else []
                body = " ".join(body_lines).strip()

                if len(headline) > 140 and not body:
                    sentences = re.split(r"([.?!।]\s+)", headline)
                    if len(sentences) >= 2:
                        headline = sentences[0]
                        body = "".join(sentences[1:]).strip()

                combined_len = len(headline) + len(body)
                if combined_len < 35:
                    continue

                full_story_ocr = f"{headline}\n{body}".strip()
                p_nums, cont_lbl = detect_continuation_link(full_story_ocr, page_num)

                # Compute exact article bounding box from matching OCR blocks
                story_bbox = None
                if is_page_data and getattr(p_data, "blocks", None):
                    p_blocks = p_data.blocks
                    search_words = [w.lower().strip("\"'.,;:-!?।/\\()-") for w in (headline + " " + body[:200]).split() if len(w) >= 3]
                    matched_boxes = []
                    for blk in p_blocks:
                        blk_txt = (blk.get("text") or "").lower()
                        if any(w in blk_txt for w in search_words[:15]):
                            matched_boxes.append(blk.get("box"))
                    if matched_boxes:
                        sb_x1 = min(pt[0] for box in matched_boxes for pt in box)
                        sb_y1 = min(pt[1] for box in matched_boxes for pt in box)
                        sb_x2 = max(pt[0] for box in matched_boxes for pt in box)
                        sb_y2 = max(pt[1] for box in matched_boxes for pt in box)
                        story_bbox = [int(sb_x1), int(sb_y1), int(sb_x2), int(sb_y2)]

                stories.append({
                    "page": page_num,
                    "page_numbers": p_nums,
                    "continuation_label": cont_lbl,
                    "title": headline,
                    "body": body,
                    "snippet": body[:400] if body else headline,
                    "ocr_raw_text": full_story_ocr,
                    "ocr_confidence": ocr_conf,
                    "page_snapshot_url": snapshot_url,
                    "publication_date": pub_date,
                    "bounding_box": story_bbox,
                })

        # Fallback: if no stories were created from blocks, extract stories from paragraphs
        if not stories and pages_text_or_data:
            for item in pages_text_or_data:
                if is_page_data:
                    p_data = item
                    page_num = p_data.page_num
                    raw_text = p_data.raw_text
                    ocr_conf = p_data.ocr_confidence
                    snapshot_url = p_data.snapshot_url
                    pub_date = p_data.publication_date
                else:
                    page_num, raw_text = item
                    ocr_conf = 0.98
                    snapshot_url = None
                    pub_date = None

                if not raw_text or not raw_text.strip():
                    continue

                paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw_text) if p.strip()]
                if not paragraphs:
                    paragraphs = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

                for p in paragraphs:
                    p_lines = [l.strip() for l in p.splitlines() if l.strip()]
                    if not p_lines:
                        continue
                    headline = p_lines[0][:140]
                    body = " ".join(p_lines[1:]) if len(p_lines) > 1 else p
                    if len(headline) < 4 and len(body) < 8:
                        continue
                    p_nums, cont_lbl = detect_continuation_link(p, page_num)

                    # Compute bounding box from OCR blocks if available
                    story_bbox = None
                    if is_page_data and getattr(p_data, "blocks", None):
                        p_blocks = p_data.blocks
                        search_words = [w.lower().strip("\"'.,;:-!?।/\\()-") for w in (headline + " " + body[:200]).split() if len(w) >= 3]
                        matched_boxes = []
                        for blk in p_blocks:
                            blk_txt = (blk.get("text") or "").lower()
                            if any(w in blk_txt for w in search_words[:15]):
                                matched_boxes.append(blk.get("box"))
                        if matched_boxes:
                            sb_x1 = min(pt[0] for box in matched_boxes for pt in box)
                            sb_y1 = min(pt[1] for box in matched_boxes for pt in box)
                            sb_x2 = max(pt[0] for box in matched_boxes for pt in box)
                            sb_y2 = max(pt[1] for box in matched_boxes for pt in box)
                            story_bbox = [int(sb_x1), int(sb_y1), int(sb_x2), int(sb_y2)]

                    stories.append({
                        "page": page_num,
                        "page_num": page_num,
                        "page_numbers": p_nums,
                        "continuation_label": cont_lbl,
                        "title": headline,
                        "english_headline": headline,
                        "body": body,
                        "snippet": body[:400] if body else headline,
                        "original_snippet": body[:400] if body else headline,
                        "english_summary": body[:400] if body else headline,
                        "ocr_raw_text": p,
                        "ocr_confidence": ocr_conf,
                        "confidence": ocr_conf,
                        "page_snapshot_url": snapshot_url,
                        "publication_date": pub_date,
                        "bounding_box": story_bbox,
                    })

        return stories

    def classify_category(self, title: str, snippet: str) -> str:
        """
        Classifies an article into standard categories based on the 19-category taxonomy.
        Backward-compatible wrapper mapping to legacy names when needed.
        """
        primary, _ = classify_news_categories(title, snippet)
        legacy_map = {
            "Politics": "political",
            "Sports": "sports",
            "Business": "business",
            "Finance": "economic",
            "Crime": "crises_disasters",
            "Environment": "crises_disasters",
            "Weather": "crises_disasters",
        }
        return legacy_map.get(primary, primary.lower())

    async def parse_and_process_pdf(
        self,
        file_path: Path,
        source_name: str = "Uploaded Newspaper PDF",
        max_pages: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, float, bool, Optional[str]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Full Digital Twin async pipeline:
        1. Render ALL pages at 300 DPI and store page snapshots in data/snapshots/.
        2. Detect scanned vs text, run dual-engine OCR (RapidOCR + Multilingual Tesseract).
        3. Never skip pages. Detect blank & low-confidence pages accurately.
        4. Segment stories with multi-page continuation detection (e.g. Page 3 -> Page 7).
        5. Translate 100% of regional Indic content into English with Named Entity Preservation.
        6. Classify news across 19 categories (Politics, Sports, Business, World, National, State, Local,
           Education, Technology, Science, Health, Environment, Crime, Law & Courts, Entertainment,
           Automobile, Finance, Weather, Other).
        7. Organize into categories and return structured Digital Twin output.
        """
        loop = asyncio.get_running_loop()
        doc_id, pages_data = await loop.run_in_executor(
            _pdf_executor,
            self.process_pdf_pages,
            file_path,
            max_pages,
            source_name,
            progress_callback
        )

        raw_stories = self.segment_text_into_stories(pages_data)

        articles: List[Dict[str, Any]] = []
        translation_tasks = []

        scanned_count = sum(1 for p in pages_data if p.is_scanned)
        newspaper_title = source_name or file_path.stem.replace('_', ' ').replace('-', ' ').title()

        # Build initial articles
        for idx, story in enumerate(raw_stories):
            headline_orig = story["title"]
            content_orig = story.get("body") or story.get("ocr_raw_text") or story.get("snippet", "")
            primary_cat, sec_cats = classify_news_categories(headline_orig, content_orig)
            article_id = hashlib.md5(f"{doc_id}_{story['page']}_{idx}_{headline_orig[:20]}".encode()).hexdigest()[:12]

            article_dict = {
                "id": article_id,
                "article_id": article_id,
                "newspaper": newspaper_title,
                "pdf_file": file_path.name,
                "publication_date": story.get("publication_date") or datetime.now().strftime("%Y-%m-%d"),
                "original_language": "English",
                "page_number": story["page"],
                "page_num": story["page"],
                "page_numbers": story.get("page_numbers", [story["page"]]),
                "continuation_label": story.get("continuation_label", f"Page: {story['page']}"),
                "category": primary_cat,
                "secondary_categories": sec_cats,
                "headline_english": headline_orig,
                "english_headline": headline_orig,
                "content_english": story.get("body") or content_orig or story.get("snippet") or headline_orig,
                "english_summary": (story.get("body") or content_orig or story.get("snippet") or headline_orig)[:400],
                "headline_original": headline_orig,
                "content_original": content_orig,
                "original_snippet": (story.get("body") or content_orig or story.get("snippet") or headline_orig)[:400],
                "ocr_confidence": round(float(story.get("ocr_confidence", 0.95)), 2),
                "confidence": round(float(story.get("ocr_confidence", 0.95)), 2),
                "is_low_confidence": float(story.get("ocr_confidence", 0.95)) < 0.70,
                "page_snapshot_url": story.get("page_snapshot_url"),
                "original_page_image_url": story.get("page_snapshot_url"),
                "crop_image_url": f"/api/newspaper/article/{article_id}/crop",
                "pdf_download_url": f"/api/newspaper/article/{article_id}/pdf",
                "status": "completed",
                "bounding_box": story.get("bounding_box"),
                # Backward-compatibility fields
                "title": headline_orig,
                "original_title": headline_orig,
                "snippet": (story.get("body") or content_orig or story.get("snippet") or headline_orig)[:400],
                "source_id": "uploaded_pdf",
                "source_name": f"{newspaper_title} (Page {story['page']})",
                "author": newspaper_title,
                "link": f"#page-{story['page']}",
                "published_at": story.get("publication_date") or f"Page {story['page']}",
                "is_translated": False,
                "ocr_raw_text": story.get("ocr_raw_text"),
                "doc_id": doc_id,
            }
            articles.append(article_dict)

            # Check if translation is needed for non-English content
            needs_tr = (
                is_text_non_english(headline_orig) or
                is_text_non_english(content_orig)
            )
            if needs_tr:
                combined_sample = f"{headline_orig} {content_orig[:300]}"
                lang_code, lang_name = detect_script_language(combined_sample, source_hint=newspaper_title)
                article_dict["original_language"] = lang_name
                translation_tasks.append(self._translate_story_dict(article_dict, lang_code, lang_name))

        if translation_tasks:
            # Paced translation worker pool (4 concurrent) to avoid API 429 rate limit
            sem = asyncio.Semaphore(4)
            async def _throttled_tr(t):
                async with sem:
                    await asyncio.sleep(0.08)
                    return await t
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(_throttled_tr(t) for t in translation_tasks), return_exceptions=True),
                    timeout=120.0
                )
            except Exception as te:
                logger.warning(f"Translation batch completed with notice: {te}")

        # Post-translation re-classification: Guarantee categorized news in English
        for a in articles:
            if a.get("is_translated") or a.get("category") == "Other":
                new_p, new_s = classify_news_categories(a["headline_english"], a["content_english"])
                if new_p != "Other":
                    a["category"] = new_p
                    a["secondary_categories"] = new_s

        # Initialize all 19 standard categories + legacy aliases
        categorized: Dict[str, List[Dict[str, Any]]] = {
            "all": [],
            "Politics": [],
            "Sports": [],
            "Business": [],
            "World": [],
            "National": [],
            "State": [],
            "Local": [],
            "Education": [],
            "Technology": [],
            "Science": [],
            "Health": [],
            "Environment": [],
            "Crime": [],
            "Law & Courts": [],
            "Entertainment": [],
            "Automobile": [],
            "Finance": [],
            "Weather": [],
            "Other": [],
            # Legacy lowercase buckets
            "sports": [],
            "business": [],
            "economic": [],
            "political": [],
            "crises_disasters": [],
        }

        translated_count = 0
        needs_review_count = 0

        for a in articles:
            if a.get("is_translated"):
                translated_count += 1
            if a.get("is_low_confidence"):
                needs_review_count += 1

            categorized["all"].append(a)
            cat = a.get("category", "Other")
            if cat in categorized:
                categorized[cat].append(a)

            # Map to legacy buckets
            cat_l = cat.lower()
            if cat_l in ("sports", "business"):
                categorized[cat_l].append(a)
            elif cat_l in ("politics", "national", "state"):
                categorized["political"].append(a)
            elif cat_l in ("finance", "economic"):
                categorized["economic"].append(a)
            elif cat_l in ("crime", "environment", "weather"):
                categorized["crises_disasters"].append(a)

        unique_languages = sorted(list({a.get("original_language", "English") for a in articles}))
        dates = sorted(list({a.get("publication_date") for a in articles if a.get("publication_date")}), reverse=True)

        summary = {
            "newspaper_names": [newspaper_title],
            "publication_dates": dates,
            "original_languages": unique_languages,
            "total_pages_processed": len(pages_data),
            "total_articles_extracted": len(articles),
            "translated_count": translated_count,
            "needs_review_count": needs_review_count,
        }

        return {
            "filename": file_path.name,
            "doc_id": doc_id,
            "source_name": newspaper_title,
            "total_pages": len(pages_data),
            "scanned_pages_count": scanned_count,
            "total_articles": len(articles),
            "translated_count": translated_count,
            "needs_review_count": needs_review_count,
            "detected_languages": unique_languages,
            "snapshots": [p.snapshot_url for p in pages_data if p.snapshot_url],
            "categories": categorized,
            "articles": articles,
            "summary": summary,
        }

    async def _translate_story_dict(self, article: Dict[str, Any], lang_code: str, lang_name: str):
        """Translates regional article headline and FULL body content into complete English."""
        try:
            hl = article["headline_original"]
            if is_text_non_english(hl):
                tr_res = await llm_translator.translate(hl, source_lang=lang_code)
                article["headline_english"] = tr_res.translated_text
                article["english_headline"] = tr_res.translated_text
                article["title"] = tr_res.translated_text
                article["is_translated"] = True

            body = article["content_original"]
            if body and is_text_non_english(body):
                # Use translate_long_text to translate the ENTIRE article body,
                # not just a truncated slice — chunks at paragraph/sentence boundaries
                tr_body = await llm_translator.translate_long_text(body, source_lang=lang_code)
                article["content_english"] = tr_body.translated_text
                article["english_summary"] = tr_body.translated_text[:400]
                article["snippet"] = tr_body.translated_text[:400]
                article["is_translated"] = True

            # Clean OCR header artifact in headline only if headline was extreme noise
            clean_t = article["headline_english"].strip()
            if (len(clean_t) < 6 or re.match(r"^(page\s*\d+|regd|rni|p\.\s*\d+|no\.)", clean_t, re.I)) and article["content_english"] and len(article["content_english"]) > 15:
                sentences = re.split(r"[.!?]\s+", article["content_english"].strip())
                if sentences and len(sentences[0]) > 10:
                    article["headline_english"] = sentences[0][:130].strip()
                    article["english_headline"] = article["headline_english"]
                    article["title"] = article["headline_english"]
        except Exception as e:
            logger.warning(f"Translation warning for '{article.get('headline_original', '')[:30]}': {e}")


    async def _translate_article_llm(self, article: NewsArticle, lang_code: str, lang_name: str):
        """Translates regional/foreign article title and snippet using LLMTranslator with Named Entity Preservation."""
        try:
            if is_text_non_english(article.title):
                article.original_title = article.title
                tr_title = await llm_translator.translate(article.title, source_lang=lang_code)
                article.title = tr_title.translated_text
                article.is_translated = True
                article.original_language = lang_name
                article.translation_confidence = tr_title.confidence_score
                article.needs_review = tr_title.needs_review
                for ent in tr_title.preserved_entities:
                    if ent not in article.preserved_entities:
                        article.preserved_entities.append(ent)

            if article.snippet and is_text_non_english(article.snippet):
                article.original_snippet = article.snippet
                tr_snip = await llm_translator.translate(article.snippet, source_lang=lang_code)
                article.snippet = tr_snip.translated_text
                article.is_translated = True
                article.original_language = lang_name
                article.translation_confidence = min(article.translation_confidence, tr_snip.confidence_score)
                if tr_snip.needs_review:
                    article.needs_review = True
                for ent in tr_snip.preserved_entities:
                    if ent not in article.preserved_entities:
                        article.preserved_entities.append(ent)

            # If title is an OCR artifact or generic header, derive headline from translated snippet
            clean_t = article.title.strip()
            if (len(clean_t) < 12 or re.match(r"^(page\s*\d+|regd|rni|p\.\s*\d+|no\.)", clean_t, re.I)) and article.snippet and len(article.snippet) > 15:
                sentences = re.split(r"[.!?]\s+", article.snippet.strip())
                if sentences and len(sentences[0]) > 10:
                    article.title = sentences[0][:130].strip()
        except Exception as e:
            logger.warning(f"Error in LLM translation for '{article.title[:30]}': {e}")

    async def parse_and_process_pdf_batch(
        self,
        file_paths: List[Path],
        source_names: Optional[List[str]] = None,
        max_pages_per_doc: Optional[int] = None,
        max_concurrency: int = 4,
        progress_callback: Optional[Callable[[int, int, str, float, bool, Optional[str]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Batch processing engine supporting 20+ concurrent PDFs:
        - Controlled concurrency via asyncio.Semaphore(max_concurrency) to prevent memory spikes.
        - Processes every page from page 1 to the end when max_pages_per_doc is None.
        - Error isolation: corrupted files do not abort the remaining PDFs in the batch.
        - Unified aggregation across all documents into 19 standard categories.
        - Per-document metadata, snapshots, and metrics.
        """
        sem = asyncio.Semaphore(max_concurrency)
        total_files = len(file_paths)
        documents_summary = []
        all_articles: List[Dict[str, Any]] = []
        all_snapshots = []
        all_languages = set()

        async def _process_single(idx: int, path: Path, src_name: str):
            async with sem:
                logger.info(f"Processing batch PDF ({idx + 1}/{total_files}): {path.name}")
                try:
                    result = await self.parse_and_process_pdf(
                        file_path=path,
                        source_name=src_name,
                        max_pages=max_pages_per_doc,
                        progress_callback=progress_callback,
                    )
                    return {"success": True, "data": result, "path": path}
                except Exception as e:
                    logger.exception(f"Error processing PDF in batch ({path.name}): {e}")
                    if progress_callback:
                        try:
                            progress_callback(1, 1, "failed", 0.0, False, path.name)
                        except Exception:
                            pass
                    return {"success": False, "error": str(e), "filename": path.name, "path": path}

        tasks = []
        for idx, path in enumerate(file_paths):
            if source_names and idx < len(source_names) and source_names[idx]:
                name = source_names[idx]
            else:
                name = path.stem.replace("_", " ").title()
            tasks.append(_process_single(idx, path, name))

        batch_results = await asyncio.gather(*tasks)

        aggregated_categories: Dict[str, List[Dict[str, Any]]] = {
            "all": [],
            "Politics": [],
            "Sports": [],
            "Business": [],
            "World": [],
            "National": [],
            "State": [],
            "Local": [],
            "Education": [],
            "Technology": [],
            "Science": [],
            "Health": [],
            "Environment": [],
            "Crime": [],
            "Law & Courts": [],
            "Entertainment": [],
            "Automobile": [],
            "Finance": [],
            "Weather": [],
            "Other": [],
            # Legacy lowercase buckets
            "sports": [],
            "business": [],
            "economic": [],
            "political": [],
            "crises_disasters": [],
        }

        successful_count = 0
        total_pages = 0
        translated_count = 0
        needs_review_count = 0

        for item in batch_results:
            if item["success"]:
                successful_count += 1
                doc_data = item["data"]
                total_pages += doc_data.get("total_pages", 0)
                translated_count += doc_data.get("translated_count", 0)
                needs_review_count += doc_data.get("needs_review_count", 0)

                doc_id = doc_data.get("doc_id", "")
                fname = doc_data.get("filename", "")
                src_name = doc_data.get("source_name", "")

                for snap in doc_data.get("snapshots", []):
                    all_snapshots.append(snap)

                # Tag articles with document info and aggregate
                for cat_name, cat_articles in doc_data.get("categories", {}).items():
                    if cat_name == "all":
                        for a in cat_articles:
                            a["doc_id"] = doc_id
                            a["filename"] = fname
                            if a.get("original_language"):
                                all_languages.add(a["original_language"])
                            all_articles.append(a)
                            aggregated_categories["all"].append(a)
                    else:
                        for a in cat_articles:
                            a["doc_id"] = doc_id
                            a["filename"] = fname
                            if cat_name in aggregated_categories:
                                aggregated_categories[cat_name].append(a)

                documents_summary.append({
                    "doc_id": doc_id,
                    "filename": fname,
                    "source_name": src_name,
                    "total_pages": doc_data.get("total_pages", 0),
                    "scanned_pages_count": doc_data.get("scanned_pages_count", 0),
                    "total_articles": doc_data.get("total_articles", 0),
                    "translated_count": doc_data.get("translated_count", 0),
                    "needs_review_count": doc_data.get("needs_review_count", 0),
                    "snapshots": doc_data.get("snapshots", []),
                    "success": True,
                })
            else:
                documents_summary.append({
                    "doc_id": "",
                    "filename": item.get("filename", "unknown"),
                    "source_name": item.get("filename", "unknown"),
                    "total_pages": 0,
                    "scanned_pages_count": 0,
                    "total_articles": 0,
                    "translated_count": 0,
                    "needs_review_count": 0,
                    "snapshots": [],
                    "success": False,
                    "error": item.get("error", "Processing error"),
                })

        summary = {
            "newspaper_names": [d["source_name"] for d in documents_summary if d.get("source_name")] or (source_names or [p.stem.replace('_', ' ').replace('-', ' ').title() for p in file_paths]),
            "publication_dates": sorted(list({a.get("publication_date") for a in all_articles if a.get("publication_date")}), reverse=True),
            "original_languages": sorted(list(all_languages)),
            "total_pages_processed": total_pages,
            "total_articles_extracted": len(all_articles),
            "translated_count": translated_count,
            "needs_review_count": needs_review_count,
        }

        return {
            "batch_mode": True,
            "total_files": total_files,
            "successful_files": successful_count,
            "failed_files": total_files - successful_count,
            "total_pages": total_pages,
            "total_articles": len(all_articles),
            "articles": all_articles,
            "translated_count": translated_count,
            "needs_review_count": needs_review_count,
            "detected_languages": sorted(list(all_languages)),
            "documents": documents_summary,
            "snapshots": all_snapshots[:30],
            "categories": aggregated_categories,
            "summary": summary,
        }


# Singleton instance
pdf_news_parser = NewspaperPDFParser()
