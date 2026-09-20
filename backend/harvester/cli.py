import sys
import asyncio
import click
import uvicorn
from datetime import datetime
from pathlib import Path

from harvester.config import settings
from harvester.models import NewsAlert
from harvester.registry import SOURCES_REGISTRY, list_sources, get_source
from harvester.orchestrator import orchestrator
from harvester.storage.retention import retention_manager
from harvester.auth.session_manager import session_manager
from harvester.scheduler.cron_manager import cron_scheduler


def safe_echo(text: str, err: bool = False):
    """Safely prints text to the terminal handling Windows charmap/cp1252 encodings."""
    try:
        click.echo(text, err=err)
    except (UnicodeEncodeError, Exception):
        enc = sys.stdout.encoding or "utf-8"
        safe_text = text.encode(enc, errors="replace").decode(enc)
        click.echo(safe_text, err=err)


@click.group()
def cli():
    """Automated ePaper Harvester CLI - Scheduled downloads from 50+ sources."""
    pass



@cli.command("list")
@click.option("--language", "-l", default=None, help="Filter by language (English, Hindi, Telugu, etc.)")
@click.option("--category", "-c", default=None, help="Filter by category (National, Regional, Business)")
def list_cmd(language, category):
    """List configured newspaper sources."""
    sources = list_sources(language=language, category=category)
    click.echo(f"\nFound {len(sources)} configured sources:\n")
    click.echo(f"{'ID':<18} | {'NAME':<28} | {'LANGUAGE':<10} | {'ENGINE':<18} | {'DEFAULT ED':<12} | {'SCHEDULE'}")
    click.echo("-" * 105)
    for s in sources:
        click.echo(
            f"{s.id:<18} | {s.name:<28} | {s.language.value:<10} | {s.engine_type.value:<18} | {s.default_edition:<12} | {s.schedule_time} IST"
        )
    click.echo("")


@cli.command("run")
@click.option("--source", "-s", required=True, help="Source identifier (e.g. toi, the_hindu, dainik_bhaskar, eenadu)")
@click.option("--edition", "-e", default=None, help="Regional edition code (e.g. delhi, mumbai, hyderabad)")
@click.option("--date", "-d", default=None, help="Target date YYYY-MM-DD (defaults to today)")
def run_cmd(source, edition, date):
    """Harvest an ePaper edition and compile to PDF."""
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    src = get_source(source)
    if not src:
        click.echo(f"Error: Source '{source}' is not configured.", err=True)
        sys.exit(1)

    ed = edition or src.default_edition
    click.echo(f"Starting harvest: {src.name} [{ed}] for {target_date}...")

    async def _do_run():
        job = orchestrator.create_job(source, target_date=target_date, edition=ed)
        res = await orchestrator.execute_job(job.job_id)
        if res.success:
            click.echo(f"\n[SUCCESS] PDF saved to: {res.pdf_path}")
            click.echo(f"Pages: {res.page_count} | Size: {res.file_size_bytes / (1024*1024):.2f} MB | Time: {res.duration_seconds}s")
        else:
            click.echo(f"\n[FAILED] Error: {res.error}", err=True)
            sys.exit(1)

    asyncio.run(_do_run())


@cli.command("run-all")
@click.option("--language", "-l", default=None, help="Filter by language")
@click.option("--date", "-d", default=None, help="Target date YYYY-MM-DD")
def run_all_cmd(language, date):
    """Run batch harvest for all active configured newspapers."""
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    sources = list_sources(language=language, active_only=True)
    click.echo(f"Triggering batch harvest for {len(sources)} sources (Date: {target_date})...")

    async def _do_batch():
        jobs = await orchestrator.trigger_batch_harvest(language=language, target_date=target_date)
        click.echo(f"Queued {len(jobs)} background harvest jobs.")

    asyncio.run(_do_batch())


@cli.command("archive")
@click.option("--source", "-s", default=None, help="Filter by source ID")
@click.option("--limit", "-n", default=20, help="Max results")
def archive_cmd(source, limit):
    """List downloaded PDF archives in local storage."""
    archives = retention_manager.list_archives(source_id=source, limit=limit)
    if not archives:
        click.echo("No archives found.")
        return
    click.echo(f"\nDownloaded PDF Archives ({len(archives)} items):\n")
    click.echo(f"{'SOURCE':<24} | {'EDITION':<12} | {'DATE':<12} | {'PAGES':<6} | {'SIZE':<8} | {'PATH'}")
    click.echo("-" * 105)
    for a in archives:
        click.echo(f"{a.source_name:<24} | {a.edition:<12} | {a.target_date:<12} | {a.page_count:<6} | {a.file_size_mb} MB | {a.filepath}")
    click.echo("")


@cli.command("purge")
@click.option("--days", "-d", default=None, type=int, help="Retention days threshold")
def purge_cmd(days):
    """Purge archives older than the retention threshold."""
    retention_days = days if days is not None else settings.retention_days
    purged = retention_manager.purge_expired(retention_days)
    click.echo(f"Purged {purged} expired archive files older than {retention_days} days.")


@cli.command("import-cookies")
@click.option("--source", "-s", required=True, help="Source ID (e.g. toi, the_hindu)")
@click.option("--file", "-f", required=True, type=click.Path(exists=True), help="Cookie file (JSON or Netscape format)")
def import_cookies_cmd(source, file):
    """Import session cookies for authenticated sources."""
    src = get_source(source)
    if not src:
        click.echo(f"Error: Source '{source}' not recognized.", err=True)
        sys.exit(1)
    with open(file, "r", encoding="utf-8") as f:
        content = f.read()
    count = session_manager.import_cookies_raw(source, content)
    click.echo(f"Successfully imported and saved {count} cookies for {src.name}!")


@cli.command("send-digest")
@click.option("--category", "-c", default="all", help="News category (all, sports, business, economic, political, crises_disasters)")
@click.option("--to", "-t", default=None, help="Recipient email address (defaults to configured recipient)")
@click.option("--keywords", "-k", default=None, help="Custom keywords/topic filter")
@click.option("--max-articles", "-m", default=25, type=int, help="Maximum articles to include")
def send_digest_cmd(category, to, keywords, max_articles):
    """Send multi-language categorized news digest translated to English via Gmail SMTP."""
    from harvester.notifications.email_service import news_email_service
    recipient = to or settings.default_recipient_email
    safe_echo(f"Compiling '{category}' news digest for '{recipient}'...")

    async def _do_send():
        try:
            res = await news_email_service.send_news_digest(
                category=category,
                recipient_email=recipient,
                custom_keywords=keywords,
                max_articles=max_articles
            )
            safe_echo(f"\n[SUCCESS] Email digest dispatched!")
            safe_echo(f"Recipient(s): {res['recipient_email']}")
            safe_echo(f"Category: {res['category_name']}")
            safe_echo(f"Articles Included: {res['articles_count']}")
            safe_echo(f"Subject: {res['subject']}")
        except Exception as e:
            safe_echo(f"\n[FAILED] Error sending digest: {e}", err=True)
            sys.exit(1)

    asyncio.run(_do_send())


@cli.command("check-inbox")
@click.option("--limit", "-n", default=15, type=int, help="Number of recent emails to inspect")
def check_inbox_cmd(limit):
    """Scan IMAP inbox for newspaper clippings matching sender or subject rules."""
    from harvester.automation.email_monitor import email_inbox_monitor
    safe_echo(f"Checking IMAP inbox ({settings.imap_user}) for clippings...")

    async def _do_check():
        res = await email_inbox_monitor.check_inbox(limit=limit)
        if res.get("success"):
            safe_echo(f"\n[SUCCESS] Inbox check complete!")
            safe_echo(f"Checked: {res['checked_count']} emails | Matched Rules: {res['matched_count']} | Ingested: {res['ingested_count']} clippings")
            for clip in res.get("clippings", []):
                safe_echo(f"  - [{clip['id']}] From: {clip['sender']} | File: {clip['attachment_filename']} | Stories: {clip['articles_count']}")
        else:
            safe_echo(f"\n[FAILED] Inbox check error: {res.get('error')}", err=True)
            sys.exit(1)

    asyncio.run(_do_check())


@cli.command("simulate-inbox")
@click.option("--sender", "-s", default="cuttyknowledge2006@gmail.com", help="Simulated sender email")
@click.option("--subject", "-sub", default="Regional Newspaper Clipping - Special Edition", help="Simulated email subject")
@click.option("--file", "-f", default=None, type=click.Path(exists=True), help="Path to clipping PDF or image")
def simulate_inbox_cmd(sender, subject, file):
    """Simulate an incoming email clipping with OCR, translation, and pipeline push."""
    from harvester.automation.email_monitor import email_inbox_monitor
    file_path = Path(file) if file else None
    safe_echo(f"Simulating incoming clipping from '{sender}' with subject '{subject}'...")

    async def _do_sim():
        try:
            record = await email_inbox_monitor.simulate_incoming_clipping(
                sender=sender,
                subject=subject,
                file_path=file_path
            )
            safe_echo(f"\n[SUCCESS] Clipping ingested and processed!")
            safe_echo(f"Clipping ID: {record['id']}")
            safe_echo(f"Rule Matched: {record['rule_matched']}")
            safe_echo(f"Stories Extracted: {record['articles_count']}")
            safe_echo(f"Auto-Translated: {record['translated_count']}")
            for idx, art in enumerate(record.get("articles", [])[:5], 1):
                safe_echo(f"  {idx}. [{art.get('category', 'all').upper()}] {art.get('title')}")
        except Exception as e:
            safe_echo(f"\n[FAILED] Simulation failed: {e}", err=True)
            sys.exit(1)

    asyncio.run(_do_sim())


@cli.command("test-email")
def test_email_cmd():
    """Run diagnostics on Gmail SMTP (outbound) and Gmail IMAP (inbound) connections."""
    from harvester.notifications.email_service import news_email_service
    from harvester.automation.email_monitor import email_inbox_monitor

    safe_echo("\n--- Running Email Workflow Diagnostics ---\n")
    
    # 1. SMTP Test
    safe_echo(f"1. Testing Gmail SMTP SSL ({settings.smtp_host}:{settings.smtp_port})...")
    smtp_res = news_email_service.test_smtp_connection()
    if smtp_res["success"]:
        safe_echo(f"   [OK] SMTP Connected! Authenticated as {smtp_res['user']} (Latency: {smtp_res['latency_ms']}ms)")
    else:
        safe_echo(f"   [FAIL] SMTP Error: {smtp_res['error']}", err=True)

    # 2. IMAP Test
    safe_echo(f"\n2. Testing Gmail IMAP SSL ({settings.imap_host}:{settings.imap_port})...")
    imap_res = email_inbox_monitor.test_imap_connection()
    if imap_res["success"]:
        safe_echo(f"   [OK] IMAP Connected! Total messages in INBOX: {imap_res['total_messages']} (Latency: {imap_res['latency_ms']}ms)")
    else:
        safe_echo(f"   [FAIL] IMAP Error: {imap_res['error']}", err=True)

    safe_echo(f"\nMonitored Senders: {', '.join(settings.email_monitor_sender_rules)}")
    safe_echo(f"Subject Keywords: {', '.join(settings.email_monitor_subject_keywords)}")
    safe_echo(f"Default Recipient: {settings.default_recipient_email}\n")



@cli.command("test-telegram")
@click.option("--chat-id", "-c", default=None, help="Target chat ID (defaults to default_chat_id)")
def test_telegram_cmd(chat_id):
    """Test Telegram Bot API connection and dispatch a test alert."""
    from harvester.notifications.telegram_service import telegram_service
    target_chat = chat_id or settings.telegram_default_chat_id
    safe_echo(f"Testing Telegram Bot API for token: {settings.telegram_bot_token[:12]}...")

    async def _do_test():
        me = await telegram_service.call_api("getMe")
        if me.get("ok"):
            bot = me.get("result", {})
            safe_echo(f"  [OK] Bot Connected: @{bot.get('username')} ({bot.get('first_name')}) [ID: {bot.get('id')}]")
        else:
            safe_echo(f"  [FAIL] Could not connect to Telegram: {me.get('error')}", err=True)
            return

        safe_echo(f"Sending test alert to chat {target_chat}...")
        test_alert = NewsAlert(
            id=f"alert_test_{int(datetime.now().timestamp())}",
            article_id="art_test_cli",
            source_name="Automated Harvester CLI",
            severity="high",
            category="sports",
            topic="Telegram Alert Dispatch Verification",
            summary="CLI diagnostic test confirming high-priority alert delivery and PDF pipeline readiness.",
            translated_text="ePaper Harvester: Telegram Alert Pipeline Operational",
            ocr_raw_text="ePaper Harvester: Telegram Alert Pipeline Operational",
            ocr_confidence=0.99,
            translation_confidence=0.99,
            needs_review=False,
            preserved_entities=["Antigravity", "ePaper Harvester"],
            page_number=1,
            page_snapshot_url="/api/snapshots/sample/1",
            created_at=datetime.now()
        )
        sent = await telegram_service.broadcast_alert(test_alert)
        if sent > 0:
            safe_echo(f"  [OK] Alert sent successfully to {sent} chat(s)!")
        else:
            safe_echo("  [FAIL] Failed to send alert.", err=True)

    asyncio.run(_do_test())


@cli.command("telegram-bot")
def telegram_bot_cmd():
    """Run the interactive Telegram Bot listener standalone."""
    from harvester.notifications.telegram_service import telegram_service
    safe_echo(f"Starting standalone Telegram Bot listener for @Mhjkbktbot...")
    safe_echo("Press CTRL+C to stop.")

    async def _do_bot():
        telegram_service.start_polling()
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            telegram_service.stop_polling()
            safe_echo("\nTelegram Bot listener stopped.")

    try:
        asyncio.run(_do_bot())
    except KeyboardInterrupt:
        pass


@cli.command("test-whatsapp")
@click.option("--chat-id", "-c", default=None, help="Target WhatsApp chat ID or phone (defaults to whatsapp_default_chat_id)")
def test_whatsapp_cmd(chat_id):
    """Test WhatsApp Green API connection and dispatch a test alert."""
    from harvester.notifications.whatsapp_service import whatsapp_service
    target_chat = whatsapp_service.normalize_chat_id(chat_id or settings.whatsapp_default_chat_id)
    safe_echo(f"Testing WhatsApp Green API for Instance: {settings.whatsapp_id_instance}...")

    async def _do_test():
        state_res = await whatsapp_service.call_api("getStateInstance", method="GET")
        if state_res.get("ok"):
            state = state_res.get("stateInstance")
            safe_echo(f"  [OK] Instance State: {state}")
        else:
            safe_echo(f"  [FAIL] Could not connect to Green API: {state_res.get('error')}", err=True)
            return

        settings_res = await whatsapp_service.call_api("getSettings", method="GET")
        wid = settings_res.get("wid", "unknown")
        safe_echo(f"  [OK] Authorized WhatsApp Account: {wid}")

        safe_echo(f"Sending test alert to chat {target_chat}...")
        test_alert = NewsAlert(
            id=f"alert_test_wa_cli_{int(datetime.now().timestamp())}",
            article_id="art_test_wa_cli",
            source_name="Automated Harvester CLI",
            severity="high",
            category="sports",
            topic="WhatsApp Alert Dispatch Verification",
            summary="CLI diagnostic test confirming WhatsApp Green API alert delivery and PDF pipeline readiness.",
            translated_text="ePaper Harvester: WhatsApp Alert Pipeline Operational",
            ocr_raw_text="ePaper Harvester: WhatsApp Alert Pipeline Operational",
            ocr_confidence=0.99,
            translation_confidence=0.99,
            needs_review=False,
            preserved_entities=["Antigravity", "ePaper Harvester", "WhatsApp Green API"],
            page_number=1,
            page_snapshot_url="/api/snapshots/sample/1",
            created_at=datetime.now()
        )
        if chat_id:
            whatsapp_service.register_chat(target_chat)
        sent = await whatsapp_service.broadcast_alert(test_alert)
        if sent > 0:
            safe_echo(f"  [OK] WhatsApp Alert sent successfully to {sent} chat(s)!")
        else:
            safe_echo("  [FAIL] Failed to send WhatsApp alert.", err=True)

    asyncio.run(_do_test())


@cli.command("whatsapp-bot")
def whatsapp_bot_cmd():
    """Run the interactive WhatsApp Bot listener standalone."""
    from harvester.notifications.whatsapp_service import whatsapp_service
    safe_echo(f"Starting standalone WhatsApp Bot listener for Instance {settings.whatsapp_id_instance}...")
    safe_echo("Press CTRL+C to stop.")

    async def _do_bot():
        whatsapp_service.start_polling()
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            whatsapp_service.stop_polling()
            safe_echo("\nWhatsApp Bot listener stopped.")

    try:
        asyncio.run(_do_bot())
    except KeyboardInterrupt:
        pass


@cli.command("serve")
@click.option("--host", "-h", default="0.0.0.0", help="Host address")
@click.option("--port", "-p", default=None, help="Port number (defaults to PORT env var or 10000 on Render, 8000 locally)")
@click.option("--reload/--no-reload", default=False, help="Enable code auto-reload (development only)")
def serve_cmd(host, port, reload):
    """Launch the Web Control Center and API server."""
    env_port = os.environ.get("PORT")
    target_port = 10000 if os.environ.get("RENDER") else 8000
    if env_port and env_port.isdigit():
        target_port = int(env_port)

    if port is not None:
        port_str = str(port).strip()
        if port_str.isdigit():
            target_port = int(port_str)
        elif port_str != "$PORT":
            try:
                target_port = int(port_str)
            except ValueError:
                pass

    click.echo(f"Starting ePaper Harvester Web Dashboard on {host}:{target_port}")
    uvicorn.run("harvester.api.app:app", host=host, port=target_port, reload=reload)


if __name__ == "__main__":
    cli()

