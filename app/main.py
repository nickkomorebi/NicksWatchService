import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import create_tables

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NicksWatchService…")
    await create_tables()

    # Mark any runs left in "running" state as failed — they were interrupted by a restart
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from app.database import AsyncSessionLocal
    from app.models import Run
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Run).where(Run.status == "running"))
        orphaned = result.scalars().all()
        for run in orphaned:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_summary = "Interrupted by service restart"
            logger.warning("Marked orphaned run id=%d as failed", run.id)
        if orphaned:
            await db.commit()

    yield

    logger.info("Shutting down…")


app = FastAPI(title="NicksWatchService", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.routers import api, ui  # noqa: E402 — after app creation

app.include_router(ui.router)
app.include_router(api.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
