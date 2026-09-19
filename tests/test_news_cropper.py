import unittest
from pathlib import Path
import sys

backend_path = Path(r"d:\Projects\VEE2\backend")
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from harvester.news.news_cropper import generate_news_crop, get_or_create_boxes

class TestNewsCropper(unittest.TestCase):
    def test_news_crop_generation(self):
        snapshot_dir = Path(r"d:\Projects\VEE2\data\snapshots")
        # Find any available page snapshot
        cand = None
        for p in snapshot_dir.rglob("page_001.jpg"):
            cand = p
            break

        if cand and cand.exists():
            crop_path = generate_news_crop(cand, query="newspaper")
            self.assertIsNotNone(crop_path)
            self.assertTrue(crop_path.exists())
            self.assertGreater(crop_path.stat().st_size, 0)

            # Test boxes cache
            boxes = get_or_create_boxes(cand)
            self.assertIsInstance(boxes, list)

if __name__ == "__main__":
    unittest.main()
