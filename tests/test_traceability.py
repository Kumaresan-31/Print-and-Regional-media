import asyncio
import unittest
from pathlib import Path

from harvester.news.alerts_service import alerts_service
from harvester.news.pdf_parser import pdf_news_parser
from harvester.models import NewsAlert, NewsArticle


class TestDigitalTwinTraceability(unittest.TestCase):

    def test_traceability_linkage(self):
        """
        Verify that an alert satisfies 3-tier traceability:
        Translated Text -> OCR Raw Text -> Page Snapshot URL
        """
        sample_articles = [
            {
                "id": "art_test_101",
                "source_name": "Dainik Bhaskar (Page 1)",
                "category": "crises_disasters",
                "title": "Severe Flash Flood Hits Mountain Region, 50 Rescued",
                "snippet": "Emergency rescue operations deployed in full force.",
                "ocr_raw_text": "पहाड़ी इलाके में भीषण बाढ़, 50 लोगों को सुरक्षित निकाला गया",
                "ocr_confidence": 0.985,
                "translation_confidence": 0.96,
                "needs_review": False,
                "preserved_entities": ["NDRF"],
                "page_number": 1,
                "page_snapshot_url": "/api/snapshots/sample_doc/1",
                "bounding_box": [10.0, 20.0, 400.0, 300.0],
            },
            {
                "id": "art_test_102",
                "source_name": "The Hindu (Business)",
                "category": "business",
                "title": "PayU Expands Digital Merchant Settlement Network",
                "snippet": "PayU announced a new partnership for merchant settlements.",
                "ocr_raw_text": "PayU Expands Digital Merchant Settlement Network with banking partners",
                "ocr_confidence": 0.994,
                "translation_confidence": 1.0,
                "needs_review": False,
                "preserved_entities": ["PayU"],
                "page_number": 3,
                "page_snapshot_url": "/api/snapshots/sample_doc/3",
            }
        ]

        alerts = alerts_service.evaluate_and_generate_alerts(sample_articles, source_name="Test Source")
        self.assertGreaterEqual(len(alerts), 1)

        alert = alerts[0]
        # Tier 1: Translated Text
        self.assertTrue(bool(alert.translated_text))
        # Tier 2: OCR Ground Truth & Confidence
        self.assertTrue(bool(alert.ocr_raw_text))
        self.assertGreaterEqual(alert.ocr_confidence, 0.90)
        # Tier 3: Page Snapshot
        self.assertTrue(bool(alert.page_snapshot_url))
        self.assertGreaterEqual(alert.page_number, 1)

    def test_dispute_resolution(self):
        """
        Verify dispute resolution:
        Editorial reviewer can adjust translated text and approve audit trail.
        """
        sample_articles = [
            {
                "id": "art_dispute_201",
                "source_name": "Eenadu Hyderabad",
                "category": "economic",
                "title": "RBI Monetary Committee Reviews Inflation Projections",
                "snippet": "Governor discusses repo rates.",
                "ocr_raw_text": "ఆర్బీఐ ద్రవ్యోల్బణ అంచనాల సమీక్ష",
                "ocr_confidence": 0.97,
                "translation_confidence": 0.82,
                "needs_review": True,
                "page_number": 2,
                "page_snapshot_url": "/api/snapshots/sample_doc/2",
            }
        ]

        alerts = alerts_service.evaluate_and_generate_alerts(sample_articles, source_name="Eenadu")
        self.assertGreaterEqual(len(alerts), 1)
        alert_id = alerts[0].id

        # Resolve dispute
        updated = alerts_service.resolve_dispute(
            alert_id=alert_id,
            updated_translation="RBI Monetary Policy Committee Completes Inflation Review",
            audit_verdict="verified"
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.translated_text, "RBI Monetary Policy Committee Completes Inflation Review")
        self.assertFalse(updated.needs_review)


if __name__ == "__main__":
    unittest.main()
