from typing import Dict, Type
from harvester.models import SourceConfig
from harvester.extractors.base import BaseExtractor
from harvester.extractors.sources.toi import ToiExtractor
from harvester.extractors.sources.the_hindu import TheHinduExtractor
from harvester.extractors.sources.eenadu import EenaduExtractor
from harvester.extractors.sources.dainik_bhaskar import DainikBhaskarExtractor
from harvester.extractors.sources.indian_express import IndianExpressExtractor
from harvester.extractors.sources.sakshi import SakshiExtractor
from harvester.extractors.sources.amar_ujala import AmarUjalaExtractor
from harvester.extractors.sources.dt_next import DtNextExtractor
from harvester.extractors.sources.financial_express import FinancialExpressExtractor
from harvester.extractors.sources.loksatta import LoksattaExtractor
from harvester.extractors.sources.lokmat import LokmatExtractor
from harvester.extractors.sources.generic import GenericUniversalExtractor

SPECIALIZED_MAP: Dict[str, Type[BaseExtractor]] = {
    "toi": ToiExtractor,
    "the_hindu": TheHinduExtractor,
    "eenadu": EenaduExtractor,
    "dainik_bhaskar": DainikBhaskarExtractor,
    "indian_express": IndianExpressExtractor,
    "sakshi": SakshiExtractor,
    "amar_ujala": AmarUjalaExtractor,
    "dt_next": DtNextExtractor,
    "financial_express": FinancialExpressExtractor,
    "loksatta": LoksattaExtractor,
    "lokmat": LokmatExtractor,
}


def get_extractor(source: SourceConfig) -> BaseExtractor:
    """
    Returns appropriate extractor instance for the given source config.
    """
    extractor_cls = SPECIALIZED_MAP.get(source.id, GenericUniversalExtractor)
    return extractor_cls(source)
