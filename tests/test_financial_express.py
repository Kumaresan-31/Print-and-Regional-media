import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from harvester.extractors.sources.financial_express import FinancialExpressExtractor, EDITION_MAP

class TestFinancialExpressExtractor(unittest.TestCase):
    def test_editions_map(self):
        self.assertIn("delhi", EDITION_MAP)
        self.assertIn("mumbai", EDITION_MAP)
        self.assertEqual(EDITION_MAP["delhi"][1], "Delhi")

    def test_extractor_instantiation(self):
        from harvester.registry import get_source
        src = get_source("financial_express")
        self.assertIsNotNone(src)
        extractor = FinancialExpressExtractor(src)
        self.assertIsNotNone(extractor)

if __name__ == "__main__":
    unittest.main()
