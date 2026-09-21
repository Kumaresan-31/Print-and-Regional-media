import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from harvester.config import DATA_DIR, settings
from harvester.notifications.whatsapp_service import whatsapp_service
from harvester.notifications.telegram_service import telegram_service
from harvester.notifications.email_service import news_email_service

logger = logging.getLogger("harvester.hardcopy")

HARDCOPY_DIR = DATA_DIR / "hardcopy_uploads"
HARDCOPY_DIR.mkdir(parents=True, exist_ok=True)


class HardcopyManager:
    """
    Manages multi-newspaper hardcopy PDF uploads, OCR progress tracking,
    structured persistence, multi-field filtering, and multi-channel alerts (WhatsApp, Telegram, Email).
    """

    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._articles_cache: List[Dict[str, Any]] = []
        self._load_all_saved_uploads()

    def _load_all_saved_uploads(self):
        """Loads all past hardcopy uploads from disk into memory."""
        all_articles = []
        try:
            for upload_file in sorted(HARDCOPY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    with open(upload_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    arts = data.get("articles", [])
                    all_articles.extend(arts)
                except Exception as e:
                    logger.warning(f"Could not load hardcopy upload file {upload_file}: {e}")
        except Exception as e:
            logger.error(f"Error reading hardcopy uploads directory: {e}")
        self._articles_cache = all_articles
        logger.info(f"HardcopyManager: Loaded {len(self._articles_cache)} total uploaded articles from disk.")

    def create_job(self, file_count: int, file_names: List[str]) -> str:
        """Initializes a new upload tracking job."""
        job_id = uuid.uuid4().hex[:12]
        self._jobs[job_id] = {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(),
            "status": "processing",
            "progress_pct": 5,
            "progress_percentage": 5,
            "current_step": f"Uploaded {file_count} document(s). Initializing FastOCR engine worker pool...",
            "file_count": file_count,
            "file_names": file_names,
            "pages_checklist": [],
            "checklist": [],
            "summary": {
                "newspaper_names": [],
                "publication_dates": [],
                "original_languages": [],
                "total_pages_processed": 0,
                "total_articles_extracted": 0,
            },
            "articles": [],
            "error": None,
        }
        return job_id

    def get_job_progress(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves real-time progress for a job with backward/forward-compatible aliases."""
        job = self._jobs.get(job_id)
        if not job:
            save_path = HARDCOPY_DIR / f"{job_id}.json"
            if save_path.exists():
                try:
                    with open(save_path, "r", encoding="utf-8") as f:
                        disk_job = json.load(f)
                        checklist = disk_job.get("pages_checklist", disk_job.get("checklist", []))
                        self._jobs[job_id] = {
                            "job_id": job_id,
                            "created_at": disk_job.get("created_at", ""),
                            "status": "completed",
                            "progress_pct": 100,
                            "progress_percentage": 100,
                            "current_step": "Extraction completed",
                            "file_count": len(checklist),
                            "file_names": list({p.get("file_name", "") for p in checklist}),
                            "pages_checklist": checklist,
                            "checklist": checklist,
                            "summary": disk_job.get("summary", {}),
                            "articles": disk_job.get("articles", []),
                            "error": None,
                        }
                        return self._jobs[job_id]
                except Exception as ex:
                    logger.debug(f"Could not load persisted job {job_id}: {ex}")
            return None
        job["progress_percentage"] = job.get("progress_pct", 0)
        job["checklist"] = job.get("pages_checklist", [])
        return job

    def update_page_progress(self, job_id: str, page_entry: Dict[str, Any]):
        """Appends or updates a page status entry in real-time."""
        job = self._jobs.get(job_id)
        if not job:
            return

        checklist = job.setdefault("pages_checklist", [])
        fname = page_entry.get("file_name", "document.pdf")
        pnum = page_entry.get("page_num", 1)
        if "name" not in page_entry:
            page_entry["name"] = f"{fname} - Page {pnum}"
        if "title" not in page_entry:
            page_entry["title"] = f"{fname} (Page {pnum})"

        # Check if page already exists to update
        existing = next((p for p in checklist if p.get("file_name") == page_entry.get("file_name") and p.get("page_num") == page_entry.get("page_num")), None)
        if existing:
            existing.update(page_entry)
        else:
            checklist.append(page_entry)

        # Update dynamic progress percentage
        total_expected = max(len(checklist), 1)
        completed = sum(1 for p in checklist if p.get("status") in ("success", "low_confidence", "failed", "blank"))
        pct = min(15 + int((completed / total_expected) * 75), 90)
        job["progress_pct"] = pct
        job["progress_percentage"] = pct
        job["checklist"] = checklist
        job["current_step"] = f"Processed {completed}/{total_expected} broadsheet pages... (Page {page_entry.get('page_num')}: {page_entry.get('status')})"

    def complete_job(self, job_id: str, results: Dict[str, Any]):
        """Marks a job as complete and persists the structured output."""
        job = self._jobs.get(job_id)
        if not job:
            return

        articles = results.get("articles", [])
        summary = results.get("summary", {})
        pages_checklist = results.get("pages_checklist", job.get("pages_checklist", []))

        job["status"] = "completed"
        job["progress_pct"] = 100
        job["progress_percentage"] = 100
        job["current_step"] = f"Extraction complete! {len(articles)} English articles categorized across {summary.get('total_pages_processed', len(pages_checklist))} pages."
        job["articles"] = articles
        job["summary"] = summary
        job["pages_checklist"] = pages_checklist
        job["checklist"] = pages_checklist

        # Save to disk
        save_path = HARDCOPY_DIR / f"{job_id}.json"
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump({
                    "job_id": job_id,
                    "created_at": job["created_at"],
                    "summary": summary,
                    "pages_checklist": pages_checklist,
                    "checklist": pages_checklist,
                    "articles": articles,
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved hardcopy upload results to {save_path}")
        except Exception as e:
            logger.error(f"Could not persist hardcopy upload {job_id}: {e}")

        # Update in-memory search index
        self._articles_cache = articles + self._articles_cache

    def fail_job(self, job_id: str, error_msg: str):
        """Marks a job as failed."""
        job = self._jobs.get(job_id)
        if job:
            job["status"] = "failed"
            job["progress_pct"] = 100
            job["progress_percentage"] = 100
            job["current_step"] = f"Failed: {error_msg}"
            job["error"] = error_msg

    # ----------------------------------------------------------------------
    # Query & Search Filter Engine
    # ----------------------------------------------------------------------
    def get_articles(
        self,
        query: Optional[str] = None,
        newspaper: Optional[str] = None,
        pdf_file: Optional[str] = None,
        date: Optional[str] = None,
        page: Optional[int] = None,
        category: Optional[str] = None,
        language: Optional[str] = None,
        job_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Queries articles from uploaded hardcopy newspapers with flexible multi-filtering.
        Operates strictly on the uploaded newspaper data (zero external APIs).
        """
        if job_id and job_id in self._jobs:
            candidate_list = self._jobs[job_id].get("articles", [])
        else:
            candidate_list = self._articles_cache

        results = []
        q_clean = (query or "").strip().lower()
        cat_clean = (category or "").strip().lower()
        np_clean = (newspaper or "").strip().lower()
        pdf_clean = (pdf_file or "").strip().lower()
        lang_clean = (language or "").strip().lower()

        for art in candidate_list:
            # Category filter (matches primary or secondary)
            if cat_clean and cat_clean != "all":
                art_cat = (art.get("category") or "").lower()
                art_secs = [c.lower() for c in art.get("secondary_categories", [])]
                if cat_clean != art_cat and cat_clean not in art_secs:
                    continue

            # Newspaper filter
            if np_clean and np_clean != "all":
                art_np = (art.get("newspaper") or "").lower()
                if np_clean not in art_np:
                    continue

            # PDF file filter
            if pdf_clean and pdf_clean != "all":
                art_pdf = (art.get("pdf_file") or "").lower()
                if pdf_clean not in art_pdf:
                    continue

            # Date filter
            if date and date != "all":
                art_date = art.get("publication_date") or ""
                if date not in art_date:
                    continue

            # Page number filter
            if page is not None and page > 0:
                p_nums = art.get("page_numbers", [art.get("page_number")])
                if page not in p_nums:
                    continue

            # Language filter
            if lang_clean and lang_clean != "all":
                art_lang = (art.get("original_language") or "").lower()
                if lang_clean not in art_lang:
                    continue

            # Search query (operates on English headline and translated content)
            if q_clean:
                searchable = f"{art.get('headline_english', '')} {art.get('content_english', '')} {art.get('headline_original', '')}".lower()
                if q_clean not in searchable:
                    continue

            # Ensure unified aliases for UI components
            art_copy = dict(art)
            art_copy["page_num"] = art.get("page_num") or art.get("page_number", 1)
            art_copy["confidence"] = art.get("confidence") or art.get("ocr_confidence", 0.95)
            art_copy["english_headline"] = art.get("english_headline") or art.get("headline_english") or art.get("title", "")
            art_copy["original_snippet"] = art.get("original_snippet") or art.get("content_original") or art.get("original_title") or art.get("snippet", "")
            art_copy["english_summary"] = art.get("english_summary") or art.get("content_english") or art.get("snippet", "")

            results.append(art_copy)
            if len(results) >= limit:
                break

        return results

    def get_metadata_filters(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns unique newspapers, PDFs, dates, languages, and category counts."""
        if job_id and job_id in self._jobs:
            items = self._jobs[job_id].get("articles", [])
        else:
            items = self._articles_cache

        newspapers = sorted(list({a.get("newspaper") for a in items if a.get("newspaper")}))
        pdf_files = sorted(list({a.get("pdf_file") for a in items if a.get("pdf_file")}))
        dates = sorted(list({a.get("publication_date") for a in items if a.get("publication_date")}), reverse=True)
        languages = sorted(list({a.get("original_language") for a in items if a.get("original_language")}))
        pages = sorted(list({a.get("page_number") for a in items if a.get("page_number")}))

        category_counts: Dict[str, int] = {}
        for a in items:
            c = a.get("category", "other").lower()
            category_counts[c] = category_counts.get(c, 0) + 1

        return {
            "newspapers": newspapers,
            "pdf_files": pdf_files,
            "dates": dates,
            "languages": languages,
            "pages": pages,
            "total_articles": len(items),
            "category_counts": category_counts,
        }

    # ----------------------------------------------------------------------
    # Multi-Channel Alert Dispatcher (WhatsApp, Telegram, Email)
    # ----------------------------------------------------------------------
    async def dispatch_alerts(
        self,
        articles: List[Dict[str, Any]],
        channels: List[str],
        custom_recipient: Optional[str] = None,
        job_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches alerts for processed hardcopy newspaper articles to WhatsApp, Telegram, and Email.
        """
        results = {"whatsapp": False, "telegram": False, "email": False, "details": {}}
        if not articles:
            return results

        # Format alert message
        top_articles = articles[:5]
        paper_names = ", ".join(list({a.get("newspaper", "Newspaper") for a in top_articles}))
        dates = ", ".join(list({a.get("publication_date", "") for a in top_articles if a.get("publication_date")}))

        # 1. Plain text / Markdown message for WhatsApp & Telegram
        lines = [
            f"🚨 *HARDCOPY NEWSPAPER EXTRACTION REPORT*",
            f"📰 *Source:* {paper_names} | 📅 *Date:* {dates or datetime.now().strftime('%Y-%m-%d')}",
            f"🌐 *Total Articles Extracted:* {len(articles)} | *Strict English Output*",
            "━" * 28,
        ]

        for i, a in enumerate(top_articles):
            cat = a.get("category", "General").title()
            headline = a.get("headline_english", "")
            page_lbl = a.get("continuation_label", f"Page: {a.get('page_number', 1)}")
            orig_lang = a.get("original_language", "Regional")
            orig_hl = a.get("headline_original")
            snippet = a.get("content_english", "")[:220]

            lines.append(f"\n*{i+1}. [{cat.upper()}]* ({page_lbl} • Orig: {orig_lang})")
            lines.append(f"📌 *{headline}*")
            if orig_hl and orig_hl != headline:
                lines.append(f"   _(Orig: {orig_hl[:70]}...)_")
            lines.append(f"📝 {snippet}...")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚡ _Extracted strictly from uploaded broadsheet pages. Zero external APIs used._")

        alert_text = "\n".join(lines)

        # Generate publication-grade PDF report (with clipping, full English, and audit stamp)
        pdf_path = None
        try:
            from harvester.news.search_pdf_exporter import build_hardcopy_article_pdf, build_hardcopy_batch_pdf
            if len(articles) == 1:
                pdf_path = await asyncio.to_thread(build_hardcopy_article_pdf, articles[0])
            elif len(articles) > 1:
                pdf_path = await asyncio.to_thread(build_hardcopy_batch_pdf, articles, paper_names or "Hardcopy Newspaper Digest")
        except Exception as pe:
            logger.warning(f"Could not generate PDF attachment for alert: {pe}")

        # Document captions
        if len(articles) == 1:
            first_art = articles[0]
            cat_name = (first_art.get("category") or "General").upper()
            hl_text = first_art.get("headline_english") or first_art.get("title") or ""
            if len(hl_text) > 140:
                hl_text = hl_text[:137] + "..."
            pg_val = first_art.get("page_number", 1)
            clean_caption = (
                f"📰 {paper_names} • Page {pg_val} | {dates or datetime.now().strftime('%Y-%m-%d')}\n"
                f"📌 [{cat_name}] {hl_text}\n"
                f"📄 Publication-Grade Clipping & 100% English Report"
            )
        else:
            clean_caption = (
                f"📰 {paper_names} | {dates or datetime.now().strftime('%Y-%m-%d')}\n"
                f"📊 {len(articles)} Articles Extracted (100% English Output)\n"
                f"📄 Complete Broadsheet Executive Digest PDF"
            )

        # A. WhatsApp Dispatch (Sends PDF Document Directly)
        if "whatsapp" in channels:
            try:
                wa_success = False
                has_custom = bool(custom_recipient and "@" not in custom_recipient and any(c.isdigit() for c in custom_recipient))
                
                # 1. Primary: Send PDF document if generated
                if pdf_path and pdf_path.exists():
                    if has_custom:
                        wa_success = await whatsapp_service.send_document(
                            chat_id=custom_recipient.strip(),
                            file_path=pdf_path,
                            caption=clean_caption
                        )
                        results["details"]["whatsapp"] = (
                            f"Delivered PDF report to WhatsApp ({custom_recipient.strip()})"
                            if wa_success else f"Failed to deliver PDF to {custom_recipient.strip()}"
                        )
                    else:
                        sent_cnt = await whatsapp_service.broadcast_document(
                            file_path=pdf_path,
                            caption=clean_caption
                        )
                        wa_success = sent_cnt > 0 or len(whatsapp_service.get_registered_chat_ids()) > 0
                        results["details"]["whatsapp"] = (
                            f"Broadcasted PDF report to {sent_cnt} WhatsApp chat(s)"
                            if wa_success else "No registered WhatsApp chats or document send failed"
                        )

                # 2. Fallback: Only send text message if PDF could not be generated or document delivery failed
                if not wa_success and (not pdf_path or not pdf_path.exists()):
                    if has_custom:
                        wa_success = await whatsapp_service.send_message(custom_recipient.strip(), alert_text)
                        results["details"]["whatsapp"] = f"Sent text alert to WhatsApp ({custom_recipient.strip()})" if wa_success else "Failed to send WhatsApp message"
                    else:
                        count = await whatsapp_service.broadcast_message(alert_text)
                        wa_success = count > 0 or len(whatsapp_service.get_registered_chat_ids()) > 0
                        results["details"]["whatsapp"] = f"Broadcasted text alert to {count} WhatsApp chat(s)" if wa_success else "No registered WhatsApp chats"

                results["whatsapp"] = wa_success
            except Exception as e:
                logger.error(f"WhatsApp alert dispatch error: {e}")
                results["details"]["whatsapp"] = str(e)

        # B. Telegram Dispatch (Sends PDF Document Directly)
        if "telegram" in channels:
            try:
                tg_success = False
                has_custom = bool(custom_recipient and "@" not in custom_recipient and any(c.isdigit() for c in custom_recipient))

                # 1. Primary: Send PDF document if generated
                if pdf_path and pdf_path.exists():
                    if has_custom:
                        tg_success = await telegram_service.send_document(
                            chat_id=custom_recipient.strip(),
                            file_path=pdf_path,
                            caption=clean_caption
                        )
                        results["details"]["telegram"] = (
                            f"Delivered PDF report to Telegram ({custom_recipient.strip()})"
                            if tg_success else f"Failed to deliver PDF to Telegram {custom_recipient.strip()}"
                        )
                    else:
                        sent_cnt = await telegram_service.broadcast_document(
                            file_path=pdf_path,
                            caption=clean_caption
                        )
                        tg_success = sent_cnt > 0 or len(telegram_service.get_registered_chat_ids()) > 0
                        results["details"]["telegram"] = (
                            f"Broadcasted PDF report to {sent_cnt} Telegram chat(s)"
                            if tg_success else "No registered Telegram chats or document send failed"
                        )

                # 2. Fallback: Only send text message if PDF could not be generated
                if not tg_success and (not pdf_path or not pdf_path.exists()):
                    tg_text = alert_text.replace("*", "<b>").replace("_", "<i>")
                    tg_formatted = ""
                    in_b = False
                    for part in alert_text.split("*"):
                        if in_b:
                            tg_formatted += f"<b>{part}</b>"
                        else:
                            tg_formatted += part
                        in_b = not in_b

                    if has_custom:
                        tg_success = await telegram_service.send_message(chat_id=custom_recipient.strip(), text=tg_formatted, parse_mode="HTML")
                        results["details"]["telegram"] = f"Sent text alert to Telegram ({custom_recipient.strip()})" if tg_success else "Failed to send message"
                    else:
                        tg_count = await telegram_service.broadcast_message(tg_formatted, parse_mode="HTML")
                        tg_success = tg_count > 0
                        results["details"]["telegram"] = f"Broadcast to {tg_count} Telegram chat(s)"

                results["telegram"] = tg_success
            except Exception as e:
                logger.error(f"Telegram alert dispatch error: {e}")
                results["details"]["telegram"] = str(e)

        # C. Email Digest via Gmail SMTP
        if "email" in channels:
            try:
                target_email = custom_recipient if (custom_recipient and "@" in custom_recipient) else getattr(settings, "email_default_recipient", getattr(settings, "smtp_user", "bureau@chennai.com"))
                # Format HTML Digest
                html_items = []
                for a in top_articles:
                    cat = a.get("category", "General").title()
                    hl = a.get("headline_english", "")
                    body = a.get("content_english", "")
                    orig_hl = a.get("headline_original", "")
                    page_lbl = a.get("continuation_label", f"Page: {a.get('page_number', 1)}")
                    lang = a.get("original_language", "Regional")

                    html_items.append(f"""
                    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-left:4px solid #0284c7; border-radius:8px; padding:16px; margin-bottom:16px;">
                        <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                            <span style="background:#e0f2fe; color:#0369a1; font-weight:700; font-size:12px; padding:3px 8px; border-radius:4px; text-transform:uppercase;">{cat}</span>
                            <span style="color:#64748b; font-size:12px; font-weight:600;">{page_lbl} • {lang}</span>
                        </div>
                        <h3 style="margin:6px 0 8px; color:#0f172a; font-size:16px;">{hl}</h3>
                        {f'<p style="color:#64748b; font-style:italic; font-size:13px; margin:0 0 8px;">Original: {orig_hl}</p>' if orig_hl and orig_hl != hl else ''}
                        <p style="color:#334155; font-size:14px; line-height:1.5; margin:0;">{body}</p>
                    </div>
                    """)

                html_body = f"""
                <html>
                <body style="font-family:Arial,sans-serif; background:#f1f5f9; padding:24px; color:#0f172a;">
                    <div style="max-width:680px; margin:0 auto; background:#ffffff; border-radius:12px; padding:24px; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
                        <div style="border-bottom:2px solid #0284c7; padding-bottom:12px; margin-bottom:20px;">
                            <h2 style="color:#0284c7; margin:0 0 6px;">📰 Hardcopy Newspaper English Digest</h2>
                            <p style="color:#64748b; margin:0; font-size:14px;"><strong>Sources:</strong> {paper_names} | <strong>Date:</strong> {dates or datetime.now().strftime('%Y-%m-%d')}</p>
                            {f'<p style="color:#0284c7; margin:4px 0 0; font-size:13px;">📎 <strong>PDF Report Attached:</strong> {pdf_path.name}</p>' if pdf_path else ''}
                        </div>
                        {"".join(html_items)}
                        <div style="margin-top:24px; padding-top:12px; border-top:1px solid #e2e8f0; text-align:center; color:#94a3b8; font-size:12px;">
                            Extracted strictly from uploaded broadsheet newspaper pages by ePaper Harvester AI.
                        </div>
                    </div>
                </body>
                </html>
                """

                subject = f"📰 [Newspaper Alert] {paper_names}: {len(articles)} Categorized English Stories"
                email_ok, email_msg = await asyncio.to_thread(
                    news_email_service.send_raw_email,
                    recipient_email=target_email,
                    subject=subject,
                    html_body=html_body,
                    attachment_path=pdf_path
                )
                results["email"] = email_ok
                results["details"]["email"] = f"Sent to {target_email}{' with PDF report attached' if pdf_path else ''}" if email_ok else email_msg
            except Exception as e:
                logger.error(f"Email alert dispatch error: {e}")
                results["details"]["email"] = str(e)

        return results


hardcopy_manager = HardcopyManager()
