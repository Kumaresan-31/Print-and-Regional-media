import asyncio
import unittest

from harvester.translation.llm_translator import llm_translator, CANONICAL_NAMED_ENTITIES


class TestLLMTranslator(unittest.TestCase):

    def test_entity_detection(self):
        # 1. Detect PayU and Nirmala Sitharaman in Hindi
        text_hi = "निर्मला सीतारमण ने PayU और UPI डिजिटल भुगतान प्रणाली की समीक्षा की"
        matches = llm_translator.extract_named_entities(text_hi)
        matched_canonicals = [m[1] for m in matches]
        self.assertIn("Nirmala Sitharaman", matched_canonicals)
        self.assertIn("PayU", matched_canonicals)
        self.assertIn("UPI", matched_canonicals)

        # 2. Detect Tamil entity
        text_ta = "நிர்மலா சீதாராமன் PayU புதிய திட்டம்"
        matches_ta = llm_translator.extract_named_entities(text_ta)
        matched_ta = [m[1] for m in matches_ta]
        self.assertIn("Nirmala Sitharaman", matched_ta)
        self.assertIn("PayU", matched_ta)

    def test_ensure_entity_preservation(self):
        text = "निर्मला सीतारमण ने PayU के साथ बैठक की"
        entities = llm_translator.extract_named_entities(text)
        dummy_trans = "The minister held a meeting with a payment company"

        # Ensure preservation restores missing entities
        cleaned, preserved, missing = llm_translator.ensure_entity_preservation(dummy_trans, entities)
        self.assertIn("Nirmala Sitharaman", cleaned)
        self.assertIn("PayU", cleaned)
        self.assertIn("PayU", preserved)

    def test_translation_preserves_payu_and_nirmala_sitharaman(self):
        async def _run():
            hindi_text = "निर्मला सीतारमण ने PayU और UPI प्रणाली को मजबूत करने का निर्देश दिया"
            result = await llm_translator.translate(hindi_text, source_lang="hi")

            self.assertIn("Nirmala Sitharaman", result.translated_text)
            self.assertIn("PayU", result.translated_text)
            self.assertIn("PayU", result.preserved_entities)
            self.assertIn("Nirmala Sitharaman", result.preserved_entities)
            self.assertGreaterEqual(result.confidence_score, 0.85)
            self.assertFalse(result.needs_review)

        asyncio.run(_run())

    def test_confidence_and_review_flag(self):
        # Extremely mangled or empty text should flag low confidence or needs_review
        conf = llm_translator.calculate_confidence(
            original_text="लंबा समाचार विवरण जिसमें कई महत्वपूर्ण बातें हैं",
            translated_text="ab",
            missing_tokens_count=2,
            total_tokens=2,
            source_lang="hi"
        )
        self.assertLess(conf, 0.85)


if __name__ == "__main__":
    unittest.main()
