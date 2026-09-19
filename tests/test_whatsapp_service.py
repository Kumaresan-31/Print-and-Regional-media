import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from datetime import datetime

from harvester.notifications.whatsapp_service import WhatsAppBotService
from harvester.models import NewsAlert


import tempfile
import shutil

class TestWhatsAppBotService(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.service = WhatsAppBotService()
        self.service.chats_file = Path(self.temp_dir) / "test_whatsapp_chats.json"
        self.service._registered_chats = {}
        self.service._load_chats()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_normalize_chat_id(self):
        # 10 digit Indian number
        self.assertEqual(WhatsAppBotService.normalize_chat_id("9445707197"), "919445707197@c.us")
        # With +91
        self.assertEqual(WhatsAppBotService.normalize_chat_id("+91 94457 07197"), "919445707197@c.us")
        # Already formatted @c.us
        self.assertEqual(WhatsAppBotService.normalize_chat_id("919445707197@c.us"), "919445707197@c.us")
        # Group format @g.us
        self.assertEqual(WhatsAppBotService.normalize_chat_id("120363029999-group@g.us"), "120363029999-group@g.us")
        # Empty
        self.assertEqual(WhatsAppBotService.normalize_chat_id(""), "")

    def test_register_and_get_chats(self):
        test_chat = "919888877777@c.us"
        is_new = self.service.register_chat(test_chat, {"senderName": "Tester"})
        self.assertIn(test_chat, self.service.get_registered_chat_ids())
        self.assertEqual(self.service._registered_chats[test_chat]["first_name"], "Tester")

    @patch.object(WhatsAppBotService, "call_api", new_callable=AsyncMock)
    def test_send_message(self, mock_call):
        import asyncio
        mock_call.return_value = {"ok": True, "idMessage": "MSG_123"}
        
        async def _test():
            res = await self.service.send_message("919445707197", "Hello WhatsApp World!")
            self.assertTrue(res)
            mock_call.assert_called_once()
            call_args = mock_call.call_args
            self.assertEqual(call_args.kwargs["payload"]["chatId"], "919445707197@c.us")
            self.assertEqual(call_args.kwargs["payload"]["message"], "Hello WhatsApp World!")

        asyncio.run(_test())

    @patch.object(WhatsAppBotService, "broadcast_message", new_callable=AsyncMock)
    def test_broadcast_alert_formatting(self, mock_broadcast):
        import asyncio
        mock_broadcast.return_value = 1

        alert = NewsAlert(
            id="alert_test_unit",
            article_id="art_unit_1",
            source_name="The Hindu",
            severity="critical",
            category="crises_disasters",
            topic="Cyclone Alert",
            summary="Severe cyclonic storm warning issued along coastal belts.",
            translated_text="Severe Cyclonic Storm Warning",
            ocr_raw_text="Severe Cyclonic Storm Warning",
            ocr_confidence=0.98,
            translation_confidence=0.98,
            needs_review=False,
            preserved_entities=["Chennai", "IMD"],
            page_number=1,
            page_snapshot_url="/api/snapshots/sample/1",
            created_at=datetime.now()
        )

        async def _test():
            sent = await self.service.broadcast_alert(alert)
            self.assertEqual(sent, 1)
            mock_broadcast.assert_called_once()
            msg = mock_broadcast.call_args[0][0]
            self.assertIn("*[CRITICAL ALERT]*", msg)
            self.assertIn("*Headline:* Severe Cyclonic Storm Warning", msg)
            self.assertIn("IMD", str(alert.preserved_entities))
            self.assertIn("http://localhost:8000", msg)

        asyncio.run(_test())

    @patch.object(WhatsAppBotService, "send_message", new_callable=AsyncMock)
    def test_process_text_commands(self, mock_send):
        import asyncio

        async def _test():
            body = {
                "typeWebhook": "incomingMessageReceived",
                "senderData": {
                    "chatId": "919445707197@c.us",
                    "senderName": "Admin"
                },
                "messageData": {
                    "typeMessage": "textMessage",
                    "textMessageData": {
                        "textMessage": "/start"
                    }
                }
            }
            await self.service._process_notification(body)
            mock_send.assert_called_once()
            self.assertIn("Welcome to the ePaper Harvester WhatsApp Bot", mock_send.call_args.kwargs["text"])

        asyncio.run(_test())

    @patch.object(WhatsAppBotService, "send_message", new_callable=AsyncMock)
    def test_send_alert_user_selected_chat(self, mock_send):
        import asyncio
        mock_send.return_value = True

        alert = NewsAlert(
            id="alert_sel_unit",
            article_id="art_sel_1",
            source_name="The Hindu",
            severity="high",
            category="business",
            topic="Company Acquisition",
            summary="Strategic acquisition deal concluded.",
            translated_text="Strategic Acquisition Finalized",
            ocr_raw_text="Strategic Acquisition Finalized",
            ocr_confidence=0.99,
            translation_confidence=0.99,
            needs_review=False,
            preserved_entities=["RBI"],
            page_number=2,
            created_at=datetime.now()
        )

        async def _test():
            sent = await self.service.send_alert(alert, chat_id="919445707197")
            self.assertEqual(sent, 1)
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            self.assertEqual(call_kwargs["chat_id"], "919445707197")
            self.assertIn("User Selected", call_kwargs["text"])
            self.assertIn("Strategic Acquisition Finalized", call_kwargs["text"])

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()

