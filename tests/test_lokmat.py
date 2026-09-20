import unittest
import json
import sys
from pathlib import Path
from datetime import datetime

backend_path = Path(r"d:\Projects\VEE2\backend")
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from harvester.registry import get_source
from harvester.auth.session_manager import session_manager


class TestLokmatIntegration(unittest.TestCase):
    def test_lokmat_registry(self):
        source = get_source("lokmat")
        self.assertIsNotNone(source)
        self.assertEqual(source.id, "lokmat")
        self.assertEqual(source.name, "Lokmat")
        self.assertTrue(source.auth_required)
        self.assertEqual(source.default_edition, "pune")
        edition_codes = [e.code for e in source.available_editions]
        self.assertIn("pune", edition_codes)
        self.assertIn("mumbai", edition_codes)
        self.assertIn("nagpur", edition_codes)
        self.assertIn("nashik", edition_codes)
        self.assertIn("aurangabad", edition_codes)

    def test_lokmat_session_validity(self):
        info = session_manager.get_session_info("lokmat", "Lokmat")
        self.assertTrue(info.has_session)
        self.assertTrue(info.is_valid)
        self.assertEqual(info.cookie_count, 4)
        self.assertIsNotNone(info.expires_at)
        self.assertGreater(info.expires_at, datetime.now())

    def test_edition_sessions(self):
        for ed in ["pune", "mumbai", "nagpur", "nashik", "aurangabad"]:
            cookies = session_manager.load_cookies(f"lokmat_{ed}")
            self.assertGreaterEqual(len(cookies), 4, f"Missing cookies for edition {ed}")
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            self.assertIn("_ga", cookie_dict)
            self.assertIn("_ga_V1GGXX48BX", cookie_dict)
            self.assertIn("_gat", cookie_dict)
            self.assertIn("_gid", cookie_dict)

    def test_lokmat_samachar_sessions(self):
        for src in ["lokmat_samachar", "lokmat_samachar_nagpur", "lokmat_samachar_aurangabad"]:
            cookies = session_manager.load_cookies(src)
            self.assertGreaterEqual(len(cookies), 4, f"Missing cookies for {src}")

    def test_root_cookie_file_matches(self):
        root_file = Path(r"d:\Projects\VEE2\lokmat_cookies.json")
        self.assertTrue(root_file.exists())
        with open(root_file, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        self.assertEqual(len(cookies), 4)

    def test_freshest_cookie_deduplication(self):
        # Test that session_manager deduplicates and keeps cookie with later expirationDate
        sample = """[
            {
                "domain": ".lokmat.com",
                "name": "test_cookie",
                "value": "older_value",
                "path": "/",
                "expirationDate": 1780000000
            }
        ][
            {
                "domain": ".lokmat.com",
                "name": "test_cookie",
                "value": "fresher_value",
                "path": "/",
                "expirationDate": 1820000000
            }
        ]"""
        count = session_manager.import_cookies_raw("test_dedup", sample)
        self.assertEqual(count, 2)
        cookies = session_manager.load_cookies("test_dedup")
        self.assertEqual(len(cookies), 1)
        self.assertEqual(cookies[0]["value"], "fresher_value")
        self.assertEqual(cookies[0]["expirationDate"], 1820000000)

        # Clean up
        test_file = session_manager._get_session_path("test_dedup")
        if test_file.exists():
            test_file.unlink()


if __name__ == "__main__":
    unittest.main()
