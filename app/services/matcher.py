import json
import logging
from typing import TYPE_CHECKING, Literal

from app.adapters.base import RawListing

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

ALWAYS_FORBIDDEN = [
    "replica",
    "homage",
    "parts",
    "for parts",
    "broken",
    "not working",
    "damaged",
]

# Title patterns that indicate editorial content rather than a for-sale listing
ARTICLE_TITLE_INDICATORS = [
    "review",
    "hands-on",
    "hands on",
    "introducing",
    "first look",
    "in-depth",
    "interview",
    "history of",
    "the story of",
    "guide to",
    "top 10",
    "best watches",
    "vs.",
    " vs ",
    "comparison",
    "buying guide",
    "reference guide",
    "watch of the",
    "video:",
    "podcast",
    "auction results",
    "market report",
    "why ",
    "how to",
    "what is",
]

# Domains that only publish editorial/review content (never listings)
ARTICLE_DOMAINS = {
    "ablogtowatch.com",
    "hodinkee.com",
    "fratellowatches.com",
    "monochrome-watches.com",
    "watchpro.com",
    "calibre11.com",
    "deployant.com",
    "revolution.watch",
    "watchtime.com",
    "europastar.com",
    "wthejournal.com",
    "watchingtyme.com",
    "watchingtyme.co.uk",
    "quillandpad.com",
    "wornandwound.com",
    "nytimes.com",
    "bloomberg.com",
    "forbes.com",
    "businessinsider.com",
    "gq.com",
    "esquire.com",
}

WEB_SEARCH_SOURCES = {"web_search", "web_search_recent"}


def _is_article(raw: RawListing) -> bool:
    """Return True if this web search result looks like an article rather than a listing."""
    title_lower = (raw.title or "").lower()
    if any(indicator in title_lower for indicator in ARTICLE_TITLE_INDICATORS):
        return True
    url_lower = (raw.url or "").lower()
    if any(domain in url_lower for domain in ARTICLE_DOMAINS):
        return True
    return False


def is_match(raw: RawListing, watch: "Watch") -> Literal["yes", "no", "ambiguous"]:
    # Drop editorial content from web search sources immediately
    if raw.source in WEB_SEARCH_SOURCES and _is_article(raw):
        return "no"

    # Normalize hyphens → spaces so "Jaeger-LeCoultre" matches "Jaeger LeCoultre"
    raw_text = (raw.title or "").lower().replace("-", " ")
    # Use normalized text for all keyword checks; original for forbidden (to avoid
    # accidentally un-forbidding multi-word phrases that cross a hyphen boundary)
    text = raw_text

    forbidden = list(ALWAYS_FORBIDDEN)
    try:
        forbidden += json.loads(watch.forbidden_keywords or "[]")
    except json.JSONDecodeError:
        pass

    if any(kw.lower().replace("-", " ") in text for kw in forbidden):
        return "no"

    refs = [r.strip() for r in (watch.references_csv or "").split(",") if r.strip()]
    has_ref = any(ref.lower().replace("-", " ") in text for ref in refs)

    has_brand = watch.brand.lower().replace("-", " ") in text
    has_model = watch.model.lower().replace("-", " ") in text

    try:
        required = json.loads(watch.required_keywords or "[]")
    except json.JSONDecodeError:
        required = []
    has_required = all(kw.lower().replace("-", " ") in text for kw in required) if required else True

    if has_ref or (has_brand and has_model and has_required):
        return "yes"

    if has_brand or has_model:
        return "ambiguous"

    return "no"


async def llm_verify(raw: RawListing, watch: "Watch") -> tuple[float, str]:
    """Call Claude to score an ambiguous listing. Returns (confidence, rationale)."""
    from app.config import settings

    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set; skipping LLM verification")
        return 0.5, "LLM verification skipped: no API key"

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    prompt = (
        f"You are a watch authentication expert. Determine whether the following listing "
        f"is a genuine used listing for a {watch.brand} {watch.model} "
        f"(reference numbers: {watch.references_csv or 'any'}).\n\n"
        f"Listing title: {raw.title}\n"
        f"Source: {raw.source}\n"
        f"Price: {raw.price_amount} {raw.currency}\n"
        f"Condition: {raw.condition}\n"
        f"Location: {raw.seller_location}\n\n"
        f"Respond with JSON only:\n"
        f'{{"confidence": <0.0-1.0>, "rationale": "<one sentence>"}}'
    )

    try:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = json.loads(text)
        confidence = float(data.get("confidence", 0.5))
        rationale = str(data.get("rationale", ""))
        return confidence, rationale
    except Exception as exc:
        logger.warning("LLM verification failed: %s", exc)
        return 0.5, f"LLM error: {exc}"
