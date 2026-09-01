import asyncio
import os
import unittest
from pathlib import Path

from harvester.news.pdf_parser import pdf_news_parser, detect_script_language
from harvester.api.app import upload_and_parse_newspaper
from fastapi import UploadFile


class TestPDFNewsParser(unittest.TestCase):

    def test_detect_script_language(self):
        code, name = detect_script_language("दैनिक भास्कर आज की खबर")
        self.assertEqual(code, "hi")
        self.assertEqual(name, "Hindi")

        code, name = detect_script_language("ఈనాడు ప్రధాన వార్తలు")
        self.assertEqual(code, "te")
        self.assertEqual(name, "Telugu")

        code, name = detect_script_language("தினமலர் செய்தி")
        self.assertEqual(code, "ta")
        self.assertEqual(name, "Tamil")

        code, name = detect_script_language("The Times of India Sports News")
        self.assertEqual(code, "auto")

    def test_classify_category(self):
        self.assertEqual(pdf_news_parser.classify_category("India Wins Cricket Series in Thrilling Final", "Captain hits century"), "sports")
        self.assertEqual(pdf_news_parser.classify_category("Sensex Surges 800 Points on Market Rally", "Tata and Reliance shares lead gains"), "business")
        self.assertEqual(pdf_news_parser.classify_category("RBI Keeps Repo Rate Steady Amid Inflation Concerns", "GDP growth projected at 7.2 percent"), "economic")
        self.assertEqual(pdf_news_parser.classify_category("Parliament Passes Landmark Bill in Monsoon Session", "Opposition ministers stage walkout"), "political")
        self.assertEqual(pdf_news_parser.classify_category("Rescue Operations Intensify After Flash Flood in Mountains", "Over 200 injured and emergency relief sent"), "crises_disasters")

    def test_segment_text_into_stories(self):
        sample_pages = [
            (1, "HEADLINE ONE CRICKET TOURNAMENT\nIndia won the match by 5 wickets in final overs.\n\nHEADLINE TWO SENSEX GAINS\nStock markets rallied today on strong tech earnings."),
        ]
        stories = pdf_news_parser.segment_text_into_stories(sample_pages)
        self.assertGreaterEqual(len(stories), 2)
        self.assertIn("CRICKET", stories[0]["title"])
        self.assertIn("SENSEX", stories[1]["title"])

    def test_detect_scanned_pdf(self):
        # Sparse text with image is scanned
        self.assertTrue(pdf_news_parser.detect_scanned_pdf("   ", image_count=1))
        self.assertTrue(pdf_news_parser.detect_scanned_pdf("Page 1", image_count=1))
        # Dense vector text is not scanned
        dense_text = "This is a full digital article text with multiple sentences and detailed coverage of national news events." * 3
        self.assertFalse(pdf_news_parser.detect_scanned_pdf(dense_text, image_count=0))

    def test_extract_masthead_date(self):
        header1 = "THE TIMES OF INDIA - NEW DELHI - 29 August 2026 - VOL. CLXXXVIII"
        date1 = pdf_news_parser.extract_masthead_date(header1)
        self.assertIsNotNone(date1)
        self.assertIn("29 August 2026", date1)

        header2 = "DAINIK BHASKAR - BHOPAL - 2026-08-29 - SPECIAL"
        date2 = pdf_news_parser.extract_masthead_date(header2)
        self.assertIsNotNone(date2)
        self.assertIn("2026-08-29", date2)

    def test_parse_sample_pdf(self):
        async def _run():
            sample_pdf = Path("data/sample_regional_newspaper.pdf")
            if not sample_pdf.exists():
                sample_pdf = Path("data/archive/toi/2026-08-29/toi_delhi_2026-08-29.pdf")
            if not sample_pdf.exists():
                self.skipTest("Sample PDF not found")

            result = await pdf_news_parser.parse_and_process_pdf(sample_pdf, max_pages=2)
            self.assertIn("total_pages", result)
            self.assertIn("total_articles", result)
            self.assertIn("categories", result)
            self.assertIn("snapshots", result)
            self.assertGreater(result["total_pages"], 0)
            self.assertGreater(result["total_articles"], 0)
            self.assertGreater(len(result["snapshots"]), 0)

            # Check traceability on first article
            first_art = result["categories"]["all"][0]
            self.assertIn("page_snapshot_url", first_art)
            self.assertIsNotNone(first_art["page_snapshot_url"])
            self.assertGreaterEqual(first_art.get("ocr_confidence", 0), 0.90)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

