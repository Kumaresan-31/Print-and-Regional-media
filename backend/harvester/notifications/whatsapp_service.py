import asyncio
import json
import logging
import re
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import requests

from harvester.config import settings, DATA_DIR
from harvester.models import NewsAlert, NewsArticle
from harvester.news.pdf_parser import pdf_news_parser
from harvester.news.alerts_service import alerts_service
from harvester.news.service import news_service, CATEGORY_CONFIG
from harvester.registry import get_source, list_sources
from harvester.storage.retention import retention_manager
from harvester.scheduler.cron_manager import cron_scheduler

logger = logging.getLogger("harvester.whatsapp")


class WhatsAppBotService:
    """
    Enterprise WhatsApp Bot Service powered by Green API (https://green-api.com) for:
    1. Real-time broadcast of high-priority & critical news alerts.
    2. Interactive multi-command control (/start, /news, /search, /alerts, /status, /sports, /business).
    3. Direct Newspaper PDF Analysis: Users send PDF files or clippings to WhatsApp, which automatically
       processes them through the 3-Tier OCR & LLM extraction pipeline and replies with categorized stories.
    4. Sharing harvested PDF search reports from Web UI and API.
    """

    def __init__(self):
        self.id_instance = settings.whatsapp_id_instance
        self.api_token = settings.whatsapp_api_token
        self.api_base = f"{settings.whatsapp_api_base}/waInstance{self.id_instance}"
        self.media_base = f"{settings.whatsapp_media_base}/waInstance{self.id_instance}"
        self.chats_file = settings.whatsapp_registered_chats_file
        self.default_chat_id = self.normalize_chat_id(settings.whatsapp_default_chat_id)
        self._registered_chats: Dict[str, Dict[str, Any]] = {}
        self._load_chats()

        # Polling state
        self._polling_task: Optional[asyncio.Task] = None
        self._is_polling: bool = False
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Automated-ePaper-Harvester/2.1"})

    @staticmethod
    def normalize_chat_id(chat_id: str) -> str:
        """
        Normalizes a phone number or chat identifier into Green API format:
        - Individual chat: '<country_code><number>@c.us' (e.g. '919445707197@c.us')
        - Group chat: '<group_id>@g.us'
        """
        if not chat_id:
            return ""
        cid = str(chat_id).strip()
        if cid.endswith("@c.us") or cid.endswith("@g.us") or cid.endswith("@lid"):
            return cid

        # Remove spaces, dashes, plus sign, brackets
        clean = re.sub(r"[^\d]", "", cid)
        if not clean:
            return cid

        # If 10 digits assume India (+91)
        if len(clean) == 10:
            clean = "91" + clean

        return f"{clean}@c.us"

    def _load_chats(self):
        """Loads registered chat IDs from disk."""
        if self.chats_file.exists():
            try:
                with open(self.chats_file, "r", encoding="utf-8") as f:
                    self._registered_chats = json.load(f)
            except Exception as e:
                logger.error(f"Error loading WhatsApp chats file: {e}")
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
            logger.error(f"Error saving WhatsApp chats file: {e}")

    def register_chat(self, chat_id: str, user_info: Optional[Dict[str, Any]] = None) -> bool:
        """Registers a chat ID to receive automated broadcasts."""
        cid = self.normalize_chat_id(chat_id)
        if not cid:
            return False
        is_new = cid not in self._registered_chats
        info = user_info or {}
        self._registered_chats[cid] = {
            "id": cid,
            "first_name": info.get("senderName") or info.get("chatName") or info.get("first_name") or "User",
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
    # Green API HTTP Core
    # --------------------------------------------------------------------------
    def _call_api_sync(
        self,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        method: str = "POST",
        use_media: bool = False
    ) -> Dict[str, Any]:
        """Synchronous HTTP call to Green API."""
        base = self.media_base if use_media else self.api_base
        url = f"{base}/{endpoint}/{self.api_token}"

        try:
            if method.upper() == "GET":
                resp = self._session.get(url, timeout=25)
            elif method.upper() == "DELETE":
                resp = self._session.delete(url, timeout=25)
            elif files:
                resp = self._session.post(url, data=payload or {}, files=files, timeout=60)
            else:
                resp = self._session.post(url, json=payload or {}, timeout=25)

            if not resp.text.strip():
                return {"ok": resp.status_code == 200, "status_code": resp.status_code}

            try:
                data = resp.json()
                if isinstance(data, dict):
                    data["ok"] = resp.status_code == 200
                elif isinstance(data, list):
                    data = {"ok": resp.status_code == 200, "result": data}
                return data
            except Exception:
                return {"ok": resp.status_code == 200, "raw": resp.text}

        except Exception as e:
            logger.warning(f"WhatsApp API call to '{endpoint}' failed: {e}")
            return {"ok": False, "error": str(e)}

    async def call_api(
        self,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        method: str = "POST",
        use_media: bool = False
    ) -> Dict[str, Any]:
        """Async wrapper for Green API call."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._call_api_sync, endpoint, payload, files, method, use_media)

    # --------------------------------------------------------------------------
    # Outbound WhatsApp API Methods
    # --------------------------------------------------------------------------
    async def send_message(self, chat_id: str, text: str) -> bool:
        """Sends a text message with auto-splitting for messages over 4000 characters."""
        if not text:
            return False

        cid = self.normalize_chat_id(chat_id)
        if not cid:
            return False

        # WhatsApp recommended chunk limit is ~4000 chars
        chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)]
        success = True

        for chunk in chunks:
            payload = {
                "chatId": cid,
                "message": chunk,
            }
            res = await self.call_api("sendMessage", payload=payload, method="POST")
            if not res.get("ok") and not res.get("idMessage"):
                logger.error(f"Failed to send WhatsApp message to {cid}: {res.get('error') or res}")
                success = False

        return success

    async def broadcast_message(self, text: str) -> int:
        """Broadcasts a message to all registered chats."""
        chat_ids = self.get_registered_chat_ids()
        if not chat_ids:
            logger.warning("No registered WhatsApp chats to broadcast to.")
            return 0

        sent_count = 0
        for cid in chat_ids:
            ok = await self.send_message(chat_id=cid, text=text)
            if ok:
                sent_count += 1
        return sent_count

    def _send_document_sync(self, chat_id: str, file_path: Path, caption: str = "") -> bool:
        """Send a PDF/document file to a WhatsApp chat using Green API sendFileByUpload."""
        cid = self.normalize_chat_id(chat_id)
        if not cid or not file_path.exists():
            return False

        filename = file_path.name
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        try:
            with open(file_path, "rb") as fh:
                file_bytes = fh.read()

            files = {"file": (filename, file_bytes, mime_type)}
            payload = {
                "chatId": cid,
                "fileName": filename,
                "caption": caption or ""
            }
            res = self._call_api_sync("sendFileByUpload", payload=payload, files=files, method="POST", use_media=True)
            return bool(res.get("ok") or res.get("idMessage"))
        except Exception as e:
            logger.error(f"Failed to send document to WhatsApp chat {cid}: {e}")
            return False

    async def send_document(self, chat_id: str, file_path: Path, caption: str = "") -> bool:
        """Async: Send a PDF/document to a specific WhatsApp chat."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_document_sync, chat_id, file_path, caption)

    async def broadcast_document(self, file_path: Path, caption: str = "") -> int:
        """Broadcast a document/PDF file to all registered WhatsApp chats."""
        chat_ids = self.get_registered_chat_ids()
        if not chat_ids:
            logger.warning("No registered WhatsApp chats to broadcast document to.")
            return 0
        sent_count = 0
        for cid in chat_ids:
            ok = await self.send_document(chat_id=cid, file_path=file_path, caption=caption)
            if ok:
                sent_count += 1
        return sent_count

    def format_alert_message(self, alert: NewsAlert) -> str:
        """Formats a user-selected NewsAlert into a high-visibility WhatsApp message."""
        severity_emoji = {
            "critical": "🚨🚨 *[CRITICAL ALERT]*",
            "high": "⚡ *[HIGH PRIORITY]*",
            "medium": "📢 *[MONITORED ALERT]*",
            "low": "ℹ️ *[NEWS NOTICE]*"
        }.get(alert.severity.lower(), "📢 *[NEWS ALERT]*")

        urgency_pill = "*🔥 BREAKING / URGENT*" if alert.severity in ("critical", "high") else "*📰 VERIFIED INTELLIGENCE*"
        alert_title = alert.translated_text or alert.summary
        created_str = str(alert.created_at)[:19].replace('T', ' ')
        conf_pct = int(getattr(alert, 'ocr_confidence', 0.95) * 100)

        message_lines = [
            f"{severity_emoji}",
            f"{urgency_pill}\n",
            f"📌 *Headline:* {alert_title}",
            f"🏛️ *Publication:* {alert.source_name}",
            f"🏷️ *Topic:* {alert.topic or 'National / Regional'}",
            f"🕒 *Detected:* {created_str} IST\n",
            f"📝 *Summary:*",
            f"_{alert.summary}_\n",
            f"🎯 *OCR Ground-Truth Confidence:* {conf_pct}%",
            f"🔍 *Status:* VERIFIED (User Selected)",
            f"\n🔗 *Open Traceability Viewer:* http://localhost:8000"
        ]

        return "\n".join(message_lines)

    async def send_alert(self, alert: NewsAlert, chat_id: Optional[str] = None) -> int:
        """Sends a specific user-selected NewsAlert to a chat or broadcasts to registered chats."""
        formatted_msg = self.format_alert_message(alert)
        if chat_id:
            ok = await self.send_message(chat_id=chat_id, text=formatted_msg)
            return 1 if ok else 0
        return await self.broadcast_message(formatted_msg)

    async def broadcast_alert(self, alert: NewsAlert) -> int:
        """Formats and broadcasts a NewsAlert to all subscribed WhatsApp chats."""
        return await self.send_alert(alert)

    # --------------------------------------------------------------------------
    # Interactive WhatsApp Polling & Command / PDF Ingestion Engine
    # --------------------------------------------------------------------------
    def start_polling(self):
        """Starts background long-polling for incoming WhatsApp messages & PDF uploads."""
        if self._is_polling:
            return
        self._is_polling = True
        loop = asyncio.get_event_loop()
        self._polling_task = loop.create_task(self._poll_loop())
        logger.info(f"WhatsApp Bot polling started for Green API instance {self.id_instance}")

    def stop_polling(self):
        """Stops the polling loop."""
        self._is_polling = False
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
        logger.info("WhatsApp Bot polling stopped.")

    async def _poll_loop(self):
        """Continuous polling loop using receiveNotification & deleteNotification."""
        # Ensure incoming webhooks are active for polling queue
        try:
            await self.call_api("setSettings", payload={"webhookUrl": "", "incomingWebhook": "yes", "stateWebhook": "yes"})
        except Exception as set_err:
            logger.warning(f"Could not auto-configure Green API settings: {set_err}")

        while self._is_polling:
            try:
                res = await self.call_api("receiveNotification", method="GET")
                if res and isinstance(res, dict) and "receiptId" in res:
                    receipt_id = res.get("receiptId")
                    body = res.get("body", {})

                    try:
                        await self._process_notification(body)
                    except Exception as proc_err:
                        logger.error(f"Error processing WhatsApp notification: {proc_err}")
                    finally:
                        # Always delete notification to advance queue
                        if receipt_id:
                            del_endpoint = f"deleteNotification/{self.api_token}/{receipt_id}"
                            del_url = f"{self.api_base}/{del_endpoint}"
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, self._session.delete, del_url)

                    # Quick yield to avoid starving event loop
                    await asyncio.sleep(0.2)
                else:
                    # Queue is empty, pause before next poll
                    await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WhatsApp polling loop error: {e}")
                await asyncio.sleep(4.0)

    async def _process_notification(self, body: Dict[str, Any]):
        """Dispatches an incoming notification to appropriate document or command handler."""
        type_webhook = body.get("typeWebhook")
        if type_webhook != "incomingMessageReceived":
            return

        sender_data = body.get("senderData", {})
        chat_id = sender_data.get("chatId")
        if not chat_id:
            return

        # Auto-register user chat
        self.register_chat(chat_id, user_info=sender_data)

        message_data = body.get("messageData", {})
        type_message = message_data.get("typeMessage")

        # 1. Document / PDF Upload Handler
        if type_message in ("fileMessage", "documentMessage"):
            await self._handle_document_upload(chat_id, message_data, sender_data)
            return

        # 2. Text Command Handler
        text = ""
        if type_message == "textMessage":
            text = message_data.get("textMessageData", {}).get("textMessage", "")
        elif type_message == "extendedTextMessage":
            text = message_data.get("extendedTextMessageData", {}).get("text", "")

        text = text.strip()
        if text:
            await self._handle_text_command(chat_id, text, sender_data)

    # --------------------------------------------------------------------------
    # PDF Processing & Pipeline Analysis Reply
    # --------------------------------------------------------------------------
    async def _handle_document_upload(self, chat_id: str, message_data: Dict[str, Any], sender_data: Dict[str, Any]):
        """
        Handles incoming PDF or document attachments sent to WhatsApp:
        1. Downloads file from Green API servers.
        2. Ingests into 3-Tier Digital Twin pipeline (RapidOCR, Story Segmentation, Translation).
        3. Evaluates high-priority alerts.
        4. Replies directly in WhatsApp with structured, categorized news stories.
        """
        file_data = message_data.get("fileMessageData", {})
        download_url = file_data.get("downloadUrl")
        file_name = file_data.get("fileName", f"newspaper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        caption = (file_data.get("caption") or "").strip().lower()

        # If downloadUrl is missing, try downloadFile API
        if not download_url:
            msg_id = message_data.get("idMessage")
            if msg_id:
                dl_res = await self.call_api("downloadFile", payload={"chatId": chat_id, "idMessage": msg_id})
                download_url = dl_res.get("downloadUrl")

        is_pdf = file_name.lower().endswith(".pdf")
        if not is_pdf:
            await self.send_message(
                chat_id=chat_id,
                text="⚠️ *Unsupported File:* Please upload an ePaper or newspaper clipping in *PDF* format."
            )
            return

        # Send processing indicator
        await self.send_message(
            chat_id=chat_id,
            text=(
                f"📥 *ePaper / Clipping Received:* `{file_name}`\n\n"
                f"⚙️ *Initiating Pipeline Process:*\n"
                f"  • 🔍 High-Resolution 300-DPI Page Rendering\n"
                f"  • 🔤 RapidOCR Print Font Text Recognition\n"
                f"  • 🧩 Headline & Story Segmentation\n"
                f"  • 🌐 Named-Entity Preserving Translation\n"
                f"  • 🚨 Automatic High-Priority Threat Analysis\n\n"
                f"_Analyzing document now... please wait 15-25 seconds..._"
            )
        )

        if not download_url:
            await self.send_message(chat_id=chat_id, text="❌ *Error:* Could not retrieve file download link from WhatsApp.")
            return

        # Download and save locally
        upload_dir = DATA_DIR / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        local_file_path = upload_dir / f"wa_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}"

        try:
            loop = asyncio.get_event_loop()
            def _download():
                r = requests.get(download_url, timeout=60)
                r.raise_for_status()
                with open(local_file_path, "wb") as f:
                    f.write(r.content)
            await loop.run_in_executor(None, _download)
        except Exception as dl_err:
            logger.exception(f"WhatsApp file download failed: {dl_err}")
            await self.send_message(chat_id=chat_id, text=f"❌ *Download Failed:* {str(dl_err)}")
            return

        # Process via PDF News Parser Pipeline
        try:
            parsed_data = await pdf_news_parser.parse_and_process_pdf(
                file_path=local_file_path,
                source_name=f"WhatsApp Upload: {file_name.replace('.pdf', '')}",
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
                logger.warning(f"Could not generate alerts for WhatsApp PDF: {alert_err}")

            categories = parsed_data.get("categories", {})
            total_stories = len(all_stories)
            pages_count = parsed_data.get("total_pages", 1)

            requested_cat = None
            for cat_key in ["sports", "business", "economic", "political", "crises_disasters"]:
                if cat_key in caption or cat_key.replace("_", " ") in caption:
                    requested_cat = cat_key
                    break

            summary_header = [
                f"✅ *PDF Pipeline Analysis Complete!*",
                f"📄 *Document:* `{file_name}`",
                f"📑 *Pages Analyzed:* {pages_count} | *Stories Extracted:* {total_stories}",
                f"🌐 *Auto-Translated:* {parsed_data.get('translated_count', 0)} regional stories",
                f"🚨 *Alerts Generated:* {len(generated_alerts)} critical stories",
            ]

            if requested_cat:
                summary_header.append(f"🎯 _Showing filtered results for:_ *{requested_cat.upper()}*\n")
            else:
                summary_header.append(f"🗞️ *Categorized News Digest:*\n")

            story_blocks = []
            target_categories = [requested_cat] if requested_cat else ["sports", "business", "crises_disasters", "political", "economic"]

            category_headers = {
                "sports": "🏆 *SPORTS NEWS*",
                "business": "💼 *BUSINESS & MARKETS*",
                "economic": "📈 *ECONOMIC & FISCAL*",
                "political": "🏛️ *POLITICAL DEVELOPMENTS*",
                "crises_disasters": "🚨 *CRISES & EMERGENCIES*",
            }

            for cat in target_categories:
                cat_stories = categories.get(cat, [])
                if not cat_stories:
                    continue

                story_blocks.append(f"{category_headers.get(cat, f'📰 {cat.upper()}')} ({len(cat_stories)} stories):")
                for s in cat_stories[:4]:
                    title = s.get("title", "")
                    snippet = (s.get("snippet", "")[:180]).replace("\n", " ")
                    orig_title = s.get("original_title")
                    conf = int(s.get("ocr_confidence", 0.9) * 100)

                    block = f"• *{title}*\n  _{snippet}..._\n  [OCR Confidence: {conf}%]"
                    if orig_title and orig_title != s.get("title"):
                        block += f"\n  📖 _Original:_ {orig_title}"
                    story_blocks.append(block)
                story_blocks.append("")

            if not story_blocks:
                story_blocks.append("ℹ️ _No stories matched the requested filter. Top headlines below:_\n")
                for s in all_stories[:5]:
                    story_blocks.append(f"• *{s.get('title', '')}*\n  _{s.get('snippet', '')[:160]}..._")

            final_reply = "\n".join(summary_header) + "\n" + "\n".join(story_blocks)
            final_reply += f"\n🔍 *View Complete Document in Web Dashboard:*\nhttp://localhost:8000"

            await self.send_message(chat_id=chat_id, text=final_reply)

        except Exception as proc_err:
            logger.exception(f"Error processing PDF from WhatsApp: {proc_err}")
            await self.send_message(chat_id=chat_id, text=f"❌ *Processing Failed:* {str(proc_err)}")

    # --------------------------------------------------------------------------
    # Interactive Text Commands Handler
    # --------------------------------------------------------------------------
    async def _handle_text_command(self, chat_id: str, text: str, sender_data: Dict[str, Any]):
        """Processes interactive WhatsApp commands from the user."""
        cmd_parts = text.split()
        command = cmd_parts[0].lower()
        args = cmd_parts[1:]

        # 1. /start
        if command in ("/start", "start"):
            welcome = (
                f"👋 *Welcome to the ePaper Harvester WhatsApp Bot!*\n\n"
                f"I am connected to your enterprise multi-language news harvesting pipeline (50+ newspapers).\n\n"
                f"*Available Capabilities:*\n"
                f"• 🚨 *Automated Alerts:* You are registered to receive breaking & high-priority alerts.\n"
                f"• 📄 *PDF Analysis:* Send me ANY newspaper PDF clipping directly, and I will analyze it using OCR, translation, and category classification!\n"
                f"• 🏆 *Category Feeds:* Read strictly filtered Sports, Business, or Political news.\n\n"
                f"*Quick Commands:*\n"
                f"  /sports - Latest Sports news across publications\n"
                f"  /business - Latest Business & market news\n"
                f"  /news _[source] [category]_ - Fetch specific paper (e.g. `/news eenadu sports`)\n"
                f"  /search _[keyword]_ - Search with automated English translation\n"
                f"  /alerts - View recent high-priority alerts\n"
                f"  /status - Check pipeline & scheduler status\n"
                f"  /help - Display help menu"
            )
            await self.send_message(chat_id=chat_id, text=welcome)
            return

        # 2. /help
        if command in ("/help", "help"):
            help_text = (
                f"📖 *ePaper Harvester WhatsApp Bot Commands:*\n\n"
                f"• */news <source_id> [category]*\n"
                f"  Fetch live categorized news.\n"
                f"  _Examples:_\n"
                f"  `/news the_hindu sports`\n"
                f"  `/news eenadu business`\n"
                f"  `/news dainik_bhaskar all`\n\n"
                f"• */sports* or */business* or */crises*\n"
                f"  Direct shortcuts to top category stories.\n\n"
                f"• */search <keywords>*\n"
                f"  Search across all Indian newspapers with auto-translation to English.\n"
                f"  _Example:_ `/search PayU acquisition`\n\n"
                f"• */alerts*\n"
                f"  List active high-priority intelligence alerts.\n\n"
                f"• */status*\n"
                f"  View system status, scheduler jobs, and storage metrics.\n\n"
                f"💡 *Tip:* Simply send any newspaper PDF to this chat for instant OCR and categorized story breakdown!"
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
                await self.send_message(chat_id=chat_id, text="⚠️ Usage: `/search <keywords>` (e.g. `/search Tata Motors`)")
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
            text=f"🔍 _Searching news across publications for:_ *{text}*..."
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
                text=f"📰 *{source_name}:* No recent articles found for category `{category}`."
            )
            return

        cat_badge = CATEGORY_CONFIG.get(category, {}).get("icon", "📰") + " " + category.title()
        msg_lines = [
            f"🗞️ *{source_name} - {cat_badge}*",
            f"Showing {len(articles)} verified stories:\n"
        ]

        for idx, a in enumerate(articles[:5], 1):
            title = a.title
            snippet = (a.snippet[:160]).replace("\n", " ") if a.snippet else ""
            orig = a.original_title

            item_str = f"*{idx}. {title}*\n_{snippet}..._"
            if orig and orig != a.title:
                item_str += f"\n📖 _Original:_ {orig}"
            if a.link and a.link != "#":
                item_str += f"\n🔗 Read Verified Story: {a.link}"
            msg_lines.append(item_str + "\n")

        msg_lines.append("🌐 Open in Dashboard: http://localhost:8000")
        await self.send_message(chat_id=chat_id, text="\n".join(msg_lines))

    async def _handle_search_query(self, chat_id: str, query: str):
        """Searches news across sources with automated translation."""
        results = await news_service.search_news(keywords=query, limit=6)
        if not results:
            await self.send_message(
                chat_id=chat_id,
                text=f"🔍 No recent news articles found matching '*{query}*'."
            )
            return

        msg_lines = [
            f"🔍 *Search Results for:* _'{query}'_",
            f"Found {len(results)} relevant stories across publications:\n"
        ]

        for idx, a in enumerate(results[:5], 1):
            title = a.title
            snippet = (a.snippet[:150]).replace("\n", " ") if a.snippet else ""
            orig = a.original_title

            block = f"*{idx}. [{a.category.upper()}] {title}*\n📰 _Source: {a.source_name}_\n_{snippet}..._"
            if orig and orig != a.title:
                block += f"\n📖 _Original:_ {orig}"
            if a.link and a.link != "#":
                block += f"\n🔗 Read Full Story: {a.link}"
            msg_lines.append(block + "\n")

        msg_lines.append("🌐 Open in Dashboard: http://localhost:8000")
        await self.send_message(chat_id=chat_id, text="\n".join(msg_lines))

    async def _handle_alerts_query(self, chat_id: str):
        """Lists active high-priority alerts."""
        alerts = alerts_service.get_alerts(limit=5)
        if not alerts:
            await self.send_message(chat_id=chat_id, text="✅ *All Clear:* No active high-priority alerts right now.")
            return

        msg_lines = [
            f"🚨 *Active Intelligence Alerts ({len(alerts)}):*\n"
        ]

        for idx, alt in enumerate(alerts, 1):
            sev_emoji = "🚨" if alt.severity == "critical" else "⚡"
            alt_head = alt.translated_text or alt.summary
            alt_date = str(alt.created_at)[:16].replace('T', ' ')
            alt_conf = int(getattr(alt, 'ocr_confidence', 0.95) * 100)
            msg_lines.append(
                f"*{idx}. {sev_emoji} [{alt.severity.upper()}] {alt_head}*\n"
                f"  📌 Topic: {alt.topic or 'Alert'} | Source: {alt.source_name}\n"
                f"  🕒 Detected: {alt_date}\n"
                f"  🎯 Confidence: {alt_conf}%\n"
            )

        msg_lines.append("🔗 Open Traceability Dashboard: http://localhost:8000")
        await self.send_message(chat_id=chat_id, text="\n".join(msg_lines))

    async def _handle_status_query(self, chat_id: str):
        """Returns overall system status."""
        sched_status = cron_scheduler.get_status()
        storage = retention_manager.get_storage_stats()
        sources = list_sources()

        # Check Green API state
        state_info = await self.call_api("getStateInstance", method="GET")
        wa_state = state_info.get("stateInstance", "unknown") if state_info.get("ok") else "error"

        status_text = (
            f"📊 *ePaper Harvester System Status:*\n\n"
            f"• *Scheduler:* `{'RUNNING' if sched_status.get('running') else 'STOPPED'}`\n"
            f"• *Active Scheduled Jobs:* {sched_status.get('jobs_count', 0)}\n"
            f"• *Configured Newspapers:* {len(sources)} publications\n"
            f"• *Archived Editions:* {storage.get('total_archives', 0)} files ({storage.get('total_size_mb', 0):.1f} MB)\n"
            f"• *WhatsApp Instance Status:* `{wa_state}`\n"
            f"• *Registered WhatsApp Users:* {len(self.get_registered_chat_ids())}\n"
            f"• *Default WhatsApp Chat:* `{self.default_chat_id}`\n"
            f"• *Server:* `http://localhost:8000`"
        )
        await self.send_message(chat_id=chat_id, text=status_text)


# Global singleton instance
whatsapp_service = WhatsAppBotService()
