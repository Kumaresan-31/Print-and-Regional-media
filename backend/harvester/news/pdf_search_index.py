"""
PDF Search Index
================
Persistent per-source JSON index of OCR-translated newspaper pages
from DT Next, Lokmat, Loksatta, Financial Express harvested PDFs.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from harvester.config import settings, PDF_INDEX_DIR
from harvester.news.pdf_parser import pdf_news_parser
from harvester.registry import get_source

logger = logging.getLogger("harvester.pdf_search_index")

# Sources eligible for PDF-native keyword search
INDEXED_SOURCES = {"dt_next", "lokmat", "loksatta", "financial_express"}

SOURCE_ALIASES: Dict[str, str] = {
    "the_financial_express": "financial_express",
    "financialexpress": "financial_express",
    "financial_express": "financial_express",
    "the_finanace_express": "financial_express",
    "finanace_express": "financial_express",
    "fe": "financial_express",
    "the_hindu": "the_hindu",
    "dtnext": "dt_next",
    "dt_next": "dt_next",
    "loksatta": "loksatta",
    "lokmat": "lokmat",
}


class PDFSearchIndex:
    """
    Persistent OCR search index for harvested newspaper PDFs.
    Keyword search runs against English-translated OCR text only.
    Results include page number and snapshot image URL.
    """

    def __init__(self):
        self._memory_index: Dict[str, Dict[str, Any]] = {}
        self._load_all_indexes()

    @staticmethod
    def normalize_source_id(source_id: Optional[str]) -> str:
        if not source_id:
            return ""
        clean = source_id.strip().lower().replace("-", "_")
        return SOURCE_ALIASES.get(clean, clean)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _index_key(self, source_id: str, date: str) -> str:
        return f"{source_id}:{date}"

    def _index_file(self, source_id: str, date: str) -> Path:
        source_dir = PDF_INDEX_DIR / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir / f"{date}.json"

    def _load_all_indexes(self):
        """Load all existing index files from disk into memory on startup."""
        loaded = 0
        try:
            for source_dir in PDF_INDEX_DIR.iterdir():
                if not source_dir.is_dir():
                    continue
                for idx_file in source_dir.glob("*.json"):
                    try:
                        with open(idx_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        key = self._index_key(data["source_id"], data["date"])
                        self._memory_index[key] = data
                        loaded += 1
                    except Exception as e:
                        logger.warning(f"Could not load index file {idx_file}: {e}")
        except Exception:
            pass
        if loaded:
            logger.info(f"PDF Search Index: loaded {loaded} cached index files.")

    def _save_index(self, source_id: str, date: str):
        key = self._index_key(source_id, date)
        data = self._memory_index.get(key)
        if not data:
            return
        idx_file = self._index_file(source_id, date)
        try:
            with open(idx_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Could not save index for {source_id}/{date}: {e}")

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_document(
        self,
        pdf_path: Path,
        source_id: str,
        date: str,
        force: bool = False,
    ) -> bool:
        """
        OCR + translate a harvested PDF and store results in the search index.
        Skips if already indexed unless force=True.
        """
        if source_id not in INDEXED_SOURCES:
            logger.debug(f"Source {source_id} not in INDEXED_SOURCES, skipping index.")
            return False

        key = self._index_key(source_id, date)
        if key in self._memory_index and not force:
            logger.info(f"PDF already indexed: {source_id}/{date}, skipping.")
            return True

        if not pdf_path.exists():
            logger.error(f"PDF not found for indexing: {pdf_path}")
            return False

        source = get_source(source_id)
        source_name = source.name if source else source_id.replace("_", " ").title()
        logger.info(f"Indexing PDF: {pdf_path.name} for {source_name} ({date})...")

        try:
            result = await pdf_news_parser.parse_and_process_pdf(
                file_path=pdf_path,
                source_name=source_name,
                max_pages=16,
            )

            page_map: Dict[int, Dict[str, Any]] = {}

            for art in result.get("categories", {}).get("all", []):
                pg = art.get("page_number", 1)
                if pg not in page_map:
                    page_map[pg] = {
                        "page_num": pg,
                        "snapshot_url": art.get("page_snapshot_url"),
                        "snapshot_path": None,
                        "ocr_text_original": [],
                        "ocr_text_en": [],
                        "ocr_confidence": art.get("ocr_confidence", 0.9),
                        "original_language": art.get("original_language", ""),
                        "stories": [],
                    }
                entry = page_map[pg]

                if art.get("ocr_raw_text"):
                    entry["ocr_text_original"].append(art["ocr_raw_text"])

                full_en = f"{art.get('title', '')} {art.get('snippet', '')}".strip()
                if full_en:
                    entry["ocr_text_en"].append(full_en)

                conf = art.get("ocr_confidence", entry["ocr_confidence"])
                entry["ocr_confidence"] = min(entry["ocr_confidence"], conf)

                if art.get("original_language"):
                    entry["original_language"] = art["original_language"]

                entry["stories"].append({
                    "id": art.get("id"),
                    "title": art.get("title", ""),
                    "snippet": art.get("snippet", ""),
                    "original_title": art.get("original_title"),
                    "original_snippet": art.get("original_snippet"),
                    "category": art.get("category", "all"),
                    "page_num": pg,
                    "ocr_raw_text": art.get("ocr_raw_text"),
                    "ocr_confidence": art.get("ocr_confidence", 0.9),
                    "page_snapshot_url": art.get("page_snapshot_url"),
                    "is_translated": art.get("is_translated", False),
                })

            pages: List[Dict[str, Any]] = []
            for pg_num, entry in page_map.items():
                snap_url = entry.get("snapshot_url", "")
                if snap_url:
                    parts = snap_url.rstrip("/").split("/")
                    if len(parts) >= 3:
                        doc_id_part = parts[-2]
                        snap_dir = settings.snapshots_dir / doc_id_part
                        for ext in [f"page_{pg_num:03d}.jpg", f"page_{pg_num}.jpg"]:
                            candidate = snap_dir / ext
                            if candidate.exists():
                                entry["snapshot_path"] = str(candidate)
                                break
                entry["ocr_text_original"] = "\n\n".join(entry["ocr_text_original"])
                entry["ocr_text_en"] = "\n\n".join(entry["ocr_text_en"])
                pages.append(entry)

            pages.sort(key=lambda x: x["page_num"])

            index_entry = {
                "source_id": source_id,
                "source_name": source_name,
                "date": date,
                "pdf_path": str(pdf_path),
                "doc_id": result.get("doc_id", ""),
                "indexed_at": datetime.now().isoformat(),
                "total_pages": result.get("total_pages", len(pages)),
                "total_stories": result.get("total_articles", 0),
                "snapshots": result.get("snapshots", []),
                "pages": pages,
            }

            self._memory_index[key] = index_entry
            self._save_index(source_id, date)
            logger.info(
                f"PDF indexed: {source_id}/{date} — {len(pages)} pages, "
                f"{result.get('total_articles', 0)} stories"
            )
            return True

        except Exception as e:
            logger.exception(f"Error indexing PDF {pdf_path}: {e}")
            return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        keywords: str,
        source_ids: Optional[List[str]] = None,
        date: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Keyword search against OCR-translated English text from harvested PDFs.
        Returns results ordered by relevance with page_num and snapshot_url.
        """
        clean_kw = keywords.strip().lower()
        if not clean_kw:
            return []

        tokens = [t for t in re.split(r"\s+", clean_kw) if len(t) >= 2]
        if not tokens:
            tokens = [clean_kw]

        self._load_all_indexes()
        target_sources = {self.normalize_source_id(s) for s in source_ids} if source_ids else INDEXED_SOURCES
        results: List[Dict[str, Any]] = []

        for key, idx_doc in self._memory_index.items():
            src_id = idx_doc.get("source_id", "")
            if src_id not in target_sources and self.normalize_source_id(src_id) not in target_sources:
                continue
            doc_date = idx_doc.get("date", "")
            if date and doc_date != date:
                continue

            for page in idx_doc.get("pages", []):
                searchable = (
                    page.get("ocr_text_en", "").lower() + " " +
                    page.get("ocr_text_original", "").lower()
                )
                match_count = sum(1 for t in tokens if t in searchable)
                if match_count == 0:
                    continue

                phrase_match = clean_kw in searchable

                best_story = None
                best_story_score = 0
                for story in page.get("stories", []):
                    s_text = (
                        f"{story.get('title', '')} {story.get('snippet', '')} "
                        f"{story.get('original_title', '') or ''}"
                    ).lower()
                    sc = sum(1 for t in tokens if t in s_text)
                    if sc > best_story_score:
                        best_story_score = sc
                        best_story = story

                en_text = page.get("ocr_text_en", "")
                snippet = _extract_keyword_snippet(en_text, clean_kw, tokens)

                # Fallback to nearest story or first story if title was not in query
                if not best_story and page.get("stories"):
                    for story in page.get("stories"):
                        s_raw = (story.get("ocr_raw_text") or "").lower()
                        if any(t in s_raw for t in tokens):
                            best_story = story
                            break
                    if not best_story:
                        best_story = page.get("stories")[0]

                if best_story and not best_story.get("title"):
                    best_story["title"] = snippet[:80] if snippet else f"{idx_doc.get('source_name')} - Page {page.get('page_num', 1)}"

                import urllib.parse
                doc_id_val = idx_doc.get("doc_id", "")
                pg_num = page.get("page_num", 1)
                story_id = best_story.get("id", "") if best_story else ""
                crop_url = f"/api/pdf-search/crop?doc_id={doc_id_val}&page_num={pg_num}&q={urllib.parse.quote_plus(clean_kw)}&story_id={story_id}&source_id={src_id}&date={doc_date}"

                results.append({
                    "source_id": src_id,
                    "source_name": idx_doc.get("source_name", src_id),
                    "date": doc_date,
                    "doc_id": doc_id_val,
                    "pdf_path": idx_doc.get("pdf_path", ""),
                    "page_num": pg_num,
                    "snapshot_url": page.get("snapshot_url"),
                    "snapshot_path": page.get("snapshot_path"),
                    "crop_url": crop_url,
                    "ocr_confidence": page.get("ocr_confidence", 0.9),
                    "original_language": page.get("original_language", ""),
                    "snippet_en": snippet,
                    "ocr_text_en": page.get("ocr_text_en", ""),
                    "story": best_story,
                    "match_count": match_count,
                    "phrase_match": phrase_match,
                    "_score": match_count * 2 + (5 if phrase_match else 0),
                })

        results.sort(key=lambda x: x["_score"], reverse=True)
        for r in results:
            r.pop("_score", None)
        return results[:limit]

    # ------------------------------------------------------------------
    # Status / Management
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        for key, doc in self._memory_index.items():
            src = doc["source_id"]
            if src not in summary:
                summary[src] = {
                    "source_id": src,
                    "source_name": doc.get("source_name", src),
                    "indexed_dates": [],
                    "total_pages": 0,
                    "total_stories": 0,
                }
            summary[src]["indexed_dates"].append(doc["date"])
            summary[src]["total_pages"] += doc.get("total_pages", 0)
            summary[src]["total_stories"] += doc.get("total_stories", 0)

        return {
            "indexed_sources": list(summary.values()),
            "total_documents": len(self._memory_index),
            "eligible_sources": sorted(INDEXED_SOURCES),
        }

    async def rebuild_index(self, source_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Scan data/archives/ and re-index all eligible PDFs."""
        from harvester.config import ARCHIVE_DIR
        indexed = failed = skipped = 0
        canonical_target = self.normalize_source_id(source_id) if source_id else None
        targets = [canonical_target] if canonical_target else sorted(INDEXED_SOURCES)

        for src_id in targets:
            src_archive = ARCHIVE_DIR / src_id
            if not src_archive.exists():
                continue
            for date_dir in sorted(src_archive.iterdir()):
                if not date_dir.is_dir():
                    continue
                # Sort PDFs by size descending to prioritize full broadsheet edition
                pdf_files = sorted(date_dir.glob("*.pdf"), key=lambda f: f.stat().st_size, reverse=True)
                for pdf_file in pdf_files:
                    key = self._index_key(src_id, date_dir.name)
                    if key in self._memory_index and not force:
                        skipped += 1
                        break
                    ok = await self.index_document(pdf_file, src_id, date_dir.name, force=force)
                    if ok:
                        indexed += 1
                    else:
                        failed += 1
                    break

        return {
            "status": "rebuild_complete",
            "indexed": indexed,
            "skipped": skipped,
            "failed": failed,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_keyword_snippet(text: str, phrase: str, tokens: List[str], max_len: int = 400) -> str:
    """Extract a readable context snippet around the first keyword match."""
    if not text:
        return ""
    lower = text.lower()
    pos = lower.find(phrase)
    if pos < 0:
        for t in tokens:
            pos = lower.find(t)
            if pos >= 0:
                break
    if pos < 0:
        return text[:max_len]
    start = max(0, pos - 80)
    end = min(len(text), pos + max_len - 80)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


# Singleton instance
pdf_search_index = PDFSearchIndex()
