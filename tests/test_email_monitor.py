import asyncio
import unittest
from pathlib import Path

from harvester.automation.email_monitor import email_inbox_monitor, decode_mime_header
from harvester.api.app import get_inbox_status, get_inbox_clippings, get_email_diagnostics


class TestEmailInboxMonitor(unittest.TestCase):

    def test_rule_matching(self):
        # 1. Matches sender = cuttyknowledge2006@gmail.com
        matched, reason = email_inbox_monitor.matches_rule(
            sender="cuttyknowledge2006@gmail.com",
            subject="Today's Report"
        )
        self.assertTrue(matched)
        self.assertIn("Sender match", reason)

        # 2. Matches sender = bureau@chennai.com
        matched, reason = email_inbox_monitor.matches_rule(
            sender="bureau@chennai.com",
            subject="Today's Report"
        )
        self.assertTrue(matched)
        self.assertIn("Sender match", reason)

        # 3. Matches sender with display name
        matched, reason = email_inbox_monitor.matches_rule(
            sender="Knowledge Desk <cuttyknowledge2006@gmail.com>",
            subject="Press Release"
        )
        self.assertTrue(matched)

        # 4. Matches subject containing 'clipping'
        matched, reason = email_inbox_monitor.matches_rule(
            sender="reporter@tamilnadu.org",
            subject="Urgent newspaper clipping for review"
        )
        self.assertTrue(matched)
        self.assertIn("Subject keyword match", reason)

        # 5. Case-insensitive matching
        matched, reason = email_inbox_monitor.matches_rule(
            sender="desk@news.in",
            subject="DAILY CLIPPING ARCHIVE"
        )
        self.assertTrue(matched)

        # 6. Non-matching emails
        matched, reason = email_inbox_monitor.matches_rule(
            sender="notifications@bank.com",
            subject="Your monthly statement is ready"
        )
        self.assertFalse(matched)

    def test_decode_mime_header(self):
        self.assertEqual(decode_mime_header("Simple text"), "Simple text")
        self.assertEqual(decode_mime_header(""), "")

    def test_imap_diagnostic_method(self):
        diag = email_inbox_monitor.test_imap_connection()
        self.assertIn("success", diag)
        self.assertIn("host", diag)
        self.assertEqual(diag["host"], "imap.gmail.com")

    def test_simulation_pipeline(self):
        async def _run():
            sample_file = Path("data/sample_regional_newspaper.pdf")
            if not sample_file.exists():
                self.skipTest("Sample PDF not found")

            record = await email_inbox_monitor.simulate_incoming_clipping(
                sender="bureau@chennai.com",
                subject="Regional Newspaper Clipping - Chennai Special",
                file_path=sample_file
            )

            self.assertIn("id", record)
            self.assertEqual(record["sender"], "bureau@chennai.com")
            self.assertGreater(record["articles_count"], 0)
            self.assertTrue(any(len(record["articles"]) > 0 for _ in [1]))

            # Verify presence in status and clippings API
            status = get_inbox_status()
            self.assertGreaterEqual(status["total_clippings_ingested"], 1)

            clippings = get_inbox_clippings()
            self.assertGreaterEqual(len(clippings), 1)

        asyncio.run(_run())

    def test_direct_clipping_ingest(self):
        async def _run():
            sample_file = Path("data/sample_regional_newspaper.pdf")
            if not sample_file.exists():
                self.skipTest("Sample PDF not found")

            record = await email_inbox_monitor.ingest_uploaded_clipping(
                file_path=sample_file,
                sender="bureau@chennai.com",
                subject="Uploaded Regional Clipping"
            )

            self.assertIn("id", record)
            self.assertIn("articles", record)
            self.assertGreater(record["articles_count"], 0)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
