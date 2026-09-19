import unittest
import json
import sys
from pathlib import Path

backend_path = Path(r"d:\Projects\VEE2\backend")
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from harvester.registry import get_source
from harvester.extractors.factory import get_extractor
from harvester.extractors.sources.loksatta import LoksattaExtractor
from harvester.auth.session_manager import session_manager

class TestLoksattaIntegration(unittest.TestCase):
    def test_loksatta_registry(self):
        source = get_source("loksatta")
        self.assertIsNotNone(source)
        self.assertEqual(source.id, "loksatta")
        self.assertTrue(source.auth_required)
        edition_codes = [e.code for e in source.available_editions]
        self.assertIn("mumbai", edition_codes)
        self.assertIn("pune", edition_codes)
        self.assertIn("nagpur", edition_codes)
        self.assertIn("nashik", edition_codes)

    def test_loksatta_extractor_factory(self):
        source = get_source("loksatta")
        extractor = get_extractor(source)
        self.assertIsInstance(extractor, LoksattaExtractor)

    def test_loksatta_session_validity(self):
        info = session_manager.get_session_info("loksatta", "Loksatta")
        self.assertTrue(info.has_session)
        self.assertTrue(info.is_valid)
        self.assertGreater(info.cookie_count, 0)
        self.assertIsNotNone(info.expires_at)
        # Should be valid in the future
        from datetime import datetime
        self.assertGreater(info.expires_at, datetime.now())

    def test_edition_sessions(self):
        for ed in ["mumbai", "pune", "nagpur", "nashik"]:
            cookies = session_manager.load_cookies(f"loksatta_{ed}")
            self.assertGreater(len(cookies), 0, f"Missing cookies for edition {ed}")

    def test_concatenated_json_import(self):
        sample = '[{"domain":".loksatta.com","name":"test1","value":"val1"}][{"domain":".loksatta.com","name":"test2","value":"val2"}]'
        count = session_manager.import_cookies_raw("test_source", sample)
        self.assertEqual(count, 2)
        cookies = session_manager.load_cookies("test_source")
        self.assertEqual(len(cookies), 2)
        test_file = session_manager._get_session_path("test_source")
        if test_file.exists():
            test_file.unlink()

if __name__ == "__main__":
    unittest.main()
