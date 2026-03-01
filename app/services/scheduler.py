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
        trigger="interval",
        hours=settings.schedule_interval_hours,
        id="watch_search",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — job runs every %d hours", settings.schedule_interval_hours)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
