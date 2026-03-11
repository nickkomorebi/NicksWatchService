import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, RawListing
from app.database import AsyncSessionLocal
from app.models import Listing, Run, RunSourceError, Watch
from app.services import matcher

logger = logging.getLogger(__name__)

WATCH_CONCURRENCY = 3   # watches processed in parallel
ADAPTER_CONCURRENCY = 4  # adapters per watch in parallel
LLM_CONFIDENCE_THRESHOLD = 0.6  # listings below this are excluded

# Estimated average tokens per call (used for cost logging only)
_LV_INPUT_TOKENS = 300    # llm_verify: claude-sonnet-4-6
_LV_OUTPUT_TOKENS = 50
_IV_INPUT_TOKENS = 1500   # verify_watch_image: claude-haiku-4-5 (image tiles + prompt)
_IV_OUTPUT_TOKENS = 3
_LV_COST_PER_CALL = (_LV_INPUT_TOKENS * 3.00 + _LV_OUTPUT_TOKENS * 15.00) / 1_000_000   # ~$0.00165
_IV_COST_PER_CALL = (_IV_INPUT_TOKENS * 0.80 + _IV_OUTPUT_TOKENS * 4.00) / 1_000_000    # ~$0.00121

# Sources where titles can't be reliably parsed with English keyword matching —
# every non-rejected result gets LLM verification regardless of is_match result.
ALWAYS_VERIFY_SOURCES = {"mercari_jp", "yahoo_jp"}


def make_url_hash(source: str, url: str) -> str:
    canonical = url.split("?")[0].rstrip("/")
    return hashlib.sha256(f"{source}:{canonical}".encode()).hexdigest()


def make_fallback_hash(source: str, title: str, price: float | None) -> str:
    key = f"{source}:{title}:{price}"
    return hashlib.sha256(key.encode()).hexdigest()


async def _upsert_listing(
    db: AsyncSession,
    raw: RawListing,
    watch: Watch,
    confidence_score: float | None,
    confidence_rationale: str | None,
    run_seen_hashes: set[str],
) -> bool:
    """Insert or update a listing. Returns True if it was newly created."""
    url_hash = make_url_hash(raw.source, raw.url) if raw.url else make_fallback_hash(raw.source, raw.title, raw.price_amount)
    run_seen_hashes.add(url_hash)

    now = datetime.now(timezone.utc)
    stmt = select(Listing).where(Listing.url_hash == url_hash)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # If the user dismissed this listing, never resurface it
        if existing.removed_at is not None:
            return False
        existing.last_seen_at = now
        existing.last_checked_at = now
        existing.is_active = True
        existing.removed_at = None
        existing.availability_note = None
        if raw.title:
            existing.title = raw.title
        if raw.price_amount is not None:
            existing.price_amount = raw.price_amount
        if raw.image_url:
            existing.image_url = raw.image_url
        await db.commit()
        return False
    else:
        listing = Listing(
            watch_id=watch.id,
            source=raw.source,
            url=raw.url,
            url_hash=url_hash,
            title=raw.title,
            price_amount=raw.price_amount,
            currency=raw.currency,
            condition=raw.condition,
            seller_location=raw.seller_location,
            image_url=raw.image_url,
            listed_at=raw.listed_at,
            first_seen_at=now,
            last_seen_at=now,
            last_checked_at=now,
            is_active=True,
            confidence_score=confidence_score,
            confidence_rationale=confidence_rationale,
            extra_data=json.dumps(raw.extra_data) if raw.extra_data else None,
        )
        db.add(listing)
        await db.commit()
        return True


async def _process_adapter(
    adapter,
    watch: Watch,
    run_id: int,
    run_seen_hashes: set[str],
) -> tuple[int, int, list[str], int, int, int, int]:
    """Run one adapter for one watch.
    Returns (found, new, errors, lv_calls, lv_rejected, iv_calls, iv_rejected).
    """
    errors = []
    found = 0
    new = 0
    lv_calls = 0      # llm_verify calls (claude-sonnet-4-6)
    lv_rejected = 0   # listings dropped by llm_verify
    iv_calls = 0      # verify_watch_image calls (claude-haiku-4-5)
    iv_rejected = 0   # images dropped by verify_watch_image

    try:
        raw_listings: list[RawListing] = await adapter.search(watch)
    except AdapterError as exc:
        msg = str(exc)
        logger.warning("[%s][%s] AdapterError: %s", watch.brand, adapter.name, msg)
        errors.append(msg)
        return found, new, errors, lv_calls, lv_rejected, iv_calls, iv_rejected
    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        logger.exception("[%s][%s] %s", watch.brand, adapter.name, msg)
        errors.append(msg)
        return found, new, errors, lv_calls, lv_rejected, iv_calls, iv_rejected

    # Each adapter gets its own session — concurrent adapters sharing one session
    # can corrupt it when commits interleave across await points.
    async with AsyncSessionLocal() as db:
        for raw in raw_listings:
            if not raw.url and not raw.title:
                continue

            result = matcher.is_match(raw, watch)
            if result == "no":
                continue

            confidence_score = None
            confidence_rationale = None

            needs_llm = result == "ambiguous" or raw.source in ALWAYS_VERIFY_SOURCES
            if needs_llm:
                lv_calls += 1
                try:
                    confidence_score, confidence_rationale = await matcher.llm_verify(raw, watch)
                except Exception as exc:
                    logger.warning("LLM verify failed for '%s': %s", raw.title, exc)
                    confidence_score = 0.5
                    confidence_rationale = f"LLM error: {exc}"
                if confidence_score < LLM_CONFIDENCE_THRESHOLD:
                    lv_rejected += 1
                    logger.info(
                        "LLM rejected [%s][%s]: %s (score=%.2f)",
                        watch.brand, raw.source, raw.title, confidence_score,
                    )
                    continue

            # Fetch image for sources that don't provide one
            if not raw.image_url and raw.url:
                from app.services.image_fetcher import fetch_listing_image, verify_watch_image
                candidate = await fetch_listing_image(raw.url)
                if candidate:
                    iv_calls += 1
                    if await verify_watch_image(candidate):
                        raw.image_url = candidate
                        logger.debug("Fetched image for %s: %s", raw.title, candidate)
                    else:
                        iv_rejected += 1
                        logger.info(
                            "Image rejected [%s][%s]: %s",
                            watch.brand, raw.source, raw.title,
                        )

            found += 1
            is_new = await _upsert_listing(db, raw, watch, confidence_score, confidence_rationale, run_seen_hashes)
            if is_new:
                new += 1

    return found, new, errors, lv_calls, lv_rejected, iv_calls, iv_rejected


async def _process_watch(
    watch: Watch,
    adapters: list,
    run_id: int,
    run_seen_hashes: set[str],
    db: AsyncSession,
) -> tuple[int, int, int, int, int, int]:
    """Process all adapters for one watch.
    Returns (total_found, total_new, lv_calls, lv_rejected, iv_calls, iv_rejected).
    """
    sem = asyncio.Semaphore(ADAPTER_CONCURRENCY)

    async def run_with_sem(adapter):
        async with sem:
            return await _process_adapter(adapter, watch, run_id, run_seen_hashes)

    results = await asyncio.gather(*[run_with_sem(a) for a in adapters], return_exceptions=True)

    total_found = 0
    total_new = 0
    total_lv_calls = 0
    total_lv_rejected = 0
    total_iv_calls = 0
    total_iv_rejected = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Adapter %s raised uncaught exception: %s", adapters[i].name, result)
            err = RunSourceError(
                run_id=run_id,
                watch_id=watch.id,
                source=adapters[i].name,
                error=str(result),
            )
            db.add(err)
            await db.commit()
            continue

        found, new, errors, lv_calls, lv_rejected, iv_calls, iv_rejected = result
        total_found += found
        total_new += new
        total_lv_calls += lv_calls
        total_lv_rejected += lv_rejected
        total_iv_calls += iv_calls
        total_iv_rejected += iv_rejected

        for err_msg in errors:
            err = RunSourceError(
                run_id=run_id,
                watch_id=watch.id,
                source=adapters[i].name,
                error=err_msg,
            )
            db.add(err)
        if errors:
            await db.commit()

    return total_found, total_new, total_lv_calls, total_lv_rejected, total_iv_calls, total_iv_rejected


async def run_job(triggered_by: str = "scheduler", existing_run_id: int | None = None) -> int:
    """Main entry point for the watch search job. Returns the run ID."""
    from app.adapters import ALL_ADAPTERS
    from app.services.sheets import sync_watches

    async with AsyncSessionLocal() as db:
        if existing_run_id is not None:
            # Row was already created by the API handler
            run_id = existing_run_id
        else:
            # Check for already-running run
            stmt = select(Run).where(Run.status == "running")
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                logger.warning("Run already in progress (id=%d); skipping", existing.id)
                return existing.id

            run = Run(status="running", triggered_by=triggered_by)
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        logger.info("Started run id=%d triggered_by=%s", run_id, triggered_by)

    try:
        async with AsyncSessionLocal() as db:
            await sync_watches(db)

        async with AsyncSessionLocal() as db:
            stmt = select(Watch).where(Watch.enabled == True)  # noqa: E712
            result = await db.execute(stmt)
            watches = result.scalars().all()

        logger.info("Processing %d watches", len(watches))

        run_seen_hashes: set[str] = set()
        total_found = 0
        total_new = 0
        total_lv_calls = 0
        total_lv_rejected = 0
        total_iv_calls = 0
        total_iv_rejected = 0

        sem = asyncio.Semaphore(WATCH_CONCURRENCY)

        async def process_one(watch: Watch):
            async with sem:
                async with AsyncSessionLocal() as db:
                    return await _process_watch(watch, ALL_ADAPTERS, run_id, run_seen_hashes, db)

        watch_results = await asyncio.gather(*[process_one(w) for w in watches], return_exceptions=True)

        for i, r in enumerate(watch_results):
            if isinstance(r, Exception):
                logger.error("Watch %s failed: %s", watches[i].brand, r)
            else:
                f, n, lv_calls, lv_rejected, iv_calls, iv_rejected = r
                total_found += f
                total_new += n
                total_lv_calls += lv_calls
                total_lv_rejected += lv_rejected
                total_iv_calls += iv_calls
                total_iv_rejected += iv_rejected

        # Log LLM usage and estimated cost for this run
        lv_cost = total_lv_calls * _LV_COST_PER_CALL
        iv_cost = total_iv_calls * _IV_COST_PER_CALL
        logger.info(
            "LLM usage — listing verify (sonnet): %d calls, %d rejected, est. $%.4f | "
            "image verify (haiku): %d calls, %d rejected, est. $%.4f | "
            "total est. $%.4f",
            total_lv_calls, total_lv_rejected, lv_cost,
            total_iv_calls, total_iv_rejected, iv_cost,
            lv_cost + iv_cost,
        )

        # Backfill images for active listings that still have none
        from app.services.image_fetcher import fetch_listing_image, verify_watch_image
        async with AsyncSessionLocal() as db:
            stmt = select(Listing).where(
                Listing.is_active == True,  # noqa: E712
                Listing.removed_at == None,  # noqa: E711
                Listing.image_url == None,  # noqa: E711
                Listing.url != None,  # noqa: E711
            )
            result = await db.execute(stmt)
            imageless = result.scalars().all()
            if imageless:
                logger.info("Backfilling images for %d listings", len(imageless))

            async def _backfill(listing: Listing):
                candidate = await fetch_listing_image(listing.url)
                if candidate and await verify_watch_image(candidate):
                    listing.image_url = candidate

            await asyncio.gather(*[_backfill(l) for l in imageless], return_exceptions=True)
            await db.commit()

        # Mark listings not seen in this run as inactive
        async with AsyncSessionLocal() as db:
            stmt = (
                select(Listing)
                .where(Listing.is_active == True, Listing.removed_at == None)  # noqa: E712, E711
            )
            result = await db.execute(stmt)
            all_active = result.scalars().all()
            now = datetime.now(timezone.utc)
            for listing in all_active:
                if listing.url_hash not in run_seen_hashes:
                    listing.is_active = False
                    listing.availability_note = "not found in run"
                    listing.last_checked_at = now
            await db.commit()

        # Finalize run
        async with AsyncSessionLocal() as db:
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one()
            run.finished_at = datetime.now(timezone.utc)
            run.status = "succeeded"
            run.watches_processed = len(watches)
            run.listings_found = total_found
            run.listings_new = total_new
            await db.commit()

        logger.info(
            "Run id=%d succeeded: %d watches, %d found, %d new",
            run_id, len(watches), total_found, total_new,
        )

    except Exception as exc:
        logger.exception("Run id=%d failed: %s", run_id, exc)
        async with AsyncSessionLocal() as db:
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run:
                run.finished_at = datetime.now(timezone.utc)
                run.status = "failed"
                run.error_summary = str(exc)
                await db.commit()

    return run_id
