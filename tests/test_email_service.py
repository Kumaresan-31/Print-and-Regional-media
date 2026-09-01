import asyncio
import unittest
from harvester.notifications.email_service import news_email_service
from harvester.models import NewsArticle
from harvester.api.app import send_news_email_digest, preview_news_email_digest, get_email_diagnostics, EmailDigestRequest, EmailPreviewRequest
from fastapi import HTTPException


class TestNewsEmailService(unittest.TestCase):

    def test_build_email_content(self):
        sample_articles = [
            NewsArticle(
                id="art1",
                source_id="toi",
                source_name="The Times of India",
                category="sports",
                title="India Clinches Thrilling Cricket Victory",
                link="https://timesofindia.indiatimes.com/sports",
                snippet="Full match report and highlights of today's final.",
                published_at="Today",
                author="Sports Desk",
                original_title=None,
                original_language=None,
                is_translated=False,
            ),
            NewsArticle(
                id="art2",
                source_id="eenadu",
                source_name="Eenadu",
                category="sports",
                title="National Athletics Championship Medals Tally",
                link="https://www.eenadu.net/sports",
                snippet="Andhra athletes win gold in track events.",
                published_at="Today",
                author="Eenadu",
                original_title="జాతీయ అథ్లెటిక్స్ ఛాంపియన్‌షిప్",
                original_language="Telugu",
                is_translated=True,
            ),
        ]

        text, html_doc = news_email_service.build_email_content(
            category="sports",
            articles=sample_articles,
            recipient_email="cuttyknowledge2006@gmail.com"
        )

        self.assertIn("India Clinches Thrilling Cricket Victory", text)
        self.assertIn("జాతీయ అథ్లెటిక్స్ ఛాంపియన్‌షిప్", text)
        self.assertIn("Auto-Translated from Telugu", html_doc)
        self.assertIn("The Times of India", html_doc)
        self.assertIn("Eenadu", html_doc)
        self.assertIn("cuttyknowledge2006@gmail.com", html_doc)

    def test_invalid_recipient_email(self):
        async def _run():
            with self.assertRaises(HTTPException):
                await send_news_email_digest(EmailDigestRequest(
                    category="sports",
                    recipient_email="invalid-email-address-without-at"
                ))
        asyncio.run(_run())

    def test_smtp_diagnostic(self):
        diag = news_email_service.test_smtp_connection()
        self.assertIn("success", diag)
        self.assertIn("host", diag)
        self.assertEqual(diag["host"], "smtp.gmail.com")

    def test_preview_endpoint(self):
        async def _run():
            res = await preview_news_email_digest(EmailPreviewRequest(
                category="sports",
                max_articles=3
            ))
            self.assertIn("category", res)
            self.assertIn("html_preview", res)
            self.assertIn("articles", res)
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
