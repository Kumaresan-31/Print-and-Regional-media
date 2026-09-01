import asyncio
import html
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set, Any

from deep_translator import GoogleTranslator

from harvester.config import settings

logger = logging.getLogger(__name__)

# Canonical dictionary of sensitive Named Entities to preserve strictly in English
CANONICAL_NAMED_ENTITIES: Dict[str, str] = {
    # Financial & Corporate
    "payu": "PayU",
    "पेयू": "PayU",
    "पे-यू": "PayU",
    "phonepe": "PhonePe",
    "फोनपे": "PhonePe",
    "razorpay": "Razorpay",
    "रेजरपे": "Razorpay",
    "zomato": "Zomato",
    "जोमैटो": "Zomato",
    "swiggy": "Swiggy",
    "स्विगी": "Swiggy",
    "reliance": "Reliance",
    "रिलायंस": "Reliance",
    "రిలయన్స్": "Reliance",
    "ரிலையன்ஸ்": "Reliance",
    "tata": "Tata",
    "टाटा": "Tata",
    "టాటా": "Tata",
    "டாடா": "Tata",
    "adani": "Adani",
    "अदाणी": "Adani",
    "अडानी": "Adani",
    "infosys": "Infosys",
    "इन्फोसिस": "Infosys",
    "tcs": "TCS",
    "टीसीएस": "TCS",
    "hdfc": "HDFC",
    "एचडीएफसी": "HDFC",
    "icici": "ICICI",
    "आईसीआईसीआई": "ICICI",
    "sbi": "SBI",
    "एसबीआई": "SBI",
    "rbi": "RBI",
    "आरबीआई": "RBI",
    "ఆర్బీఐ": "RBI",
    "sebi": "SEBI",
    "सेबी": "SEBI",
    "upi": "UPI",
    "यूपीआई": "UPI",
    "gst": "GST",
    "जीएसटी": "GST",
    
    # Political Leaders & Figures
    "nirmala sitharaman": "Nirmala Sitharaman",
    "nirmala seetharaman": "Nirmala Sitharaman",
    "निर्मला सीतारमण": "Nirmala Sitharaman",
    "निर्मला सीतारमन": "Nirmala Sitharaman",
    "நிர்மலா சீதாராமன்": "Nirmala Sitharaman",
    "నిర్మలా సీతారామన్": "Nirmala Sitharaman",
    "narendra modi": "Narendra Modi",
    "नरेंद्र मोदी": "Narendra Modi",
    "pm modi": "PM Modi",
    "पीएम मोदी": "PM Modi",
    "amit shah": "Amit Shah",
    "अमित शाह": "Amit Shah",
    "rahul gandhi": "Rahul Gandhi",
    "राहुल गांधी": "Rahul Gandhi",
    "droupadi murmu": "Droupadi Murmu",
    "द्रौपदी मुर्मू": "Droupadi Murmu",
    "isro": "ISRO",
    "इसरो": "ISRO",
    "drdo": "DRDO",
    "डीआरडीओ": "DRDO",
}


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    detected_language: str
    confidence_score: float
    needs_review: bool
    preserved_entities: List[str] = field(default_factory=list)
    provider: str = "llm_translator"


class LLMTranslator:
    """
    Regional Language Translation Layer with:
    1. Named Entity Preservation ("PayU", "Nirmala Sitharaman", corporate/political names).
    2. Dual translation engines (MyMemory + GoogleTranslator fallback).
    3. Deterministic entity verification and restoration for 100% fidelity.
    4. Translation confidence evaluation (0.0 to 1.0) and review flagging (needs_review).
    """

    def __init__(self, review_threshold: float = 0.85):
        self.review_threshold = review_threshold
        self._cache: Dict[str, TranslationResult] = {}

    def extract_named_entities(self, text: str) -> List[Tuple[str, str]]:
        """
        Scans text for protected named entities (both regional script representations
        and Latin terms like PayU).
        Returns list of (matched_str, canonical_english_name).
        """
        matches = []
        lower_text = text.lower()

        # 1. Search known canonical entities (longest matches first)
        sorted_entities = sorted(CANONICAL_NAMED_ENTITIES.keys(), key=len, reverse=True)
        found_canonicals = set()

        for ent_key in sorted_entities:
            if ent_key in lower_text:
                canonical = CANONICAL_NAMED_ENTITIES[ent_key]
                if canonical not in found_canonicals:
                    matches.append((ent_key, canonical))
                    found_canonicals.add(canonical)

        # 2. Match Latin acronyms or brand names embedded in regional scripts
        # e.g., "PayU", "UPI", "RBI", "PhonePe"
        for m in re.finditer(r"\b[A-Z][a-zA-Z0-9_]{2,}\b|\b[A-Z]{2,}\b", text):
            word = m.group(0)
            canonical = CANONICAL_NAMED_ENTITIES.get(word.lower(), word)
            if canonical not in found_canonicals:
                matches.append((word, canonical))
                found_canonicals.add(canonical)

        return matches

    def ensure_entity_preservation(
        self,
        translated_text: str,
        detected_entities: List[Tuple[str, str]]
    ) -> Tuple[str, List[str], int]:
        """
        Verifies that all detected named entities exist in their canonical English form
        in the translated text. If missing or distorted, restores them.
        """
        preserved = []
        missing_count = 0
        cleaned = translated_text

        for original_str, canonical in detected_entities:
            # Check case-insensitive presence
            if re.search(rf"\b{re.escape(canonical)}\b", cleaned, re.IGNORECASE):
                # Ensure standard canonical capitalization
                cleaned = re.sub(rf"\b{re.escape(canonical)}\b", canonical, cleaned, flags=re.IGNORECASE)
                preserved.append(canonical)
            elif original_str in cleaned:
                cleaned = cleaned.replace(original_str, canonical)
                preserved.append(canonical)
            else:
                # Entity was missed by translation engine; safely append or inject
                missing_count += 1
                preserved.append(canonical)
                if canonical not in cleaned:
                    cleaned = f"{cleaned} ({canonical})"

        return cleaned, preserved, missing_count

    def calculate_confidence(
        self,
        original_text: str,
        translated_text: str,
        missing_tokens_count: int,
        total_tokens: int,
        source_lang: str
    ) -> float:
        """
        Calculates translation confidence score (0.0 to 1.0).
        """
        base_confidence = 0.98

        # Penalty for missing entity tokens
        if total_tokens > 0:
            lost_ratio = missing_tokens_count / total_tokens
            base_confidence -= (lost_ratio * 0.20)

        # Check for untranslated regional characters in output
        untranslated_chars = sum(1 for ch in translated_text if ord(ch) > 0x0600)
        if untranslated_chars > 0:
            char_penalty = min(0.35, (untranslated_chars / max(len(translated_text), 1)) * 1.5)
            base_confidence -= char_penalty

        # Check for empty or excessively short translation
        if len(translated_text.strip()) < 5 and len(original_text.strip()) > 10:
            base_confidence -= 0.50

        return max(0.10, min(0.99, round(base_confidence, 2)))

    def _translate_sync(self, text: str, source_lang: str) -> str:
        """Dual-engine synchronous translation: MyMemory with GoogleTranslator fallback."""
        clean = text.strip()

        # Engine 1: MyMemory API
        try:
            lang_pair = f"{source_lang}|en" if source_lang != "auto" else "autodetect|en"
            url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(clean)}&langpair={lang_pair}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                trans = data.get("responseData", {}).get("translatedText")
                if trans and not trans.startswith("MYMEMORY WARNING") and not trans.startswith("QUERY LENGTH"):
                    return html.unescape(trans.strip())
        except Exception as e:
            logger.debug(f"MyMemory engine note: {e}")

        # Engine 2: DeepTranslator Google engine
        try:
            gt = GoogleTranslator(source=source_lang if source_lang != "auto" else "auto", target="en")
            res = gt.translate(clean)
            if res and not res.startswith("Error 500"):
                return html.unescape(res.strip())
        except Exception as e:
            logger.debug(f"GoogleTranslator engine note: {e}")

        return clean

    async def translate(
        self,
        text: str,
        source_lang: str = "auto"
    ) -> TranslationResult:
        """
        Asynchronously translates text with strict Named Entity Preservation
        and confidence evaluation.
        """
        if not text or not text.strip():
            return TranslationResult(
                original_text="",
                translated_text="",
                detected_language=source_lang,
                confidence_score=1.0,
                needs_review=False,
                preserved_entities=[],
                provider="noop"
            )

        clean_text = text.strip()
        cache_key = f"{source_lang}:{clean_text}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 1. Detect protected Named Entities
        entities = self.extract_named_entities(clean_text)

        # 2. Execute dual-engine translation
        loop = asyncio.get_event_loop()
        translated_raw = await loop.run_in_executor(None, self._translate_sync, clean_text, source_lang)

        # 3. Post-process to guarantee 100% preservation of all named entities
        translated_final, preserved_list, missing_count = self.ensure_entity_preservation(
            translated_raw, entities
        )

        # 4. Evaluate confidence and review flag
        confidence = self.calculate_confidence(
            original_text=clean_text,
            translated_text=translated_final,
            missing_tokens_count=missing_count,
            total_tokens=len(entities),
            source_lang=source_lang
        )

        needs_review = confidence < self.review_threshold

        result = TranslationResult(
            original_text=clean_text,
            translated_text=translated_final,
            detected_language=source_lang,
            confidence_score=confidence,
            needs_review=needs_review,
            preserved_entities=list(set(preserved_list)),
            provider="dual_engine_llm"
        )

        self._cache[cache_key] = result
        return result


# Global singleton instance
llm_translator = LLMTranslator(review_threshold=settings.translation_confidence_threshold)
