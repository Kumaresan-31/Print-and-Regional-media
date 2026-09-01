import unittest
from harvester.registry import SOURCES_REGISTRY, list_sources, get_source, resolve_url
from harvester.models import SourceLanguage, EngineType


class TestSourceRegistry(unittest.TestCase):
    def test_registry_size_exceeds_fifty(self):
        """Verify registry contains 50+ configured newspaper sources."""
        self.assertGreaterEqual(len(SOURCES_REGISTRY), 50, f"Expected >= 50 sources, found {len(SOURCES_REGISTRY)}")

    def test_sources_integrity(self):
        """Verify all sources possess valid metadata, editions, and URL templates."""
        for src_id, src in SOURCES_REGISTRY.items():
            self.assertEqual(src_id, src.id)
            self.assertTrue(len(src.name) > 0)
            self.assertIsInstance(src.language, SourceLanguage)
            self.assertIsInstance(src.engine_type, EngineType)
            self.assertTrue(src.url_template.startswith("http"))
            self.assertGreater(len(src.available_editions), 0)
            self.assertTrue(any(e.code == src.default_edition for e in src.available_editions),
                            f"Default edition '{src.default_edition}' not in available editions for {src.id}")

    def test_language_diversity(self):
        """Verify presence of major Indian languages."""
        languages = {s.language for s in SOURCES_REGISTRY.values()}
        expected_langs = [
            SourceLanguage.ENGLISH,
            SourceLanguage.HINDI,
            SourceLanguage.TELUGU,
            SourceLanguage.TAMIL,
            SourceLanguage.MARATHI,
            SourceLanguage.BENGALI,
            SourceLanguage.GUJARATI,
            SourceLanguage.KANNADA,
            SourceLanguage.MALAYALAM,
        ]
        for el in expected_langs:
            self.assertIn(el, languages, f"Missing expected language: {el}")

    def test_url_token_resolution(self):
        """Verify dynamic URL token resolution ({YYYY}, {MM}, {DD}, {edition})."""
        toi = get_source("toi")
        self.assertIsNotNone(toi)
        resolved = resolve_url(toi, "2026-08-29", "mumbai")
        self.assertIn("2026-08-29", resolved)
        self.assertIn("mumbai", resolved)

        eenadu = get_source("eenadu")
        self.assertIsNotNone(eenadu)
        resolved_eenadu = resolve_url(eenadu, "2026-08-29", "hyderabad")
        self.assertIn("29%2F08%2F2026", resolved_eenadu)


if __name__ == "__main__":
    unittest.main()
