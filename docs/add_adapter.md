# How to Add a New Source Adapter

## 1. Create the adapter file

Create `app/adapters/my_source.py`:

```python
from app.adapters.base import AdapterError, BaseAdapter, AvailabilityResult, RawListing
from app.models import Watch


class MySourceAdapter(BaseAdapter):
    name = "my_source"

    async def search(self, watch: Watch) -> list[RawListing]:
        # Build query from watch.brand, watch.model, watch.references_csv
        # Fetch data from API or scraper
        # Return list[RawListing]
        ...

    async def check_availability(self, url: str) -> AvailabilityResult:
        # Optional: check if a listing URL is still live
        return AvailabilityResult(is_active=True)
```

## 2. Register the adapter

In `app/adapters/__init__.py`, import and add to `ALL_ADAPTERS`:

```python
from app.adapters.my_source import MySourceAdapter

ALL_ADAPTERS = [
    ...
    MySourceAdapter(),
]
```

## 3. Add required config

If your adapter needs API keys:
- Add to `.env.example`:
  ```
  MY_SOURCE_API_KEY=
  ```
- Add to `app/config.py` Settings class:
  ```python
  my_source_api_key: str = ""
  ```
- Use in adapter: `from app.config import settings`

## 4. Error handling

Always raise `AdapterError` for expected failures (bad credentials, API down, rate limits).
The job runner catches `AdapterError` per-adapter and logs it as a `RunSourceError` without stopping the rest of the run.

```python
from app.adapters.base import AdapterError

try:
    resp = await client.get(url)
    resp.raise_for_status()
except httpx.HTTPError as exc:
    raise AdapterError(f"My source request failed: {exc}") from exc
```

## 5. RawListing fields

| Field | Type | Notes |
|---|---|---|
| `source` | `str` | Must match `adapter.name` |
| `url` | `str` | Full URL to the listing |
| `title` | `str` | Listing title |
| `price_amount` | `float \| None` | Numeric price |
| `currency` | `str \| None` | ISO 4217 code: USD, JPY, EUR, etc. |
| `condition` | `str \| None` | e.g. "Used", "Pre-owned", "New" |
| `seller_location` | `str \| None` | Country or city |
| `image_url` | `str \| None` | Direct image URL |
| `extra_data` | `dict` | Source-specific metadata (stored as JSON) |

## 6. Test your adapter

```python
# scripts/test_adapter.py (ad hoc)
import asyncio
from app.adapters.my_source import MySourceAdapter
from app.models import Watch

async def main():
    adapter = MySourceAdapter()
    # Create a minimal Watch-like object
    class FakeWatch:
        brand = "Rolex"
        model = "Submariner"
        references_csv = "16610"
        query_terms = ""
        required_keywords = "[]"
        forbidden_keywords = "[]"

    results = await adapter.search(FakeWatch())
    print(f"Got {len(results)} results")
    for r in results[:3]:
        print(r)

asyncio.run(main())
```
