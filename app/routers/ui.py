from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Listing, Run, RunSourceError, Watch

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    # Last successful run (for "new listing" boundary)
    stmt = select(Run).where(Run.status == "succeeded").order_by(Run.id.desc()).limit(1)
    result = await db.execute(stmt)
    last_run = result.scalar_one_or_none()

    # All watches with active listings
    stmt = (
        select(Watch)
        .where(Watch.enabled == True)  # noqa: E712
        .options(selectinload(Watch.listings))
        .order_by(Watch.brand, Watch.model)
    )
    result = await db.execute(stmt)
    watches = result.scalars().all()

    # Filter to only active, non-removed listings per watch
    watch_listings = []
    for watch in watches:
        active = [
            l for l in watch.listings
            if l.is_active and l.removed_at is None
        ]
        active.sort(key=lambda l: l.first_seen_at, reverse=True)
        watch_listings.append((watch, active))

    # Current run status
    stmt = select(Run).order_by(Run.id.desc()).limit(1)
    result = await db.execute(stmt)
    latest_run = result.scalar_one_or_none()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "watch_listings": watch_listings,
            "last_run": last_run,
            "latest_run": latest_run,
            "run_token": settings.run_token,
        },
    )


@router.get("/partials/run-status", response_class=HTMLResponse)
async def run_status_partial(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(Run).order_by(Run.id.desc()).limit(1)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    return templates.TemplateResponse(
        "partials/run_status_banner.html",
        {"request": request, "run": run},
    )


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Run)
        .options(selectinload(Run.source_errors))
        .order_by(Run.id.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()

    return templates.TemplateResponse(
        "runs.html",
        {"request": request, "runs": runs, "run_token": settings.run_token},
    )
