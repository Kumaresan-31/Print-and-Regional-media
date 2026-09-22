import os
import sys
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFont

# Ensure backend is on sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from harvester.extractors.engines.marathi_ocr import marathi_ocr_engine, MarathiOCREngine
from harvester.news.pdf_parser import detect_script_language, run_ocr_on_image


def test_engine_initialization():
    """Verifies that the Marathi OCR engine initializes with mar+eng configured."""
    assert marathi_ocr_engine is not None
    assert "mar" in marathi_ocr_engine.default_lang


def test_is_marathi_source():
    """Verifies source classification for Marathi regional newspapers."""
    assert marathi_ocr_engine.is_marathi_source("lokmat")
    assert marathi_ocr_engine.is_marathi_source("loksatta")
    assert marathi_ocr_engine.is_marathi_source("sakaal")
    assert marathi_ocr_engine.is_marathi_source("maharashtra_times")
    assert marathi_ocr_engine.is_marathi_source("saamana")
    assert marathi_ocr_engine.is_marathi_source("pudhari")
    assert marathi_ocr_engine.is_marathi_source("divya_marathi")

    assert not marathi_ocr_engine.is_marathi_source("the_hindu")
    assert not marathi_ocr_engine.is_marathi_source("toi")
    assert not marathi_ocr_engine.is_marathi_source("eenadu")


def test_is_marathi_text_detection():
    """Verifies linguistic detection for Marathi text vs generic Devanagari/Hindi."""
    # Contains unique Marathi character 'ळ'
    assert marathi_ocr_engine.is_marathi_text("परीक्षेचे नवीन वेळापत्रक जाहीर")
    # Contains inflected Marathi tokens
    assert marathi_ocr_engine.is_marathi_text("पुण्यातील प्रमुख घडामोडी")
    assert marathi_ocr_engine.is_marathi_text("मुख्यमंत्री यांनी बैठक घेतली आणि निर्णय जाहीर केला")

    # English text
    assert not marathi_ocr_engine.is_marathi_text("The Reserve Bank of India announced new interest rates today.")


def test_marathi_ocr_text_and_boxes_extraction(tmp_path):
    """
    Renders a synthetic image with Marathi text + English date,
    and validates OCR extraction via marathi_ocr_engine using mar+eng and --oem 3 --psm 6.
    """
    # Create test image with Nirmala font if available, or load existing test image
    img_path = tmp_path / "test_marathi.png"
    font_path = Path(r"C:\Windows\Fonts\Nirmala.ttc")
    if font_path.exists():
        font = ImageFont.truetype(str(font_path), 36, index=0)
    else:
        font = ImageFont.load_default()

    img = Image.new("RGB", (750, 160), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((25, 45), "लोकमत - महाराष्ट्र न्यूज 2026", fill="black", font=font)
    img.save(img_path)

    # 1. Test text extraction with PSM 6 (uniform text block)
    extracted_text = marathi_ocr_engine.extract_text(img_path, psm=6)
    assert extracted_text is not None
    assert len(extracted_text) > 0
    # Devanagari script present
    assert any(0x0900 <= ord(c) <= 0x097F for c in extracted_text)

    # 2. Test boxes extraction with PSM 3 / PSM 6
    text_out, conf, blocks = marathi_ocr_engine.extract_boxes(img_path, psm=6)
    assert len(blocks) > 0
    assert conf > 0.5
    assert "box" in blocks[0]
    assert "text" in blocks[0]


def test_pdf_parser_marathi_integration():
    """Verifies that pdf_parser correctly classifies and routes Marathi newspaper text."""
    lang_code, lang_name = detect_script_language(
        "पुण्यातील जिल्हाधिकाऱ्यांनी घेतला मोठा निर्णय, सर्व शाळांना सुट्टी जाहीर",
        source_hint="lokmat"
    )
    assert lang_code == "mr"
    assert lang_name == "Marathi"
