from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str
    model: str
    references_csv: str | None
    query_terms: str | None
    enabled: bool
    synced_at: datetime | None


class ListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    watch_id: int
    source: str
    url: str
    title: str | None
    price_amount: float | None
    currency: str | None
    condition: str | None
    seller_location: str | None
    image_url: str | None
    first_seen_at: datetime
    last_seen_at: datetime | None
    is_active: bool
    availability_note: str | None
    confidence_score: float | None
    confidence_rationale: str | None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    error_summary: str | None
    watches_processed: int
    listings_found: int
    listings_new: int
    triggered_by: str | None


class RunSourceErrorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    watch_id: int | None
    source: str
    error: str
    created_at: datetime


class TriggerResponse(BaseModel):
    run_id: int
    message: str
