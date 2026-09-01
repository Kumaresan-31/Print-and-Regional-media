import unittest
import shutil
import json
from pathlib import Path
from harvester.auth.session_manager import SessionManager


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests_temp_sessions")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.mgr = SessionManager(sessions_dir=self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_load_cookies(self):
        cookies = [
            {"name": "session_token", "value": "xyz123", "domain": ".thehindu.com", "expires": 1893456000},
            {"name": "user_pref", "value": "dark", "domain": ".thehindu.com", "expires": 1893456000},
        ]
        self.mgr.save_cookies("the_hindu", cookies)

        loaded = self.mgr.load_cookies("the_hindu")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["name"], "session_token")

        cookie_dict = self.mgr.get_cookie_dict("the_hindu")
        self.assertEqual(cookie_dict["session_token"], "xyz123")

    def test_import_netscape_format(self):
        netscape_raw = """# Netscape HTTP Cookie File
.timesgroup.com\tTRUE\t/\tTRUE\t1893456000\tTOI_AUTH\tabc_token_999
.timesgroup.com\tTRUE\t/\tFALSE\t1893456000\t_ga\tGA1.2.3.4
"""
        count = self.mgr.import_cookies_raw("toi", netscape_raw)
        self.assertEqual(count, 2)

        info = self.mgr.get_session_info("toi", "The Times of India")
        self.assertTrue(info.has_session)
        self.assertEqual(info.cookie_count, 2)


if __name__ == "__main__":
    unittest.main()
