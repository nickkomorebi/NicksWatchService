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

    from app.services.scheduler import start_scheduler, shutdown_scheduler
    start_scheduler()

    yield

    logger.info("Shutting down…")
    shutdown_scheduler()


app = FastAPI(title="NicksWatchService", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.routers import api, ui  # noqa: E402 — after app creation

app.include_router(ui.router)
app.include_router(api.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
