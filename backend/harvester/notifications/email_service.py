import asyncio
import email.encoders
import html
import logging
import smtplib
from datetime import datetime
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from harvester.config import settings
from harvester.models import NewsArticle
from harvester.news.service import news_service, CATEGORY_CONFIG
from harvester.registry import list_sources

logger = logging.getLogger(__name__)

# Representative multi-lingual newspapers to aggregate from across India
MULTI_LANGUAGE_SOURCES = [
    # English
    "the_hindu",
    "toi",
    "indian_express",
    # Hindi
    "dainik_bhaskar",
    "amar_ujala",
    "dainik_jagran",
    # Telugu
    "eenadu",
    "sakshi",
    # Tamil
    "daily_thanthi",
    "dinamalar",
    # Marathi
    "lokmat",
    "loksatta",
    # Bengali
    "anandabazar_patrika",
    # Gujarati
    "gujarat_samachar",
    # Kannada
    "prajavani",
    # Malayalam
    "malayala_manorama",
]


class NewsEmailService:
    """
    Email service for sending multi-language categorized news digests
    translated to English via Gmail SMTP.
    """

    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.default_recipient = settings.default_recipient_email

    def test_smtp_connection(self) -> Dict[str, Any]:
        """
        Tests Gmail SMTP SSL connection and authentication with latency tracking.
        """
        try:
            start_time = datetime.now()
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.login(self.smtp_user, self.smtp_password)
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return {
                "success": True,
                "status": "connected",
                "host": self.smtp_host,
                "port": self.smtp_port,
                "user": self.smtp_user,
                "default_recipient": self.default_recipient,
                "latency_ms": latency_ms,
                "error": None,
                "checked_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"SMTP diagnostic test failed: {e}")
            return {
                "success": False,
                "status": "failed",
                "host": self.smtp_host,
                "port": self.smtp_port,
                "user": self.smtp_user,
                "default_recipient": self.default_recipient,
                "latency_ms": None,
                "error": str(e),
                "checked_at": datetime.now().isoformat(),
            }

    async def aggregate_multi_language_news(
        self,
        category: str = "all",
        custom_keywords: Optional[str] = None,
        max_articles: int = 25
    ) -> List[NewsArticle]:
        """
        Aggregates news from top national and regional newspapers across India,
        guaranteeing that all regional content is translated to fluent English.
        """
        # If custom keywords are provided, use the search engine across publications
        if custom_keywords and custom_keywords.strip():
            logger.info(f"Aggregating keyword news for email: '{custom_keywords}'")
            return await news_service.search_news(keywords=custom_keywords.strip(), limit=max_articles)

        # Otherwise aggregate across multi-language newspapers for the selected category
        tasks = []
        for src_id in MULTI_LANGUAGE_SOURCES:
            tasks.append(news_service.get_news_for_source(source_id=src_id, category=category, limit=2))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles: List[NewsArticle] = []
        seen_titles = set()

        for res in results:
            if isinstance(res, list):
                for art in res:
                    # Deduplicate by title
                    norm_title = art.title.strip().lower()
                    if norm_title not in seen_titles:
                        seen_titles.add(norm_title)
                        all_articles.append(art)

        # Return up to max_articles
        return all_articles[:max_articles]

    def build_email_content(
        self,
        category: str,
        articles: List[NewsArticle],
        recipient_email: str
    ) -> Tuple[str, str]:
        """
        Generates both plain text and rich HTML email content for the news digest.
        """
        cat_info = CATEGORY_CONFIG.get(category, CATEGORY_CONFIG["all"])
        category_name = cat_info["name"]
        category_icon = cat_info["icon"]
        category_color = cat_info["color"]
        current_time = datetime.now().strftime("%A, %d %B %Y | %I:%M %p IST")

        # --- Plain Text Version ---
        text_lines = [
            f"Automated ePaper Harvester - Multi-Language News Digest",
            f"Category: {category_name} ({category_icon})",
            f"Date: {current_time}",
            f"All regional language news auto-translated to English",
            "=" * 60,
            "",
        ]

        for idx, art in enumerate(articles, 1):
            text_lines.append(f"{idx}. {art.title}")
            text_lines.append(f"   Source: {art.source_name} | Category: {art.category.title()}")
            if art.is_translated and art.original_language:
                text_lines.append(f"   [Translated to English from {art.original_language}]")
                if art.original_title:
                    text_lines.append(f"   Original: {art.original_title}")
            if art.snippet:
                text_lines.append(f"   Summary: {art.snippet}")
            text_lines.append(f"   Link: {art.link}")
            text_lines.append("")

        text_content = "\n".join(text_lines)

        # --- Rich HTML Version ---
        cards_html_list = []
        for idx, art in enumerate(articles, 1):
            orig_html = ""
            if art.is_translated and art.original_title:
                orig_html = f"""
                <div style="font-size:12px;color:#94a3b8;font-style:italic;margin-bottom:8px;padding:4px 8px;background:#f8fafc;border-left:3px solid #38bdf8;border-radius:2px;">
                    <strong>Original ({html.escape(art.original_language or 'Regional')}):</strong> {html.escape(art.original_title)}
                </div>
                """

            trans_badge = ""
            if art.is_translated:
                trans_badge = f"""
                <span style="font-size:11px;font-weight:600;color:#0284c7;background:#e0f2fe;padding:2px 8px;border-radius:12px;display:inline-block;margin-right:6px;">
                    🌐 Auto-Translated from {html.escape(art.original_language or 'Regional')}
                </span>
                """

            snippet_html = f"<p style='color:#475569;font-size:13px;line-height:1.5;margin:6px 0 10px 0;'>{html.escape(art.snippet)}</p>" if art.snippet else ""

            card = f"""
            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.05);">
                <div style="margin-bottom:8px;">
                    <span style="font-size:11px;font-weight:700;color:#ffffff;background:{category_color};padding:2px 8px;border-radius:12px;display:inline-block;margin-right:6px;">
                        {category_icon} {art.category.title()}
                    </span>
                    <span style="font-size:11px;font-weight:600;color:#334155;background:#f1f5f9;padding:2px 8px;border-radius:12px;display:inline-block;margin-right:6px;">
                        📰 {html.escape(art.source_name)}
                    </span>
                    {trans_badge}
                </div>
                <h3 style="margin:6px 0 8px 0;font-size:16px;line-height:1.4;">
                    <a href="{art.link}" target="_blank" style="color:#0f172a;text-decoration:none;font-weight:700;">
                        {html.escape(art.title)}
                    </a>
                </h3>
                {orig_html}
                {snippet_html}
                <div style="text-align:right;">
                    <a href="{art.link}" target="_blank" style="font-size:12px;font-weight:600;color:#0284c7;text-decoration:none;">
                        Read Full Story ↗
                    </a>
                </div>
            </div>
            """
            cards_html_list.append(card)

        cards_html = "\n".join(cards_html_list)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{category_name} News Digest</title>
        </head>
        <body style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;background-color:#f8fafc;margin:0;padding:20px;color:#1e293b;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);border:1px solid #e2e8f0;">
                <!-- Header Banner -->
                <tr>
                    <td style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%);padding:28px 24px;text-align:center;color:#ffffff;">
                        <div style="font-size:32px;margin-bottom:8px;">{category_icon}</div>
                        <h1 style="margin:0 0 6px 0;font-size:22px;font-weight:800;letter-spacing:-0.5px;color:#ffffff;">
                            {category_name} News Digest
                        </h1>
                        <p style="margin:0 0 12px 0;font-size:13px;color:#94a3b8;">
                            Multi-Language National & Regional Headlines • Auto-Translated to English
                        </p>
                        <div style="display:inline-block;background:rgba(255,255,255,0.1);padding:4px 12px;border-radius:20px;font-size:12px;color:#cbd5e1;">
                            📅 {current_time}
                        </div>
                    </td>
                </tr>

                <!-- Metrics Bar -->
                <tr>
                    <td style="background:#f1f5f9;padding:12px 24px;border-bottom:1px solid #e2e8f0;">
                        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="font-size:12px;color:#475569;font-weight:600;">
                            <tr>
                                <td>📊 <strong>{len(articles)}</strong> Articles Included</td>
                                <td style="text-align:center;">🌐 <strong>10+</strong> Indian Languages</td>
                                <td style="text-align:right;">⚡ <strong>100%</strong> in English</td>
                            </tr>
                        </table>
                    </td>
                </tr>

                <!-- Articles Body -->
                <tr>
                    <td style="padding:24px;">
                        {cards_html}
                    </td>
                </tr>

                <!-- Footer -->
                <tr>
                    <td style="background:#f8fafc;padding:20px 24px;text-align:center;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
                        <p style="margin:0 0 6px 0;">
                            Sent via <strong>Automated ePaper Harvester</strong> • All Regional Content Auto-Translated
                        </p>
                        <p style="margin:0;font-size:11px;color:#94a3b8;">
                            Delivered to: <strong>{recipient_email}</strong> from <strong>{self.smtp_user}</strong>
                        </p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return text_content, html_content

    async def preview_digest(
        self,
        category: str = "all",
        custom_keywords: Optional[str] = None,
        max_articles: int = 25
    ) -> Dict[str, Any]:
        """
        Generates and returns news digest preview without sending email.
        """
        cat_key = category.lower()
        if cat_key not in CATEGORY_CONFIG:
            cat_key = "all"

        cat_info = CATEGORY_CONFIG[cat_key]
        articles = await self.aggregate_multi_language_news(
            category=cat_key,
            custom_keywords=custom_keywords,
            max_articles=max_articles
        )

        text_content, html_content = self.build_email_content(
            category=cat_key,
            articles=articles,
            recipient_email=self.default_recipient
        )

        return {
            "category": cat_key,
            "category_name": cat_info["name"],
            "category_icon": cat_info["icon"],
            "articles_count": len(articles),
            "articles": [a.model_dump(mode="json") for a in articles],
            "html_preview": html_content,
            "text_preview": text_content,
            "sender_email": self.smtp_user,
            "default_recipient": self.default_recipient,
        }

    async def send_news_digest(
        self,
        category: str = "all",
        recipient_email: Optional[str] = None,
        custom_keywords: Optional[str] = None,
        max_articles: int = 25
    ) -> Dict[str, Any]:
        """
        Gathers news across languages, formats email digest, and delivers it via Gmail SSL SMTP.
        Supports single email or comma/semicolon-separated multiple recipients.
        """
        raw_to = recipient_email.strip() if recipient_email else self.default_recipient
        if not raw_to:
            raise ValueError("No recipient email address provided.")

        to_addrs = [e.strip() for e in raw_to.replace(";", ",").split(",") if e.strip()]
        valid_recipients = [e for e in to_addrs if "@" in e]

        if not valid_recipients:
            raise ValueError(f"Invalid recipient email address: '{raw_to}'")

        cat_key = category.lower()
        if cat_key not in CATEGORY_CONFIG:
            cat_key = "all"

        cat_info = CATEGORY_CONFIG[cat_key]
        category_name = cat_info["name"]

        # 1. Aggregate articles
        logger.info(f"Aggregating {cat_key} articles for email to {', '.join(valid_recipients)}...")
        articles = await self.aggregate_multi_language_news(
            category=cat_key,
            custom_keywords=custom_keywords,
            max_articles=max_articles
        )

        if not articles:
            raise ValueError(f"No recent news articles found for category '{category_name}'")

        # 2. Build email content
        text_content, html_content = self.build_email_content(
            category=cat_key,
            articles=articles,
            recipient_email=", ".join(valid_recipients)
        )

        # 3. Create MIME message with RFC 2047 utf-8 header encoding
        subject_prefix = f"[{cat_info['icon']} {category_name}]"
        if custom_keywords:
            subject_raw = f"{subject_prefix} News Digest: '{custom_keywords}' ({len(articles)} Stories) - Translated to English"
        else:
            subject_raw = f"{subject_prefix} Multi-Language News Digest ({len(articles)} Stories) - All in English"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject_raw, "utf-8").encode()
        msg["From"] = formataddr(("ePaper Harvester", self.smtp_user))
        msg["To"] = ", ".join(valid_recipients)

        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # 4. Connect to SMTP and send
        loop = asyncio.get_event_loop()

        def _send_smtp():
            logger.info(f"Connecting to Gmail SMTP {self.smtp_host}:{self.smtp_port} with SSL...")
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, valid_recipients, msg.as_string())
            logger.info(f"Email digest successfully dispatched to {', '.join(valid_recipients)}!")

        await loop.run_in_executor(None, _send_smtp)

        return {
            "success": True,
            "message": f"Successfully sent {len(articles)} {category_name} stories to {', '.join(valid_recipients)}",
            "recipient_email": ", ".join(valid_recipients),
            "recipients_list": valid_recipients,
            "sender_email": self.smtp_user,
            "category": cat_key,
            "category_name": category_name,
            "articles_count": len(articles),
            "subject": subject_raw,
            "timestamp": datetime.now().isoformat(),
        }


    async def send_pdf_attachment(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        pdf_path: Path,
    ) -> Dict[str, Any]:
        """
        Sends an email with a PDF file attached via Gmail SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            body_html: HTML body of the email
            pdf_path: Absolute Path to the PDF file to attach

        Returns:
            Result dict with success status
        """
        if not pdf_path.exists():
            return {"success": False, "error": f"PDF file not found: {pdf_path}"}

        msg = MIMEMultipart("mixed")
        msg["From"] = formataddr(("VEE2 ePaper Intelligence", self.smtp_user))
        msg["To"] = to_email
        msg["Subject"] = Header(subject, "utf-8").encode()

        # HTML body
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        # PDF attachment
        try:
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()
        except Exception as e:
            return {"success": False, "error": f"Could not read PDF: {e}"}

        attachment = MIMEBase("application", "pdf")
        attachment.set_payload(pdf_data)
        email.encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=pdf_path.name,
        )
        msg.attach(attachment)

        loop = asyncio.get_event_loop()

        def _send():
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, [to_email], msg.as_string())

        try:
            await loop.run_in_executor(None, _send)
            logger.info(f"PDF report sent to {to_email}: {pdf_path.name}")
            return {
                "success": True,
                "to_email": to_email,
                "subject": subject,
                "filename": pdf_path.name,
                "file_size_kb": round(pdf_path.stat().st_size / 1024, 1),
                "sent_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to send PDF to {to_email}: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
news_email_service = NewsEmailService()
