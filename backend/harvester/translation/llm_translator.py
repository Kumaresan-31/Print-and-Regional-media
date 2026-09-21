import asyncio
import html
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
import concurrent.futures
from typing import Dict, List, Optional, Tuple, Set, Any

from deep_translator import GoogleTranslator

from harvester.config import settings

logger = logging.getLogger(__name__)

# Dedicated thread pool for non-blocking HTTP translation requests (prevents starving FastAPI event loop)
_translation_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="tr_worker")

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

    def _get_bing_credentials(self) -> Optional[Tuple[str, str, str, str]]:
        """Retrieves or refreshes Bing translator session tokens (IG, IID, key, token)."""
        import time
        now = time.time()
        if hasattr(self, "_bing_creds") and self._bing_creds and (now - getattr(self, "_bing_creds_time", 0) < 1800):
            return self._bing_creds

        try:
            import requests
            session = getattr(self, "_http_session", None)
            if session is None:
                session = requests.Session()
                session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                })
                self._http_session = session

            r = session.get("https://www.bing.com/translator", timeout=8)
            ig_match = re.search(r'IG:"([^"]+)"', r.text)
            iid_match = re.search(r'data-iid="([^"]+)"', r.text)
            params_match = re.search(r'var params_AbusePreventionHelper\s*=\s*\[([^\]]+)\];', r.text)

            if ig_match and params_match:
                vals = [v.strip().strip('"\'') for v in params_match.group(1).split(",")]
                key, token = vals[0], vals[1]
                ig = ig_match.group(1)
                iid = iid_match.group(1) if iid_match else "translator.5028"
                self._bing_creds = (ig, iid, key, token)
                self._bing_creds_time = now
                return self._bing_creds
        except Exception as e:
            logger.debug(f"Bing credentials refresh note: {e}")
        return None

    def _translate_sync(self, text: str, source_lang: str) -> str:
        """Multi-engine synchronous translation with automatic chunking and noise pre-cleaning."""
        # Sanitize OCR noise (stray punctuation brackets, isolated Latin chars between Indic words)
        clean = re.sub(r"[\^~|\[\]{}\\_+=<>]+", " ", text)
        clean = re.sub(r"(?<=[\u0900-\u0D7F])\s+[a-zA-Z]\s+(?=[\u0900-\u0D7F])", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()

        if not clean:
            return ""

        # If text is long, chunk it to stay well within MyMemory 500-char and GoogleTranslator single-sentence limits
        if len(clean) > 380:
            chunks = self._split_into_chunks(clean, max_chars=380)
            if len(chunks) > 1:
                translated_parts = [self._translate_single_sync(c, source_lang) for c in chunks]
                return " ".join(p for p in translated_parts if p).strip()

        return self._translate_single_sync(clean, source_lang)

    def _translate_single_sync(self, clean: str, source_lang: str) -> str:
        """Translates a single short text segment using Bing session -> MyMemory -> GoogleTranslator fallback."""
        import time

        # Engine 1: Microsoft Bing Translator (Session Token)
        try:
            creds = self._get_bing_credentials()
            if creds:
                ig, iid, key, token = creds
                session = getattr(self, "_http_session", None)
                if session is None:
                    import requests
                    session = requests.Session()
                    session.headers.update({
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    })
                    self._http_session = session

                trans_url = f"https://www.bing.com/ttranslatev3?isVertical=1&IG={ig}&IID={iid}"
                from_lang = source_lang if source_lang not in ("auto", "autodetect", "") else "auto-detect"
                payload = {"text": clean, "fromLang": from_lang, "to": "en", "token": token, "key": key}
                resp = session.post(trans_url, data=payload, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        translations = data[0].get("translations", [])
                        if translations:
                            tr_text = translations[0].get("text", "").strip()
                            if tr_text:
                                return html.unescape(tr_text)
                else:
                    self._bing_creds = None
        except Exception as e:
            logger.debug(f"Bing engine note: {e}")
            self._bing_creds = None

        # Fallback engines
        for attempt in range(2):
            # Engine 2: MyMemory API (strictly under 500 chars)
            try:
                lang_pair = f"{source_lang}|en" if source_lang != "auto" else "autodetect|en"
                url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(clean[:450])}&langpair={lang_pair}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    trans = data.get("responseData", {}).get("translatedText")
                    if trans and not trans.startswith("MYMEMORY WARNING") and not trans.startswith("QUERY LENGTH"):
                        return html.unescape(trans.strip())
            except Exception as e:
                logger.debug(f"MyMemory engine note (attempt {attempt + 1}): {e}")

            # Engine 3: DeepTranslator Google engine
            try:
                gt = GoogleTranslator(source=source_lang if source_lang != "auto" else "auto", target="en")
                res = gt.translate(clean)
                if res and not res.startswith("Error 500"):
                    return html.unescape(res.strip())
            except Exception as e:
                err_str = str(e)
                logger.debug(f"GoogleTranslator engine note (attempt {attempt + 1}): {err_str}")
                if "429" in err_str and attempt == 0:
                    time.sleep(0.5)
                    continue

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
        translated_raw = await loop.run_in_executor(_translation_executor, self._translate_sync, clean_text, source_lang)

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

    def _split_into_chunks(self, text: str, max_chars: int = 380) -> List[str]:
        """
        Splits text into chunks of at most max_chars characters, breaking
        at paragraph boundaries first, then sentence boundaries, then word
        boundaries — to ensure clean, readable translated output.
        """
        if len(text) <= max_chars:
            return [text]

        chunks: List[str] = []
        # Try paragraph splits first
        paragraphs = re.split(r"\n{2,}", text)
        current = ""
        for para in paragraphs:
            if not para.strip():
                continue
            if len(current) + len(para) + 2 <= max_chars:
                current = f"{current}\n\n{para}".lstrip("\n")
            else:
                # Para itself is longer than max_chars — split by sentences
                if current:
                    chunks.append(current.strip())
                    current = ""
                if len(para) <= max_chars:
                    current = para
                else:
                    # Split by sentence
                    sentences = re.split(r"(?<=[.!?।])\s+", para)
                    for sent in sentences:
                        if len(current) + len(sent) + 1 <= max_chars:
                            current = f"{current} {sent}".lstrip()
                        else:
                            if current:
                                chunks.append(current.strip())
                            # Sentence itself longer than limit — hard split at word boundary
                            if len(sent) <= max_chars:
                                current = sent
                            else:
                                words = sent.split()
                                current = ""
                                for word in words:
                                    if len(current) + len(word) + 1 <= max_chars:
                                        current = f"{current} {word}".lstrip()
                                    else:
                                        if current:
                                            chunks.append(current.strip())
                                        current = word
        if current.strip():
            chunks.append(current.strip())
        return [c for c in chunks if c.strip()]

    async def translate_long_text(
        self,
        text: str,
        source_lang: str = "auto",
        chunk_size: int = 380,
    ) -> TranslationResult:
        """
        Translates arbitrarily long text by splitting into chunks, translating
        each chunk independently, and joining the results back into coherent English.
        Uses the same entity preservation and confidence pipeline as translate().
        This is the correct method to use for full article body translation.
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
        cache_key = f"long:{source_lang}:{clean_text[:120]}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        chunks = self._split_into_chunks(clean_text, max_chars=chunk_size)

        if len(chunks) == 1:
            # Short enough — use normal translate path
            return await self.translate(clean_text, source_lang)

        # Translate chunks with gentle pacing to avoid HTTP 429
        loop = asyncio.get_event_loop()
        translated_chunks: List[str] = []
        all_entities: List[str] = []
        min_confidence = 1.0
        any_needs_review = False

        raw_translations = []
        for chunk in chunks:
            try:
                raw_item = await loop.run_in_executor(_translation_executor, self._translate_sync, chunk, source_lang)
                raw_translations.append(raw_item)
            except Exception as ce:
                raw_translations.append(ce)
            await asyncio.sleep(0.04)

        for chunk, raw in zip(chunks, raw_translations):
            if isinstance(raw, Exception) or not raw:
                # Keep original chunk if translation failed
                translated_chunks.append(chunk)
                any_needs_review = True
                min_confidence = min(min_confidence, 0.60)
            else:
                entities = self.extract_named_entities(chunk)
                fixed, preserved, missing = self.ensure_entity_preservation(str(raw), entities)
                all_entities.extend(preserved)
                conf = self.calculate_confidence(chunk, fixed, missing, len(entities), source_lang)
                min_confidence = min(min_confidence, conf)
                if conf < self.review_threshold:
                    any_needs_review = True
                translated_chunks.append(fixed)

        full_translation = "\n\n".join(translated_chunks)

        result = TranslationResult(
            original_text=clean_text,
            translated_text=full_translation,
            detected_language=source_lang,
            confidence_score=round(min_confidence, 2),
            needs_review=any_needs_review,
            preserved_entities=list(set(all_entities)),
            provider="dual_engine_llm_chunked"
        )
        self._cache[cache_key] = result
        return result


# Global singleton instance
llm_translator = LLMTranslator(review_threshold=settings.translation_confidence_threshold)
