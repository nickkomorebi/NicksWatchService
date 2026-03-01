import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_job_sync():
    """Bridge: run async job from APScheduler background thread."""
    from app.services.job_runner import run_job
    asyncio.run(run_job(triggered_by="scheduler"))


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_job_sync,
        trigger="cron",
        hour=settings.schedule_hour,
        minute=settings.schedule_minute,
        id="daily_watch_search",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — daily job at %02d:%02d",
        settings.schedule_hour,
        settings.schedule_minute,
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
