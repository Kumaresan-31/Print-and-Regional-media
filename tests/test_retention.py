import unittest
import shutil
import time
from pathlib import Path
from harvester.storage.retention import RetentionManager


class TestRetentionManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests_temp_archive")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.mgr = RetentionManager(archive_dir=self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_archive_listing_and_purge(self):
        # Create a mock archive structure: tests_temp_archive/toi/2026-08-29/toi_delhi_2026-08-29.pdf
        date_dir = self.test_dir / "toi" / "2026-08-29"
        date_dir.mkdir(parents=True, exist_ok=True)
        pdf_file = date_dir / "toi_delhi_2026-08-29.pdf"
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF-1.4 mock content...")

        # Create thumbnail
        thumb_file = pdf_file.with_suffix(".thumb.jpg")
        with open(thumb_file, "wb") as f:
            f.write(b"mock image")

        items = self.mgr.list_archives()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_id, "toi")
        self.assertEqual(items[0].target_date, "2026-08-29")
        self.assertEqual(items[0].edition, "delhi")

        stats = self.mgr.get_storage_stats()
        self.assertEqual(stats["total_archives"], 1)

        # Test purge (purge with 0 days should delete everything older than now)
        # Artificially set file time to 2 days ago
        two_days_ago = time.time() - (2 * 86400)
        import os
        os.utime(pdf_file, (two_days_ago, two_days_ago))

        purged = self.mgr.purge_expired(retention_days=1)
        self.assertEqual(purged, 1)
        self.assertFalse(pdf_file.exists())
        self.assertFalse(thumb_file.exists())


if __name__ == "__main__":
    unittest.main()
