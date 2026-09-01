import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from datetime import timezone
    ZoneInfo = lambda x: timezone.utc

from harvester.config import settings
from harvester.registry import SOURCES_REGISTRY, list_sources
from harvester.storage.retention import retention_manager

logger = logging.getLogger(__name__)


class CronSchedulerManager:
    """
    Manages automated early-morning harvest jobs using APScheduler.
    Runs on IST (Asia/Kolkata) timezone.
    """

    def __init__(self):
        try:
            self.tz = ZoneInfo(settings.timezone)
        except Exception:
            self.tz = None
            
        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self._is_running = False

    def start(self):
        """
        Initializes and starts the scheduler.
        """
        if self._is_running:
            return

        self._register_default_jobs()
        self.scheduler.start()
        self._is_running = True
        logger.info(f"Scheduler started with timezone {settings.timezone}")

    def stop(self):
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("Scheduler stopped.")

    def _register_default_jobs(self):
        """
        Registers individual newspaper schedules and the master morning sweep.
        """
        from harvester.orchestrator import orchestrator

        # 1. Register individual source scheduled jobs
        for source in SOURCES_REGISTRY.values():
            if not source.active:
                continue

            time_parts = source.schedule_time.split(":")
            hour = int(time_parts[0]) if len(time_parts) > 0 else 5
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0

            job_id = f"sched_{source.id}"

            async def _make_source_task(src_id=source.id):
                today_str = datetime.now().strftime("%Y-%m-%d")
                logger.info(f"[Scheduler] Triggering scheduled harvest for {src_id} ({today_str})")
                await orchestrator.trigger_harvest(src_id, target_date=today_str)

            trigger = CronTrigger(hour=hour, minute=minute, timezone=self.tz)
            self.scheduler.add_job(
                _make_source_task,
                trigger=trigger,
                id=job_id,
                name=f"Daily harvest {source.name}",
                replace_existing=True
            )

        # 2. Master morning batch sweep at 05:30 AM IST
        async def _master_sweep():
            today_str = datetime.now().strftime("%Y-%m-%d")
            logger.info(f"[Scheduler] Running master morning sweep for all active papers ({today_str})")
            await orchestrator.trigger_batch_harvest(target_date=today_str)

        self.scheduler.add_job(
            _master_sweep,
            trigger=CronTrigger(hour=5, minute=30, timezone=self.tz),
            id="master_morning_sweep",
            name="Master Morning Harvest Sweep (All Papers)",
            replace_existing=True
        )

        # 3. Nightly retention cleanup at 23:30
        def _retention_purge():
            purged = retention_manager.purge_expired()
            logger.info(f"[Scheduler] Nightly retention cleanup complete. Purged {purged} files.")

        self.scheduler.add_job(
            _retention_purge,
            trigger=CronTrigger(hour=23, minute=30, timezone=self.tz),
            id="nightly_retention_purge",
            name="Nightly Retention Purge",
            replace_existing=True
        )

        # 4. Periodic Email Inbox Monitor (every 15 minutes)
        async def _inbox_monitor_check():
            try:
                from harvester.automation.email_monitor import email_inbox_monitor
                res = await email_inbox_monitor.check_inbox(limit=15)
                logger.info(f"[Scheduler] Inbox check completed: {res.get('ingested_count', 0)} clippings ingested.")
            except Exception as e:
                logger.error(f"[Scheduler] Inbox check failed: {e}")

        from apscheduler.triggers.interval import IntervalTrigger
        self.scheduler.add_job(
            _inbox_monitor_check,
            trigger=IntervalTrigger(minutes=settings.inbox_check_interval_minutes),
            id="email_inbox_monitor",
            name="Email Inbox Clipping Monitor (bureau@chennai.com / clipping)",
            replace_existing=True
        )

        # 5. Master Morning Multi-Language News Digest Auto-Dispatch at 06:00 AM IST
        async def _morning_email_digest():
            try:
                from harvester.notifications.email_service import news_email_service
                logger.info("[Scheduler] Dispatching daily morning multi-language email news digest...")
                res = await news_email_service.send_news_digest(
                    category="all",
                    recipient_email=settings.default_recipient_email,
                    max_articles=25
                )
                logger.info(f"[Scheduler] Daily morning email digest successfully delivered: {res.get('message')}")
            except Exception as e:
                logger.error(f"[Scheduler] Daily morning email digest dispatch failed: {e}")

        self.scheduler.add_job(
            _morning_email_digest,
            trigger=CronTrigger(hour=6, minute=0, timezone=self.tz),
            id="daily_morning_email_digest",
            name="Daily Morning Multi-Language Email Digest (All India Headlines)",
            replace_existing=True
        )



    def list_jobs(self) -> List[Dict[str, Any]]:
        """
        Returns all scheduled jobs with their next run times for the dashboard.
        """
        jobs_info = []
        for j in self.scheduler.get_jobs():
            next_run = j.next_run_time.isoformat() if j.next_run_time else None
            jobs_info.append({
                "id": j.id,
                "name": j.name,
                "next_run_time": next_run,
                "trigger": str(j.trigger),
            })
        return jobs_info

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._is_running,
            "timezone": settings.timezone,
            "job_count": len(self.scheduler.get_jobs()),
        }


cron_scheduler = CronSchedulerManager()
