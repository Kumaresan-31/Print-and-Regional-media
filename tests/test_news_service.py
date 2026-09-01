import unittest
import asyncio
from harvester.news.service import news_service
from harvester.models import NewsArticle
from harvester.api.app import get_source_news, get_news_categories, search_news_articles
from fastapi import HTTPException


class TestNewsFeedService(unittest.TestCase):

    def test_category_definitions(self):
        categories = news_service.get_categories()
        cat_ids = [c["id"] for c in categories]
        self.assertIn("sports", cat_ids)
        self.assertIn("business", cat_ids)
        self.assertIn("economic", cat_ids)
        self.assertIn("political", cat_ids)
        self.assertIn("crises_disasters", cat_ids)
        self.assertIn("all", cat_ids)

        for c in categories:
            self.assertIn("icon", c)
            self.assertIn("name", c)
            self.assertIn("color", c)

    def test_fallback_news_generation(self):
        for cat in ["sports", "business", "economic", "political", "crises_disasters", "all"]:
            articles = news_service._generate_fallback_news("toi", "The Times of India", cat)
            self.assertGreaterEqual(len(articles), 3)
            for a in articles:
                self.assertIsInstance(a, NewsArticle)
                self.assertEqual(a.category, cat)
                self.assertEqual(a.source_id, "toi")
                self.assertTrue(a.title)
                self.assertTrue(a.link)
                self.assertTrue(a.snippet)

    def test_get_news_for_source_live_or_cached(self):
        async def _run():
            articles = await news_service.get_news_for_source("toi", "sports", limit=5)
            self.assertGreater(len(articles), 0)
            first = articles[0]
            self.assertIsInstance(first, NewsArticle)
            self.assertEqual(first.source_id, "toi")
            self.assertEqual(first.category, "sports")
            self.assertTrue(first.title)

            # Test cache hit
            cached = await news_service.get_news_for_source("toi", "sports", limit=5)
            self.assertEqual(len(cached), len(articles))
            self.assertEqual(cached[0].id, first.id)

        asyncio.run(_run())

    def test_api_news_categories_endpoint(self):
        async def _run():
            data = await get_news_categories()
            self.assertIsInstance(data, list)
            self.assertGreaterEqual(len(data), 6)
        asyncio.run(_run())

    def test_api_news_source_endpoint(self):
        async def _run():
            data = await get_source_news("the_hindu", category="political", limit=5)
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)
            first = data[0]
            self.assertIsInstance(first, NewsArticle)
            self.assertEqual(first.category, "political")
            self.assertTrue(first.title)
            self.assertTrue(first.link)
        asyncio.run(_run())

    def test_regional_script_detection(self):
        from harvester.news.service import contains_regional_script
        self.assertTrue(contains_regional_script("दैनिक भास्कर: ताजा खबर")) # Hindi (Devanagari)
        self.assertTrue(contains_regional_script("అసెంబ్లీ ఎన్నికల ఫలితాలు")) # Telugu
        self.assertTrue(contains_regional_script("தமிழகத்தில் கனமழை")) # Tamil
        self.assertTrue(contains_regional_script("மும்பை")) # Tamil
        self.assertTrue(contains_regional_script("মুম্বই")) # Bengali
        self.assertFalse(contains_regional_script("The Times of India Sports News")) # English only

    def test_translation_to_english(self):
        async def _run():
            news_service._translation_cache["te:అసెంబ్లీ ఎన్నికల ఫలితాలు"] = "Assembly Election Results"
            trans = await news_service.translate_text("అసెంబ్లీ ఎన్నికల ఫలితాలు", "te")
            self.assertIsInstance(trans, str)
            self.assertEqual(trans, "Assembly Election Results")
            from harvester.news.service import contains_regional_script
            self.assertFalse(contains_regional_script(trans))
        asyncio.run(_run())

    def test_search_news_global(self):
        async def _run():
            results = await search_news_articles(q="Tata Motors", limit=5)
            self.assertIsInstance(results, list)
            self.assertGreater(len(results), 0)
            first = results[0]
            self.assertIsInstance(first, NewsArticle)
            self.assertTrue(first.title)
            self.assertTrue(first.link)
        asyncio.run(_run())

    def test_search_news_per_newspaper_with_translation(self):
        async def _run():
            # Search a regional paper like Dainik Bhaskar or Eenadu
            results = await search_news_articles(q="train accident", source_id="eenadu", limit=5)
            self.assertIsInstance(results, list)
            self.assertGreater(len(results), 0)
            for r in results:
                self.assertIsInstance(r, NewsArticle)
                # If translated, verify it has original title and English title
                if r.is_translated:
                    self.assertTrue(r.original_title)
                    self.assertTrue(r.title)
        asyncio.run(_run())

    def test_api_news_invalid_source(self):
        async def _run():
            with self.assertRaises(HTTPException):
                await get_source_news("non_existent_publisher_12345")
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

