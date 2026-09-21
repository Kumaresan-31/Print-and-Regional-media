import asyncio
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import urllib.error
import urllib.parse
import urllib.request

from harvester.config import settings, DATA_DIR
from harvester.models import NewsAlert, NewsArticle
from harvester.news.pdf_parser import pdf_news_parser
from harvester.news.alerts_service import alerts_service
from harvester.news.service import news_service, CATEGORY_CONFIG
from harvester.registry import get_source, list_sources
from harvester.storage.retention import retention_manager
from harvester.scheduler.cron_manager import cron_scheduler

logger = logging.getLogger("harvester.telegram")


class TelegramBotService:
    """
    Enterprise Telegram Bot Service for:
    1. Real-time broadcast of high-priority & critical news alerts.
    2. Interactive multi-command control (/start, /news, /search, /alerts, /status, /sports, /business).
    3. Direct Newspaper PDF Analysis: Users send PDF files or clippings to the bot, which automatically
       processes them through the 3-Tier OCR & LLM extraction pipeline and replies with the categorized stories.
    """

    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self.file_base = f"https://api.telegram.org/file/bot{self.bot_token}"
        self.chats_file = settings.telegram_registered_chats_file
        self.default_chat_id = settings.telegram_default_chat_id
        self._registered_chats: Dict[str, Dict[str, Any]] = {}
        self._load_chats()

        # Polling state
        self._polling_task: Optional[asyncio.Task] = None
        self._is_polling: bool = False
        self._last_update_id: int = 0

    def _load_chats(self):
        """Loads registered chat IDs from disk."""
        if self.chats_file.exists():
            try:
                with open(self.chats_file, "r", encoding="utf-8") as f:
                    self._registered_chats = json.load(f)
            except Exception as e:
                logger.error(f"Error loading Telegram chats file: {e}")
                self._registered_chats = {}
        else:
            self._registered_chats = {}

        # Ensure default chat is always present
        if self.default_chat_id and self.default_chat_id not in self._registered_chats:
            self._registered_chats[self.default_chat_id] = {
                "id": self.default_chat_id,
                "first_name": "Admin",
                "registered_at": datetime.now().isoformat(),
                "subscribed": True
            }
            self._save_chats()

    def _save_chats(self):
        """Saves registered chat IDs to disk."""
        try:
            self.chats_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.chats_file, "w", encoding="utf-8") as f:
                json.dump(self._registered_chats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving Telegram chats file: {e}")

    def register_chat(self, chat_id: str, user_info: Optional[Dict[str, Any]] = None) -> bool:
        """Registers a chat ID to receive automated broadcasts."""
        cid = str(chat_id)
        is_new = cid not in self._registered_chats
        info = user_info or {}
        self._registered_chats[cid] = {
            "id": cid,
            "first_name": info.get("first_name", "User"),
            "username": info.get("username", ""),
            "registered_at": self._registered_chats.get(cid, {}).get("registered_at", datetime.now().isoformat()),
            "last_active": datetime.now().isoformat(),
            "subscribed": True
        }
        self._save_chats()
        return is_new

    def get_registered_chat_ids(self) -> List[str]:
        """Returns all subscribed chat IDs."""
        return [cid for cid, data in self._registered_chats.items() if data.get("subscribed", True)]

    # --------------------------------------------------------------------------
    # Outbound Telegram API Methods
    # --------------------------------------------------------------------------
    def _call_api_sync(self, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Synchronous HTTP call to Telegram Bot API."""
        url = f"{self.api_base}/{endpoint}"
        headers = {"User-Agent": "Automated-ePaper-Harvester/2.1"}

        try:
            if payload:
                data = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            else:
                req = urllib.request.Request(url, headers=headers, method="GET")

            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                raw_body = e.read().decode("utf-8")
                err_data = json.loads(raw_body)
                desc = err_data.get("description", raw_body)
                logger.warning(f"Telegram API call to '{endpoint}' failed: HTTP {e.code} - {desc}")
                return err_data
            except Exception:
                logger.warning(f"Telegram API call to '{endpoint}' failed: {e}")
                return {"ok": False, "error": str(e), "error_code": e.code}
        except Exception as e:
            logger.warning(f"Telegram API call to '{endpoint}' failed: {e}")
            return {"ok": False, "error": str(e)}

    async def call_api(self, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Async wrapper for Telegram Bot API call."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._call_api_sync, endpoint, payload)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Sends a text message with auto-splitting for messages over 4096 characters."""
        if not text:
            return False

        # Telegram limit is 4096 characters
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        success = True

        for chunk in chunks:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            res = await self.call_api("sendMessage", payload)
            if not res.get("ok"):
                logger.error(f"Failed to send Telegram message to {chat_id}: {res.get('error')}")
                success = False

        return success

    async def broadcast_message(self, text: str, parse_mode: str = "HTML") -> int:
        """Broadcasts a message to all registered chats."""
        chat_ids = self.get_registered_chat_ids()
        if not chat_ids:
            logger.warning("No registered Telegram chats to broadcast to.")
            return 0

        sent_count = 0
        for cid in chat_ids:
            ok = await self.send_message(chat_id=cid, text=text, parse_mode=parse_mode)
            if ok:
                sent_count += 1
        return sent_count

    def _send_document_sync(self, chat_id: str, file_path: Path, caption: str = "") -> bool:
        """Send a PDF/document file to a Telegram chat using multipart upload."""
        import urllib.request
        import mimetypes
        import uuid

        url = f"{self.api_base}/sendDocument"
        boundary = uuid.uuid4().hex

        caption_bytes = caption.encode("utf-8") if caption else b""
        chat_id_bytes = str(chat_id).encode("utf-8")

        try:
            with open(file_path, "rb") as fh:
                file_data = fh.read()

            filename = file_path.name
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            body_parts = []
            # chat_id field
            body_parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n".encode()
                + chat_id_bytes + b"\r\n"
            )
            # caption field
            if caption_bytes:
                body_parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n".encode()
                    + caption_bytes + b"\r\n"
                )
            # parse_mode
            body_parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n".encode()
            )
            # document field
            body_parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode()
                + file_data + b"\r\n"
            )
            body_parts.append(f"--{boundary}--\r\n".encode())

            body = b"".join(body_parts)
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "User-Agent": "Automated-ePaper-Harvester/2.1",
            }
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("ok", False)
        except Exception as e:
            logger.error(f"Failed to send document to Telegram chat {chat_id}: {e}")
            return False

    async def send_document(self, chat_id: str, file_path: Path, caption: str = "") -> bool:
        """Async: Send a PDF/document to a specific Telegram chat."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_document_sync, chat_id, file_path, caption)

    async def broadcast_document(self, file_path: Path, caption: str = "") -> int:
        """Broadcast a document/PDF file to all registered Telegram chats."""
        chat_ids = self.get_registered_chat_ids()
        if not chat_ids:
            logger.warning("No registered Telegram chats to broadcast document to.")
            return 0
        sent_count = 0
        for cid in chat_ids:
            ok = await self.send_document(chat_id=cid, file_path=file_path, caption=caption)
            if ok:
                sent_count += 1
        return sent_count


    async def broadcast_alert(self, alert: NewsAlert) -> int:
        """Formats and broadcasts a real-time NewsAlert to all subscribed Telegram chats."""
        severity_emoji = {
            "critical": "🚨🚨 [CRITICAL ALERT]",
            "high": "⚡ [HIGH PRIORITY]",
            "medium": "📢 [MONITORED ALERT]",
            "low": "ℹ️ [NEWS NOTICE]"
        }.get(alert.severity.lower(), "📢 [NEWS ALERT]")

        urgency_pill = "🔥 BREAKING / URGENT" if alert.severity in ("critical", "high") else "📰 VERIFIED INTELLIGENCE"
        alert_title = alert.translated_text or alert.summary
        created_str = str(alert.created_at)[:19].replace('T', ' ')
        conf_pct = int(getattr(alert, 'ocr_confidence', 0.95) * 100)

        message_lines = [
            f"<b>{severity_emoji}</b>",
            f"<b>{urgency_pill}</b>\n",
            f"📌 <b>Headline:</b> {html.escape(alert_title)}",
            f"🏛️ <b>Publication:</b> {html.escape(alert.source_name)}",
            f"🏷️ <b>Topic:</b> {html.escape(alert.topic or 'National / Regional')}",
            f"🕒 <b>Detected:</b> {created_str} IST\n",
            f"📝 <b>Summary:</b>",
            f"<i>{html.escape(alert.summary)}</i>\n",
            f"🎯 <b>OCR Ground-Truth Confidence:</b> {conf_pct}%",
            f"🔍 <b>Status:</b> <code>VERIFIED</code>",
            f"\n🔗 <a href='http://localhost:8000'>Open Digital Twin Traceability Viewer</a>"
        ]

        formatted_msg = "\n".join(message_lines)
        return await self.broadcast_message(formatted_msg)

    # --------------------------------------------------------------------------
    # Interactive Bot Polling & Command / PDF Ingestion Engine
    # --------------------------------------------------------------------------
    def start_polling(self):
        """Starts background long-polling for incoming messages & PDF uploads."""
        if self._is_polling:
            return
        self._is_polling = True
        loop = asyncio.get_event_loop()
        self._polling_task = loop.create_task(self._poll_loop())
        logger.info(f"Telegram Bot polling started for @Mhjkbktbot (Token ID: {self.bot_token[:10]}...)")

    def stop_polling(self):
        """Stops the polling loop."""
        self._is_polling = False
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
        logger.info("Telegram Bot polling stopped.")

    async def _poll_loop(self):
        """Continuous long-polling loop with exception backoff."""
        # Ensure any conflicting webhook is cleared before starting polling
        try:
            del_res = await self.call_api("deleteWebhook", {"drop_pending_updates": False})
            if del_res.get("ok"):
                logger.info("Telegram webhook checked/cleared for polling mode.")
        except Exception as e:
            logger.debug(f"Telegram deleteWebhook check error: {e}")

        while self._is_polling:
            try:
                payload = {
                    "offset": self._last_update_id + 1 if self._last_update_id > 0 else -1,
                    "timeout": 15,
                    "allowed_updates": ["message", "edited_message"]
                }
                res = await self.call_api("getUpdates", payload)

                if res.get("ok"):
                    updates = res.get("result", [])
                    for update in updates:
                        up_id = update.get("update_id", 0)
                        if up_id > self._last_update_id:
                            self._last_update_id = up_id
                        await self._process_update(update)
                else:
                    err_code = res.get("error_code")
                    if err_code == 409:
                        desc = str(res.get("description", ""))
                        if "webhook" in desc.lower():
                            await self.call_api("deleteWebhook", {"drop_pending_updates": False})
                        await asyncio.sleep(8)
                    else:
                        await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram polling loop error: {e}")
                await asyncio.sleep(4)

    async def _process_update(self, update: Dict[str, Any]):
        """Dispatches an update to the appropriate handler."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = str(chat.get("id"))
        from_user = msg.get("from", {})

        # Auto-register user chat
        self.register_chat(chat_id, user_info=from_user)

        # 1. Document / PDF Upload Handler
        if "document" in msg:
            await self._handle_document_upload(chat_id, msg)
            return

        # 2. Text Command Handler
        text = msg.get("text", "").strip()
        if text:
            await self._handle_text_command(chat_id, text, from_user)

    # --------------------------------------------------------------------------
    # PDF Processing & Pipeline Analysis Reply
    # --------------------------------------------------------------------------
    async def _handle_document_upload(self, chat_id: str, msg: Dict[str, Any]):
        """
        Handles incoming PDF or document attachments sent to the Telegram bot:
        1. Downloads file from Telegram servers.
        2. Ingests into 3-Tier Digital Twin pipeline (RapidOCR, Story Segmentation, Translation).
        3. Evaluates high-priority alerts.
        4. Replies directly in Telegram with structured, categorized news stories.
        """
        doc = msg.get("document", {})
        file_id = doc.get("file_id")
        file_name = doc.get("file_name", f"newspaper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        mime_type = doc.get("mime_type", "")
        caption = (msg.get("caption") or "").strip().lower()

        is_pdf = file_name.lower().endswith(".pdf") or "pdf" in mime_type.lower()
        if not is_pdf:
            await self.send_message(
                chat_id=chat_id,
                text="⚠️ <b>Unsupported File:</b> Please upload an ePaper or newspaper clipping in <b>PDF</b> format."
            )
            return

        # Send processing indicator
        await self.send_message(
            chat_id=chat_id,
            text=(
                f"📥 <b>ePaper / Clipping Received:</b> <code>{html.escape(file_name)}</code>\n\n"
                f"⚙️ <b>Initiating Pipeline Process:</b>\n"
                f"  • 🔍 High-Resolution 300-DPI Page Rendering\n"
                f"  • 🔤 RapidOCR Print Font Text Recognition\n"
                f"  • 🧩 Headline & Story Segmentation\n"
                f"  • 🌐 Named-Entity Preserving Translation\n"
                f"  • 🚨 Automatic High-Priority Threat Analysis\n\n"
                f"<i>Analyzing document now... please wait 15-25 seconds...</i>"
            )
        )

        # 1. Fetch file URL from Telegram
        file_info = await self.call_api("getFile", {"file_id": file_id})
        if not file_info.get("ok"):
            await self.send_message(chat_id=chat_id, text="❌ <b>Error:</b> Could not retrieve file from Telegram servers.")
            return

        remote_file_path = file_info.get("result", {}).get("file_path")
        download_url = f"{self.file_base}/{remote_file_path}"

        # 2. Download and save locally
        upload_dir = DATA_DIR / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        local_file_path = upload_dir / f"tg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}"

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, urllib.request.urlretrieve, download_url, str(local_file_path))
        except Exception as dl_err:
            logger.exception(f"Telegram file download failed: {dl_err}")
            await self.send_message(chat_id=chat_id, text=f"❌ <b>Download Failed:</b> {str(dl_err)}")
            return

        # 3. Process via PDF News Parser Pipeline
        try:
            parsed_data = await pdf_news_parser.parse_and_process_pdf(
                file_path=local_file_path,
                source_name=f"Telegram Upload: {file_name.replace('.pdf', '')}",
                max_pages=8
            )

            # Generate alerts for any critical stories
            all_stories = parsed_data.get("categories", {}).get("all", [])
            generated_alerts = []
            try:
                generated_alerts = alerts_service.evaluate_and_generate_alerts(
                    all_stories,
                    source_name=file_name
                )
            except Exception as alert_err:
                logger.warning(f"Could not generate alerts for Telegram PDF: {alert_err}")

            # 4. Format and reply back to the user with the wanted news
            categories = parsed_data.get("categories", {})
            total_stories = len(all_stories)
            doc_id = parsed_data.get("doc_id", "")
            pages_count = parsed_data.get("total_pages", 1)

            # Filter requested category if user specified in caption (e.g. "sports", "business")
            requested_cat = None
            for cat_key in ["sports", "business", "economic", "political", "crises_disasters"]:
                if cat_key in caption or cat_key.replace("_", " ") in caption:
                    requested_cat = cat_key
                    break

            summary_header = [
                f"✅ <b>PDF Pipeline Analysis Complete!</b>",
                f"📄 <b>Document:</b> <code>{html.escape(file_name)}</code>",
                f"📑 <b>Pages Analyzed:</b> {pages_count} | <b>Stories Extracted:</b> {total_stories}",
                f"🌐 <b>Auto-Translated:</b> {parsed_data.get('translated_count', 0)} regional stories",
                f"🚨 <b>Alerts Generated:</b> {len(generated_alerts)} critical stories",
            ]

            if requested_cat:
                summary_header.append(f"🎯 <i>Showing filtered results for:</i> <b>{requested_cat.upper()}</b>\n")
            else:
                summary_header.append(f"🗞️ <b>Categorized News Digest:</b>\n")

            story_blocks = []

            # If user requested a specific category (e.g., sports), highlight that
            target_categories = [requested_cat] if requested_cat else ["sports", "business", "crises_disasters", "political", "economic"]

            category_headers = {
                "sports": "🏆 <b>SPORTS NEWS</b>",
                "business": "💼 <b>BUSINESS & MARKETS</b>",
                "economic": "📈 <b>ECONOMIC & FISCAL</b>",
                "political": "🏛️ <b>POLITICAL DEVELOPMENTS</b>",
                "crises_disasters": "🚨 <b>CRISES & EMERGENCIES</b>",
            }

            for cat in target_categories:
                cat_stories = categories.get(cat, [])
                if not cat_stories:
                    continue

                story_blocks.append(f"{category_headers.get(cat, f'📰 {cat.upper()}')} ({len(cat_stories)} stories):")
                for s in cat_stories[:4]:  # Show top 4 per category to stay concise
                    title = html.escape(s.get("title", ""))
                    snippet = html.escape(s.get("snippet", "")[:180])
                    orig_title = s.get("original_title")
                    conf = int(s.get("ocr_confidence", 0.9) * 100)

                    block = f"• <b>{title}</b>\n  <i>{snippet}...</i>\n  [OCR Confidence: {conf}%]"
                    if orig_title and orig_title != s.get("title"):
                        block += f"\n  📖 <i>Original:</i> {html.escape(orig_title)}"
                    story_blocks.append(block)
                story_blocks.append("")  # Blank line

            if not story_blocks:
                story_blocks.append("ℹ️ <i>No stories matched the requested filter. Top headlines below:</i>\n")
                for s in all_stories[:5]:
                    story_blocks.append(f"• <b>{html.escape(s.get('title', ''))}</b>\n  <i>{html.escape(s.get('snippet', '')[:160])}...</i>")

            final_reply = "\n".join(summary_header) + "\n" + "\n".join(story_blocks)
            final_reply += f"\n🔍 <a href='http://localhost:8000'>View Complete Document in Web Dashboard</a>"

            await self.send_message(chat_id=chat_id, text=final_reply)

        except Exception as proc_err:
            logger.exception(f"Error processing PDF from Telegram: {proc_err}")
            await self.send_message(chat_id=chat_id, text=f"❌ <b>Processing Failed:</b> {str(proc_err)}")

    # --------------------------------------------------------------------------
    # Interactive Text Commands Handler
    # --------------------------------------------------------------------------
    async def _handle_text_command(self, chat_id: str, text: str, from_user: Dict[str, Any]):
        """Processes interactive Telegram commands from the user."""
        cmd_parts = text.split()
        command = cmd_parts[0].lower()
        args = cmd_parts[1:]

        # 1. /start
        if command in ("/start", "start"):
            welcome = (
                f"👋 <b>Welcome to the ePaper Harvester Bot!</b>\n\n"
                f"I am connected to your enterprise multi-language news harvesting pipeline (50+ newspapers).\n\n"
                f"<b>Available Capabilities:</b>\n"
                f"• 🚨 <b>Automated Alerts:</b> You are now registered to receive breaking & high-priority alerts.\n"
                f"• 📄 <b>PDF Analysis:</b> Send me ANY newspaper PDF clipping directly, and I will analyze it using OCR, translation, and category classification!\n"
                f"• 🏆 <b>Category Feeds:</b> Read strictly filtered Sports, Business, or Political news.\n\n"
                f"<b>Quick Commands:</b>\n"
                f"  /sports - Latest Sports news across publications\n"
                f"  /business - Latest Business & market news\n"
                f"  /news <i>[source] [category]</i> - Fetch specific paper (e.g. <code>/news eenadu sports</code>)\n"
                f"  /search <i>[keyword]</i> - Search with automated English translation\n"
                f"  /alerts - View recent high-priority alerts\n"
                f"  /status - Check pipeline & scheduler status\n"
                f"  /help - Display help menu"
            )
            await self.send_message(chat_id=chat_id, text=welcome)
            return

        # 2. /help
        if command in ("/help", "help"):
            help_text = (
                f"📖 <b>ePaper Harvester Bot Commands:</b>\n\n"
                f"• <b>/news &lt;source_id&gt; [category]</b>\n"
                f"  Fetch live categorized news.\n"
                f"  <i>Examples:</i>\n"
                f"  <code>/news the_hindu sports</code>\n"
                f"  <code>/news eenadu business</code>\n"
                f"  <code>/news dainik_bhaskar all</code>\n\n"
                f"• <b>/sports</b> or <b>/business</b> or <b>/crises</b>\n"
                f"  Direct shortcuts to top category stories.\n\n"
                f"• <b>/search &lt;keywords&gt;</b>\n"
                f"  Search across all Indian newspapers with auto-translation to English.\n"
                f"  <i>Example:</i> <code>/search PayU acquisition</code>\n\n"
                f"• <b>/alerts</b>\n"
                f"  List active high-priority intelligence alerts.\n\n"
                f"• <b>/status</b>\n"
                f"  View system status, scheduler jobs, and storage metrics.\n\n"
                f"💡 <b>Tip:</b> Simply send any newspaper PDF to this chat for instant OCR and categorized story breakdown!"
            )
            await self.send_message(chat_id=chat_id, text=help_text)
            return

        # 3. /sports shortcut
        if command in ("/sports", "sports"):
            source = args[0] if args else "the_hindu"
            await self._handle_news_query(chat_id, source, "sports")
            return

        # 4. /business shortcut
        if command in ("/business", "business"):
            source = args[0] if args else "the_hindu"
            await self._handle_news_query(chat_id, source, "business")
            return

        # 5. /crises shortcut
        if command in ("/crises", "crises"):
            source = args[0] if args else "the_hindu"
            await self._handle_news_query(chat_id, source, "crises_disasters")
            return

        # 6. /news <source_id> [category]
        if command == "/news":
            source_id = args[0] if args else "the_hindu"
            category = args[1] if len(args) > 1 else "all"
            await self._handle_news_query(chat_id, source_id, category)
            return

        # 7. /search <keywords>
        if command == "/search":
            if not args:
                await self.send_message(chat_id=chat_id, text="⚠️ Usage: <code>/search &lt;keywords&gt;</code> (e.g. <code>/search Tata Motors</code>)")
                return
            query = " ".join(args)
            await self._handle_search_query(chat_id, query)
            return

        # 8. /alerts
        if command == "/alerts":
            await self._handle_alerts_query(chat_id)
            return

        # 9. /status
        if command == "/status":
            await self._handle_status_query(chat_id)
            return

        # Default fallback for unrecognized plain text: run as search
        await self.send_message(
            chat_id=chat_id,
            text=f"🔍 <i>Searching news across publications for:</i> <b>{html.escape(text)}</b>..."
        )
        await self._handle_search_query(chat_id, text)

    # --------------------------------------------------------------------------
    # Helper Handlers for Bot Commands
    # --------------------------------------------------------------------------
    async def _handle_news_query(self, chat_id: str, source_id: str, category: str):
        """Fetches and displays live categorized news."""
        source = get_source(source_id)
        source_name = source.name if source else source_id.replace("_", " ").title()

        articles = await news_service.get_news_for_source(source_id=source_id, category=category, limit=6)
        if not articles:
            await self.send_message(
                chat_id=chat_id,
                text=f"📰 <b>{html.escape(source_name)}:</b> No recent articles found for category <code>{category}</code>."
            )
            return

        cat_badge = CATEGORY_CONFIG.get(category, {}).get("icon", "📰") + " " + category.title()
        msg_lines = [
            f"🗞️ <b>{html.escape(source_name)} - {cat_badge}</b>",
            f"Showing {len(articles)} verified stories:\n"
        ]

        for idx, a in enumerate(articles[:5], 1):
            title = html.escape(a.title)
            snippet = html.escape(a.snippet[:160]) if a.snippet else ""
            orig = a.original_title

            item_str = f"<b>{idx}. {title}</b>\n<i>{snippet}...</i>"
            if orig and orig != a.title:
                item_str += f"\n📖 <i>Original:</i> {html.escape(orig)}"
            if a.link and a.link != "#":
                item_str += f"\n🔗 <a href='{a.link}'>Read Verified Story ↗</a>"
            msg_lines.append(item_str + "\n")

        msg_lines.append("🌐 <a href='http://localhost:8000'>Open in ePaper Harvester Dashboard</a>")
        await self.send_message(chat_id=chat_id, text="\n".join(msg_lines))

    async def _handle_search_query(self, chat_id: str, query: str):
        """Searches news across sources with automated translation."""
        results = await news_service.search_news(keywords=query, limit=6)
        if not results:
            await self.send_message(
                chat_id=chat_id,
                text=f"🔍 No recent news articles found matching '<b>{html.escape(query)}</b>'."
            )
            return

        msg_lines = [
            f"🔍 <b>Search Results for:</b> <i>'{html.escape(query)}'</i>",
            f"Found {len(results)} relevant stories across publications:\n"
        ]

        for idx, a in enumerate(results[:5], 1):
            title = html.escape(a.title)
            snippet = html.escape(a.snippet[:150]) if a.snippet else ""
            orig = a.original_title

            block = f"<b>{idx}. [{a.category.upper()}] {title}</b>\n📰 <i>Source: {html.escape(a.source_name)}</i>\n<i>{snippet}...</i>"
            if orig and orig != a.title:
                block += f"\n📖 <i>Original:</i> {html.escape(orig)}"
            if a.link and a.link != "#":
                block += f"\n🔗 <a href='{a.link}'>Read Full Story ↗</a>"
            msg_lines.append(block + "\n")

        msg_lines.append("🌐 <a href='http://localhost:8000'>Open in ePaper Harvester Dashboard</a>")
        await self.send_message(chat_id=chat_id, text="\n".join(msg_lines))

    async def _handle_alerts_query(self, chat_id: str):
        """Lists active high-priority alerts."""
        alerts = alerts_service.get_alerts(limit=5)
        if not alerts:
            await self.send_message(chat_id=chat_id, text="✅ <b>All Clear:</b> No active high-priority alerts right now.")
            return

        msg_lines = [
            f"🚨 <b>Active Intelligence Alerts ({len(alerts)}):</b>\n"
        ]

        for idx, alt in enumerate(alerts, 1):
            sev_emoji = "🚨" if alt.severity == "critical" else "⚡"
            alt_head = alt.translated_text or alt.summary
            alt_date = str(alt.created_at)[:16].replace('T', ' ')
            alt_conf = int(getattr(alt, 'ocr_confidence', 0.95) * 100)
            msg_lines.append(
                f"<b>{idx}. {sev_emoji} [{alt.severity.upper()}] {html.escape(alt_head)}</b>\n"
                f"  📌 Topic: {html.escape(alt.topic or 'Alert')} | Source: {html.escape(alt.source_name)}\n"
                f"  🕒 Detected: {alt_date}\n"
                f"  🎯 Confidence: {alt_conf}%\n"
            )

        msg_lines.append("🔗 <a href='http://localhost:8000'>Open Traceability Dashboard</a>")
        await self.send_message(chat_id=chat_id, text="\n".join(msg_lines))

    async def _handle_status_query(self, chat_id: str):
        """Returns overall system status."""
        sched_status = cron_scheduler.get_status()
        storage = retention_manager.get_storage_stats()
        sources = list_sources()

        status_text = (
            f"📊 <b>ePaper Harvester System Status:</b>\n\n"
            f"• <b>Scheduler:</b> <code>{'RUNNING' if sched_status.get('running') else 'STOPPED'}</code>\n"
            f"• <b>Active Scheduled Jobs:</b> {sched_status.get('jobs_count', 0)}\n"
            f"• <b>Configured Newspapers:</b> {len(sources)} publications\n"
            f"• <b>Archived Editions:</b> {storage.get('total_archives', 0)} files ({storage.get('total_size_mb', 0):.1f} MB)\n"
            f"• <b>Registered Telegram Users:</b> {len(self.get_registered_chat_ids())}\n"
            f"• <b>Default Chat ID:</b> <code>{self.default_chat_id}</code>\n"
            f"• <b>Server:</b> <code>http://localhost:8000</code>"
        )
        await self.send_message(chat_id=chat_id, text=status_text)


# Global singleton instance
telegram_service = TelegramBotService()
