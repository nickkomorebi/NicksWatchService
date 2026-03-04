import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Watch

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "brand",
    "model",
    "references_csv",
    "query_terms",
    "required_keywords",
    "forbidden_keywords",
    "enabled",
]


def _build_service():
    """Build Google Sheets API service from config."""
    import google.auth
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    if settings.google_service_account_key:
        info = json.loads(settings.google_service_account_key)
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    elif settings.google_service_account_json:
        creds = service_account.Credentials.from_service_account_file(
            settings.google_service_account_json, scopes=scopes
        )
    else:
        raise RuntimeError(
            "Neither GOOGLE_SERVICE_ACCOUNT_KEY nor GOOGLE_SERVICE_ACCOUNT_JSON is set"
        )

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _parse_bool(val: str) -> bool:
    return val.strip().lower() not in ("0", "false", "no", "")


async def sync_watches(db: AsyncSession) -> int:
    """Pull watches from Google Sheet and upsert into DB. Returns upserted count."""
    if not settings.google_sheet_id:
        logger.warning("GOOGLE_SHEET_ID not set; skipping sheet sync")
        return 0

    service = _build_service()
    sheet = service.spreadsheets()
    range_name = f"{settings.google_sheet_tab}!A1:Z1000"

    result = sheet.values().get(spreadsheetId=settings.google_sheet_id, range=range_name).execute()
    rows = result.get("values", [])

    if not rows:
        logger.warning("Google Sheet returned no rows")
        return 0

    headers = [h.strip().lower() for h in rows[0]]
    upserted = 0

    # Map sheet column names → Watch field names
    COLUMN_MAP = {
        "brand": "brand",
        "name": "model",
        "model": "model",
        "reference": "references_csv",
        "references_csv": "references_csv",
        "keywords": "query_terms",
        "query_terms": "query_terms",
        "search keywords": "query_terms",  # sheet header alias
        "search_keywords": "query_terms",  # underscore variant
        "notes": "query_terms",       # falls back; keywords wins if both present
        "required_keywords": "required_keywords",
        "forbidden_keywords": "forbidden_keywords",
        "enabled": "enabled",
    }

    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue  # skip blank rows

        raw = dict(zip(headers, row + [""] * (len(headers) - len(row))))

        # Remap to model field names
        data: dict[str, str] = {}
        for col, val in raw.items():
            field = COLUMN_MAP.get(col.strip().lower())
            if field and val.strip():
                data[field] = val.strip()

        brand = data.get("brand", "").strip()
        model = data.get("model", "").strip()
        if not brand or not model:
            continue

        enabled = _parse_bool(data.get("enabled", "1"))
        now = datetime.now(timezone.utc)

        stmt = select(Watch).where(Watch.brand == brand, Watch.model == model)
        result = await db.execute(stmt)
        watch = result.scalar_one_or_none()

        if watch is None:
            watch = Watch(brand=brand, model=model)
            db.add(watch)

        watch.references_csv = data.get("references_csv") or None
        watch.query_terms = data.get("query_terms") or None
        watch.required_keywords = data.get("required_keywords") or None
        watch.forbidden_keywords = data.get("forbidden_keywords") or None
        watch.enabled = enabled
        watch.synced_at = now
        upserted += 1

    await db.commit()
    logger.info("Synced %d watches from Google Sheet", upserted)
    return upserted


def get_owned_watches() -> list[dict]:
    """Read the Owner tab from the sheet. Returns list of row dicts (all columns).

    Synchronous — call via asyncio.to_thread() from async contexts.
    """
    if not settings.google_sheet_id:
        logger.warning("GOOGLE_SHEET_ID not set; cannot read Owner tab")
        return []

    service = _build_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.google_sheet_id, range="Owned!A2:Z1000")
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        return []

    headers = [h.strip() for h in rows[0]]
    out = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        d = dict(zip(headers, row + [""] * (len(headers) - len(row))))
        out.append(d)

    logger.info("Loaded %d owned watches from Owner tab", len(out))
    return out
