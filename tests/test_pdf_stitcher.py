import unittest
import shutil
from pathlib import Path
from PIL import Image, ImageDraw
from pypdf import PdfReader

from harvester.extractors.engines.image_stitcher import ImageStitcher


class TestPdfStitcher(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests_temp_pdf")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.stitcher = ImageStitcher(output_dir=self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_dummy_image(self, filename: str, text: str) -> Path:
        img_path = self.test_dir / filename
        img = Image.new("RGB", (800, 1200), color=(240, 245, 250))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(20, 20), (780, 1180)], outline=(50, 100, 200), width=4)
        draw.text((100, 100), text, fill=(20, 20, 20))
        img.save(img_path, "JPEG")
        return img_path

    def test_pdf_assembly_and_metadata(self):
        # Generate 3 dummy pages
        p1 = self._create_dummy_image("page_001.jpg", "Page 1: Front Page Headline")
        p2 = self._create_dummy_image("page_002.jpg", "Page 2: National News")
        p3 = self._create_dummy_image("page_003.jpg", "Page 3: Editorial & Opinion")

        output_pdf = self.test_dir / "test_newspaper.pdf"
        res_pdf = self.stitcher.assemble_pdf(
            page_image_paths=[p1, p2, p3],
            output_pdf_path=output_pdf,
            title="The Daily Test - Delhi Edition (2026-08-29)",
            author="Harvester Test Suite",
            generate_thumbnail=True
        )

        self.assertIsNotNone(res_pdf)
        self.assertTrue(res_pdf.exists())
        self.assertGreater(res_pdf.stat().st_size, 5000)

        # Inspect with PyPDF
        reader = PdfReader(str(res_pdf))
        self.assertEqual(len(reader.pages), 3)

        # Check outline/bookmarks
        outline = reader.outline
        self.assertGreaterEqual(len(outline), 3)

        # Check metadata
        meta = reader.metadata
        self.assertIn("The Daily Test", meta.get("/Title", ""))

        # Check thumbnail
        thumb_path = res_pdf.with_suffix(".thumb.jpg")
        self.assertTrue(thumb_path.exists(), "Thumbnail should be generated")
        with Image.open(thumb_path) as thumb_img:
            self.assertLessEqual(thumb_img.width, 320)


if __name__ == "__main__":
    unittest.main()
