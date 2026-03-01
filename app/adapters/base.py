from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models import Watch


@dataclass
class RawListing:
    source: str
    url: str
    title: str
    price_amount: Optional[float]
    currency: Optional[str]
    condition: Optional[str]
    seller_location: Optional[str]
    image_url: Optional[str]
    extra_data: dict = field(default_factory=dict)


@dataclass
class AvailabilityResult:
    is_active: bool
    note: Optional[str] = None


class AdapterError(Exception):
    """Raised by adapters to signal a recoverable per-source failure."""


class BaseAdapter(ABC):
    name: str  # e.g. "ebay", "chrono24"

    @abstractmethod
    async def search(self, watch: "Watch") -> list[RawListing]:
        """Search for used listings of the given watch."""
        ...

    async def check_availability(self, url: str) -> AvailabilityResult:
        """Check if a previously found listing is still active. Default: assume active."""
        return AvailabilityResult(is_active=True)
