import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import run_token_required
from app.models import Listing, Run
from app.schemas import RunRead, TriggerResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/runs/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TriggerResponse,
    dependencies=[Depends(run_token_required)],
)
async def trigger_run(db: AsyncSession = Depends(get_db)):
    # Check if already running
    stmt = select(Run).where(Run.status == "running")
    result = await db.execute(stmt)
    running = result.scalar_one_or_none()
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {running.id} is already in progress",
        )

    # Check if a successful run completed within the last 24 hours
    stmt = select(Run).where(Run.status == "succeeded").order_by(Run.id.desc()).limit(1)
    result = await db.execute(stmt)
    recent = result.scalar_one_or_none()
    if recent and recent.finished_at:
        finished = recent.finished_at.replace(tzinfo=timezone.utc) if recent.finished_at.tzinfo is None else recent.finished_at
        age = datetime.now(timezone.utc) - finished
        if age < timedelta(hours=24):
            next_run = finished + timedelta(hours=24)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"A run completed at {finished.strftime('%Y-%m-%d %H:%M')} UTC. Next manual run allowed after {next_run.strftime('%Y-%m-%d %H:%M')} UTC.",
            )

    # Create a placeholder run row so the UI sees it immediately
    run = Run(status="running", triggered_by="manual")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    run_id = run.id

    async def _run_in_bg():
        from app.services.job_runner import run_job as _rj
        try:
            # Pass the already-created run_id so job_runner won't create another row
            await _rj(triggered_by="manual", existing_run_id=run_id)
        except Exception as exc:
            logger.exception("Background run failed: %s", exc)

    asyncio.create_task(_run_in_bg())
    return TriggerResponse(run_id=run_id, message="Run started")


@router.get("/runs/latest", response_model=RunRead | None)
async def get_latest_run(db: AsyncSession = Depends(get_db)):
    stmt = select(Run).order_by(Run.id.desc()).limit(1)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    return run


@router.delete("/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Listing).where(Listing.id == listing_id)
    result = await db.execute(stmt)
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")

    listing.removed_at = datetime.now(timezone.utc)
    listing.is_active = False
    await db.commit()
