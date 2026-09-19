import asyncio
import email
from email.header import decode_header
import imaplib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from PIL import Image
import pytesseract

from harvester.config import settings, INBOX_ATTACHMENTS_DIR, INBOX_INGESTED_DIR, SNAPSHOTS_DIR, DATA_DIR
from harvester.news.pdf_parser import pdf_news_parser, detect_script_language, get_rapid_ocr
from harvester.news.service import news_service
from harvester.translation.llm_translator import llm_translator
from harvester.news.alerts_service import alerts_service

logger = logging.getLogger(__name__)

# Ensure Tesseract OCR executable is configured
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_EXE):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


def decode_mime_header(header_value: Optional[str]) -> str:
    """Decodes MIME encoded subject or header values."""
    if not header_value:
        return ""
    decoded_parts = []
    for part, encoding in decode_header(header_value):
        if isinstance(part, bytes):
            try:
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            except Exception:
                decoded_parts.append(part.decode("latin1", errors="replace"))
        else:
            decoded_parts.append(str(part))
    return "".join(decoded_parts)


class EmailInboxMonitor:
    """
    Automated inbox monitoring and rule-based newspaper clipping extraction service.
    Rules:
      - If Sender matches 'bureau@chennai.com' (or configured sender rules)
      - OR Subject contains 'clipping' (or configured keywords)
    Actions:
      - Download attachment (.pdf, .png, .jpg, .jpeg, .webp, .tiff)
      - OCR text recognition (RapidOCR + Tesseract fallback)
      - Regional language detection & auto-translation to English
      - Categorization (Sports, Business, Economic, Political, Crises & Disasters)
      - Push to main news pipeline & history
    """

    def __init__(self):
        self.imap_host = settings.imap_host
        self.imap_port = settings.imap_port
        self.imap_user = settings.imap_user
        self.imap_password = settings.imap_password
        self.sender_rules = [s.lower() for s in settings.email_monitor_sender_rules]
        self.subject_keywords = [k.lower() for k in settings.email_monitor_subject_keywords]
        self.history_file = DATA_DIR / "inbox_history.json"
        self.last_check_time: Optional[str] = None
        self._load_history()

    def _load_history(self) -> List[Dict[str, Any]]:
        """Loads processed clippings history from disk."""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
                    return self.history
            except Exception as e:
                logger.error(f"Error loading inbox history: {e}")
        self.history = []
        return self.history

    def _save_history(self):
        """Saves processed clippings history to disk."""
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving inbox history: {e}")

    def test_imap_connection(self) -> Dict[str, Any]:
        """
        Tests Gmail IMAP SSL connection and authentication with latency tracking.
        """
        try:
            start_time = datetime.now()
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=10) as mail:
                mail.login(self.imap_user, self.imap_password)
                mail.select("INBOX", readonly=True)
                status, data = mail.search(None, "ALL")
                total_msgs = len(data[0].split()) if status == "OK" and data[0] else 0
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return {
                "success": True,
                "status": "connected",
                "host": self.imap_host,
                "port": self.imap_port,
                "user": self.imap_user,
                "total_messages": total_msgs,
                "latency_ms": latency_ms,
                "error": None,
                "checked_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"IMAP diagnostic test failed: {e}")
            return {
                "success": False,
                "status": "failed",
                "host": self.imap_host,
                "port": self.imap_port,
                "user": self.imap_user,
                "total_messages": 0,
                "latency_ms": None,
                "error": str(e),
                "checked_at": datetime.now().isoformat(),
            }

    def matches_rule(self, sender: str, subject: str) -> Tuple[bool, str]:
        """
        Evaluates whether an incoming email matches extraction rules:
        - Sender matches 'bureau@chennai.com' or 'cuttyknowledge2006@gmail.com'
        - OR Subject contains 'clipping'
        """
        sender_lower = (sender or "").lower()
        subject_lower = (subject or "").lower()

        # Check sender rule
        for rule in self.sender_rules:
            if rule in sender_lower:
                return True, f"Sender match: '{rule}' in '{sender}'"

        # Check subject rule
        for kw in self.subject_keywords:
            if kw in subject_lower:
                return True, f"Subject keyword match: '{kw}' in '{subject}'"

        return False, "No rule matched"

    async def process_attachment_file(
        self,
        file_path: Path,
        email_metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Processes downloaded attachment:
        - Runs OCR if PDF or image
        - Segments text into stories
        - Detects regional language & translates to English
        - Classifies news category
        """
        file_ext = file_path.suffix.lower()
        extracted_articles = []

        if file_ext == ".pdf":
            # Process via NewspaperPDFParser
            logger.info(f"Running PDF OCR & story segmentation on {file_path.name}")
            parse_res = await pdf_news_parser.parse_and_process_pdf(
                file_path=file_path,
                source_name=email_metadata.get("subject") or "Inbox Clipping PDF"
            )
            extracted_articles = parse_res.get("categories", {}).get("all", [])

        elif file_ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]:
            # Process via High-Resolution Image OCR with Snapshot Persistence
            logger.info(f"Running RapidOCR on image clipping: {file_path.name}")
            import hashlib
            doc_id = hashlib.md5(f"{file_path.name}_{file_path.stat().st_mtime}".encode()).hexdigest()[:12]
            doc_dir = SNAPSHOTS_DIR / doc_id
            doc_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = doc_dir / "page_001.jpg"

            # Copy image to snapshots
            try:
                img = Image.open(file_path).convert("RGB")
                img.save(snapshot_path, "JPEG", quality=90)
            except Exception as e:
                logger.warning(f"Error copying snapshot for image {file_path}: {e}")

            snapshot_url = f"/api/snapshots/{doc_id}/1"
            ocr_text = ""
            ocr_conf = 0.98

            try:
                engine = get_rapid_ocr()
                res = engine(str(file_path))
                if res and res.txts:
                    ocr_text = "\n".join(res.txts).strip()
                    if res.scores:
                        ocr_conf = round(sum(res.scores) / len(res.scores), 4)
            except Exception as e:
                logger.warning(f"RapidOCR failed for image {file_path}: {e}")

            if not ocr_text.strip():
                try:
                    ocr_text = pytesseract.image_to_string(img).strip()
                except Exception as te:
                    logger.error(f"Tesseract fallback failed: {te}")

            if not ocr_text.strip():
                ocr_text = f"Clipping from {email_metadata.get('sender')} - Image attachment {file_path.name}"

            # Story segmentation
            segmented = pdf_news_parser.segment_text_into_stories([(1, ocr_text)])
            if not segmented:
                segmented = [{
                    "id": f"clip_{file_path.stem[:8]}",
                    "source_id": "inbox_clipping",
                    "source_name": email_metadata.get("sender", "Inbox Clipping"),
                    "category": "all",
                    "title": file_path.stem.replace("_", " ").title(),
                    "link": f"/data/inbox_attachments/{file_path.name}",
                    "snippet": ocr_text[:300].strip(),
                    "published_at": email_metadata.get("date") or "Today",
                    "author": email_metadata.get("sender") or "Bureau",
                    "original_title": None,
                    "original_language": None,
                    "is_translated": False,
                    "ocr_raw_text": ocr_text,
                    "ocr_confidence": ocr_conf,
                    "page_snapshot_url": snapshot_url,
                    "page_number": 1,
                }]

            # Detect language and translate using LLM with Named Entity Preservation
            for story in segmented:
                category = pdf_news_parser.classify_category(story["title"], story.get("snippet", ""))
                story["category"] = category
                story["link"] = f"/data/inbox_attachments/{file_path.name}"
                story["author"] = email_metadata.get("sender") or "Bureau Correspondent"
                story["published_at"] = email_metadata.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M")
                story["ocr_raw_text"] = story.get("ocr_raw_text") or ocr_text
                story["ocr_confidence"] = ocr_conf
                story["page_snapshot_url"] = snapshot_url
                story["page_number"] = 1
                story["preserved_entities"] = []
                story["translation_confidence"] = 1.0
                story["needs_review"] = False

                # Language detection and LLM translation
                lang_code, lang_name = detect_script_language(story["title"] + " " + story.get("snippet", ""))
                if lang_code != "auto":
                    story["original_title"] = story["title"]
                    story["original_language"] = lang_name
                    tr_title = await llm_translator.translate(story["title"], source_lang=lang_code)
                    story["title"] = tr_title.translated_text
                    story["translation_confidence"] = tr_title.confidence_score
                    story["needs_review"] = tr_title.needs_review
                    story["preserved_entities"] = list(set(tr_title.preserved_entities))

                    if story.get("snippet"):
                        tr_snip = await llm_translator.translate(story["snippet"], source_lang=lang_code)
                        story["snippet"] = tr_snip.translated_text
                        for ent in tr_snip.preserved_entities:
                            if ent not in story["preserved_entities"]:
                                story["preserved_entities"].append(ent)
                    story["is_translated"] = True

                extracted_articles.append(story)

        return extracted_articles

    def register_clipping_in_pipeline(
        self,
        email_metadata: Dict[str, Any],
        attachment_file: Path,
        rule_reason: str,
        articles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Pushes processed clipping record into the main harvester pipeline and history store.
        """
        clipping_id = f"clip_{int(datetime.now().timestamp())}_{attachment_file.stem[:8]}"
        record = {
            "id": clipping_id,
            "ingested_at": datetime.now().isoformat(),
            "sender": email_metadata.get("sender", ""),
            "subject": email_metadata.get("subject", ""),
            "date": email_metadata.get("date", ""),
            "rule_matched": rule_reason,
            "attachment_filename": attachment_file.name,
            "attachment_path": str(attachment_file),
            "attachment_url": f"/data/inbox_attachments/{attachment_file.name}",
            "articles_count": len(articles),
            "articles": articles,
            "categories": list(set(a.get("category", "all") for a in articles)),
            "translated_count": sum(1 for a in articles if a.get("is_translated")),
        }

        # Add to beginning of history list
        self.history.insert(0, record)
        self._save_history()

        # Generate critical alerts for high-priority stories
        try:
            alerts_service.evaluate_and_generate_alerts(articles, source_name=email_metadata.get("sender", "Inbox Clipping"))
        except Exception as e:
            logger.warning(f"Could not generate alerts for clipping: {e}")

        logger.info(f"Registered clipping {clipping_id} with {len(articles)} stories in pipeline!")
        return record

    async def check_inbox(self, limit: int = 15) -> Dict[str, Any]:
        """
        Connects via IMAP SSL to the monitored inbox, inspects messages against rules,
        downloads attachments, executes OCR + translation, and pushes to pipeline.
        """
        self.last_check_time = datetime.now().isoformat()
        checked_emails = 0
        matched_emails = 0
        ingested_clippings = []

        logger.info(f"Connecting to IMAP {self.imap_host}:{self.imap_port} for inbox monitoring...")

        def _fetch_messages():
            messages_to_process = []
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=20) as mail:
                mail.login(self.imap_user, self.imap_password)
                mail.select("INBOX")

                # Search all messages and take the most recent 'limit'
                typ, data = mail.search(None, "ALL")
                if typ != "OK" or not data[0]:
                    return []

                msg_ids = data[0].split()
                recent_ids = msg_ids[-limit:]

                for mid in reversed(recent_ids):
                    typ_f, msg_data = mail.fetch(mid, "(RFC822)")
                    if typ_f == "OK" and msg_data:
                        raw_email = msg_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        messages_to_process.append((mid.decode(), msg))

            return messages_to_process

        loop = asyncio.get_event_loop()
        try:
            messages = await loop.run_in_executor(None, _fetch_messages)
        except Exception as e:
            logger.error(f"IMAP connection or search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "last_check": self.last_check_time,
                "checked_count": 0,
                "matched_count": 0,
                "ingested_count": 0,
                "clippings": [],
            }

        checked_emails = len(messages)

        # Process each message
        for mid, msg in messages:
            sender = decode_mime_header(msg.get("From"))
            subject = decode_mime_header(msg.get("Subject"))
            date_str = decode_mime_header(msg.get("Date"))

            is_match, reason = self.matches_rule(sender, subject)
            if not is_match:
                continue

            matched_emails += 1
            logger.info(f"Rule Matched on Email [{mid}]: {reason}")

            email_meta = {
                "message_id": mid,
                "sender": sender,
                "subject": subject,
                "date": date_str,
            }

            # Extract attachments
            for part in msg.walk():
                content_disposition = part.get("Content-Disposition", "")
                filename = part.get_filename()

                if filename:
                    decoded_filename = decode_mime_header(filename)
                    ext = Path(decoded_filename).suffix.lower()

                    if ext in [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]:
                        # Save attachment
                        safe_filename = f"{mid}_{Path(decoded_filename).stem}{ext}"
                        target_path = INBOX_ATTACHMENTS_DIR / safe_filename

                        payload = part.get_payload(decode=True)
                        if payload:
                            with open(target_path, "wb") as f:
                                f.write(payload)

                            logger.info(f"Downloaded attachment: {safe_filename} ({len(payload)} bytes)")

                            # Run OCR, Translation, and Pipeline Registration
                            articles = await self.process_attachment_file(target_path, email_meta)
                            clipping_record = self.register_clipping_in_pipeline(
                                email_metadata=email_meta,
                                attachment_file=target_path,
                                rule_reason=reason,
                                articles=articles
                            )
                            ingested_clippings.append(clipping_record)

        return {
            "success": True,
            "last_check": self.last_check_time,
            "checked_count": checked_emails,
            "matched_count": matched_emails,
            "ingested_count": len(ingested_clippings),
            "clippings": ingested_clippings,
        }

    async def ingest_uploaded_clipping(
        self,
        file_path: Path,
        sender: str = "bureau@chennai.com",
        subject: str = "Uploaded Newspaper Clipping"
    ) -> Dict[str, Any]:
        """
        Directly ingests a user-uploaded newspaper clipping file (PDF or image),
        executing OCR, translation, and registering in the pipeline.
        """
        timestamp = int(datetime.now().timestamp())
        dest_filename = f"upload_{timestamp}_{file_path.name}"
        dest_path = INBOX_ATTACHMENTS_DIR / dest_filename

        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            dst.write(src.read())

        email_meta = {
            "sender": sender,
            "subject": subject,
            "date": datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0530"),
        }

        articles = await self.process_attachment_file(dest_path, email_meta)

        record = self.register_clipping_in_pipeline(
            email_metadata=email_meta,
            attachment_file=dest_path,
            rule_reason=f"Direct Clipping Upload: {sender}",
            articles=articles
        )

        return record

    async def simulate_incoming_clipping(
        self,
        sender: str = "cuttyknowledge2006@gmail.com",
        subject: str = "Regional Newspaper Clipping - Special Edition",
        file_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Simulates an incoming email from cuttyknowledge2006@gmail.com with clipping attachment
        to test end-to-end rule evaluation, OCR, translation, and pipeline push.
        """
        is_match, reason = self.matches_rule(sender, subject)
        if not is_match:
            raise ValueError(f"Simulation email did not match rules. Sender: '{sender}', Subject: '{subject}'")

        # If no file provided, generate or use existing sample
        if not file_path or not file_path.exists():
            sample_pdf = DATA_DIR / "sample_regional_newspaper.pdf"
            if not sample_pdf.exists():
                sample_pdf = settings.archive_dir / "toi/2026-08-29/toi_delhi_2026-08-29.pdf"
            file_path = sample_pdf

        # Copy to inbox attachments
        timestamp = int(datetime.now().timestamp())
        dest_filename = f"sim_{timestamp}_{file_path.name}"
        dest_path = INBOX_ATTACHMENTS_DIR / dest_filename

        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            dst.write(src.read())

        email_meta = {
            "sender": sender,
            "subject": subject,
            "date": datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0530"),
        }

        # Run OCR & translation
        articles = await self.process_attachment_file(dest_path, email_meta)

        # Register in pipeline
        record = self.register_clipping_in_pipeline(
            email_metadata=email_meta,
            attachment_file=dest_path,
            rule_reason=f"Simulation Rule Match: {reason}",
            articles=articles
        )

        return record

    async def fetch_real_inbox_messages(self, limit: int = 30) -> Dict[str, Any]:
        """
        Connects via IMAP SSL and fetches real incoming emails and attachment metadata
        directly from the live Gmail INBOX.
        """
        def _fetch_sync():
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=15) as mail:
                mail.login(self.imap_user, self.imap_password)
                mail.select("INBOX", readonly=True)
                typ, data = mail.search(None, "ALL")
                if typ != "OK" or not data[0]:
                    return 0, []

                msg_ids = data[0].split()
                total_inbox = len(msg_ids)
                recent_ids = msg_ids[-limit:]

                messages = []
                ingested_ids = {h.get("email_metadata", {}).get("message_id") for h in self.history if h.get("email_metadata")}
                ingested_subjects = {h.get("subject", "").lower() for h in self.history if h.get("subject")}

                for mid in reversed(recent_ids):
                    mid_str = mid.decode()
                    typ_f, msg_data = mail.fetch(mid, "(RFC822)")
                    if typ_f != "OK" or not msg_data:
                        continue

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    sender = decode_mime_header(msg.get("From"))
                    subject = decode_mime_header(msg.get("Subject"))
                    date_str = decode_mime_header(msg.get("Date"))

                    attachments = []
                    snippet = ""

                    for part in msg.walk():
                        content_type = part.get_content_type()
                        fn = part.get_filename()
                        if fn:
                            decoded_fn = decode_mime_header(fn)
                            ext = Path(decoded_fn).suffix.lower()
                            payload_bytes = part.get_payload(decode=True)
                            size = len(payload_bytes) if payload_bytes else 0
                            attachments.append({
                                "filename": decoded_fn,
                                "ext": ext,
                                "size_bytes": size,
                                "is_clipping": ext in [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]
                            })
                        elif content_type == "text/plain" and not snippet:
                            payload = part.get_payload(decode=True)
                            if payload:
                                try:
                                    snippet = payload.decode("utf-8", errors="replace")[:250].strip()
                                except Exception:
                                    snippet = payload.decode("latin1", errors="replace")[:250].strip()

                    is_match, reason = self.matches_rule(sender, subject)
                    is_ingested = (mid_str in ingested_ids) or (subject.lower() in ingested_subjects)

                    messages.append({
                        "id": mid_str,
                        "sender": sender,
                        "subject": subject,
                        "date": date_str,
                        "has_attachments": len(attachments) > 0,
                        "attachments": attachments,
                        "has_clipping_attachment": any(a["is_clipping"] for a in attachments),
                        "snippet": snippet,
                        "is_rule_matched": is_match,
                        "rule_reason": reason,
                        "is_ingested": is_ingested,
                    })

                return total_inbox, messages

        loop = asyncio.get_event_loop()
        try:
            total_count, msgs = await loop.run_in_executor(None, _fetch_sync)
            return {
                "success": True,
                "account": self.imap_user,
                "host": self.imap_host,
                "total_inbox": total_count,
                "fetched_count": len(msgs),
                "messages": msgs,
                "last_check": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to fetch live inbox messages: {e}")
            return {
                "success": False,
                "error": str(e),
                "account": self.imap_user,
                "total_inbox": 0,
                "messages": [],
            }

    async def ingest_email_by_id(self, message_id: str) -> Dict[str, Any]:
        """
        Directly fetches a specific email from the real inbox by its IMAP message ID,
        downloads clipping attachments (or text), executes OCR, translation, and pushes to pipeline.
        """
        def _fetch_single():
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=15) as mail:
                mail.login(self.imap_user, self.imap_password)
                mail.select("INBOX", readonly=True)
                typ_f, msg_data = mail.fetch(message_id.encode(), "(RFC822)")
                if typ_f != "OK" or not msg_data:
                    raise ValueError(f"Message ID {message_id} not found in INBOX")
                return email.message_from_bytes(msg_data[0][1])

        loop = asyncio.get_event_loop()
        msg = await loop.run_in_executor(None, _fetch_single)

        sender = decode_mime_header(msg.get("From"))
        subject = decode_mime_header(msg.get("Subject"))
        date_str = decode_mime_header(msg.get("Date"))

        is_match, reason = self.matches_rule(sender, subject)
        if not is_match:
            reason = f"Manual Ingestion from Inbox: {sender}"

        email_meta = {
            "message_id": message_id,
            "sender": sender,
            "subject": subject,
            "date": date_str,
        }

        ingested_records = []

        # Extract attachments
        for part in msg.walk():
            filename = part.get_filename()
            if filename:
                decoded_fn = decode_mime_header(filename)
                ext = Path(decoded_fn).suffix.lower()
                if ext in [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]:
                    safe_filename = f"{message_id}_{Path(decoded_fn).stem}{ext}"
                    target_path = INBOX_ATTACHMENTS_DIR / safe_filename
                    payload = part.get_payload(decode=True)
                    if payload:
                        with open(target_path, "wb") as f:
                            f.write(payload)

                        articles = await self.process_attachment_file(target_path, email_meta)
                        record = self.register_clipping_in_pipeline(
                            email_metadata=email_meta,
                            attachment_file=target_path,
                            rule_reason=reason,
                            articles=articles
                        )
                        ingested_records.append(record)

        # Fallback to email body text if no clipping attachment
        if not ingested_records:
            body_text = ""
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    p = part.get_payload(decode=True)
                    if p:
                        try:
                            body_text = p.decode("utf-8", errors="replace").strip()
                        except Exception:
                            body_text = p.decode("latin1", errors="replace").strip()
                        break

            if body_text:
                txt_filename = f"{message_id}_email_body.txt"
                target_path = INBOX_ATTACHMENTS_DIR / txt_filename
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(body_text)

                articles = [{
                    "id": f"email_{message_id}",
                    "source_id": "inbox_email",
                    "source_name": sender,
                    "category": pdf_news_parser.classify_category(subject, body_text),
                    "title": subject,
                    "link": f"#email-{message_id}",
                    "snippet": body_text[:400],
                    "published_at": date_str or "Today",
                    "author": sender,
                    "ocr_raw_text": body_text,
                    "ocr_confidence": 1.0,
                    "translation_confidence": 1.0,
                    "needs_review": False,
                    "preserved_entities": [],
                    "page_number": 1,
                    "page_snapshot_url": None,
                    "audit_status": "verified"
                }]

                record = self.register_clipping_in_pipeline(
                    email_metadata=email_meta,
                    attachment_file=target_path,
                    rule_reason=f"Direct Email Text Ingestion: {sender}",
                    articles=articles
                )
                ingested_records.append(record)

        if not ingested_records:
            raise ValueError(f"No extractable attachments or text body found in message {message_id}")

        return ingested_records[0]

    def get_status(self) -> Dict[str, Any]:
        """Returns monitor configuration and current statistics."""
        return {
            "imap_host": self.imap_host,
            "imap_port": self.imap_port,
            "imap_user": self.imap_user,
            "sender_rules": self.sender_rules,
            "subject_keywords": self.subject_keywords,
            "check_interval_minutes": settings.inbox_check_interval_minutes,
            "last_check_time": self.last_check_time,
            "total_clippings_ingested": len(self.history),
            "recent_clippings": self.history[:10],
        }

    def get_clippings(self) -> List[Dict[str, Any]]:
        """Returns all ingested clippings."""
        return self.history


# Singleton instance
email_inbox_monitor = EmailInboxMonitor()
