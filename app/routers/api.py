import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
        if age < timedelta(hours=6):
            next_run = finished + timedelta(hours=6)
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


@router.get("/ebay/marketplace-account-deletion")
async def ebay_challenge(challenge_code: str):
    """eBay verification handshake — responds with SHA-256 of code+token+url."""
    if not settings.ebay_verification_token or not settings.ebay_deletion_endpoint_url:
        raise HTTPException(status_code=503, detail="eBay deletion endpoint not configured")
    digest = hashlib.sha256(
        (challenge_code + settings.ebay_verification_token + settings.ebay_deletion_endpoint_url).encode()
    ).hexdigest()
    return {"challengeResponse": digest}


@router.post("/ebay/marketplace-account-deletion", status_code=status.HTTP_200_OK)
async def ebay_account_deletion(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive eBay account deletion notifications and purge matching listings."""
    body = await request.json()
    data = body.get("notification", {}).get("data", {})
    username = data.get("username", "")
    user_id = data.get("userId", "")
    logger.info("eBay account deletion notification: userId=%s username=%s", user_id, username)

    # We don't store seller user IDs, but purge any eBay listings whose URL
    # contains the user ID (eBay member URLs follow /usr/<userId> patterns).
    if user_id:
        await db.execute(
            delete(Listing).where(
                Listing.source == "ebay",
                Listing.url.contains(user_id),
            )
        )
        await db.commit()

    return {"status": "ok"}


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
