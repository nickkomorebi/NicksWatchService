"""Tests for app/services/matcher.py — is_match() logic."""
import pytest
from dataclasses import dataclass, field
from typing import Optional

from app.adapters.base import RawListing
from app.services.matcher import is_match


# ── Minimal stubs ─────────────────────────────────────────────────────────────

@dataclass
class FakeWatch:
    brand: str
    model: str
    references_csv: str = ""
    required_keywords: str = "[]"
    forbidden_keywords: str = "[]"


def listing(title: str, source: str = "ebay", url: str = "https://example.com") -> RawListing:
    return RawListing(
        source=source,
        url=url,
        title=title,
        price_amount=None,
        currency=None,
        condition=None,
        seller_location=None,
        image_url=None,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def submariner():
    return FakeWatch(brand="Rolex", model="Submariner", references_csv="16610, 16613")

@pytest.fixture
def reverso():
    return FakeWatch(brand="Jaeger-LeCoultre", model="Reverso", references_csv="Q3858522")


# ── Basic yes / no / ambiguous ────────────────────────────────────────────────

def test_brand_and_model_match(submariner):
    assert is_match(listing("Rolex Submariner 40mm stainless"), submariner) == "yes"

def test_reference_number_match(submariner):
    assert is_match(listing("Watch ref 16610 for sale"), submariner) == "yes"

def test_brand_only_is_ambiguous(submariner):
    assert is_match(listing("Beautiful Rolex for sale"), submariner) == "ambiguous"

def test_model_only_is_ambiguous(submariner):
    assert is_match(listing("Submariner — great deal"), submariner) == "ambiguous"

def test_no_match_returns_no(submariner):
    assert is_match(listing("Omega Seamaster 300m"), submariner) == "no"


# ── Forbidden keywords ────────────────────────────────────────────────────────

def test_always_forbidden_replica(submariner):
    assert is_match(listing("Rolex Submariner replica"), submariner) == "no"

def test_always_forbidden_homage(submariner):
    assert is_match(listing("Rolex Submariner homage watch"), submariner) == "no"

def test_always_forbidden_for_parts(submariner):
    assert is_match(listing("Rolex Submariner for parts not working"), submariner) == "no"

def test_always_forbidden_damaged(submariner):
    assert is_match(listing("Rolex Submariner 16610 damaged dial"), submariner) == "no"

def test_watch_specific_forbidden_keyword(submariner):
    submariner.forbidden_keywords = '["rubber strap"]'
    assert is_match(listing("Rolex Submariner with rubber strap"), submariner) == "no"


# ── Hyphen normalization ──────────────────────────────────────────────────────

def test_hyphenated_brand_matches_spaced_brand(reverso):
    # Brand in DB: "Jaeger-LeCoultre"; title uses space variant
    assert is_match(listing("Jaeger LeCoultre Reverso classic"), reverso) == "yes"

def test_spaced_brand_matches_hyphenated_title(reverso):
    # If brand stored without hyphen, title has hyphen
    watch = FakeWatch(brand="Jaeger LeCoultre", model="Reverso")
    assert is_match(listing("Jaeger-LeCoultre Reverso Grande Taille"), watch) == "yes"

def test_hyphenated_reference_matches(submariner):
    # Reference with hyphen variant in title
    watch = FakeWatch(brand="Rolex", model="Submariner", references_csv="5711/1A-001")
    assert is_match(listing("Patek Philippe 5711/1A 001 steel"), watch) == "yes"


# ── Required keywords ─────────────────────────────────────────────────────────

def test_required_keywords_all_present(submariner):
    submariner.required_keywords = '["stainless", "date"]'
    assert is_match(listing("Rolex Submariner stainless date 16610"), submariner) == "yes"

def test_required_keywords_one_missing(submariner):
    submariner.required_keywords = '["stainless", "date"]'
    # Has brand+model but missing "date"
    assert is_match(listing("Rolex Submariner stainless steel"), submariner) != "yes"

def test_required_keywords_empty_list_ignored(submariner):
    submariner.required_keywords = "[]"
    assert is_match(listing("Rolex Submariner 16610"), submariner) == "yes"


# ── Article filtering (web_search sources only) ───────────────────────────────

def test_article_title_filtered_from_web_search(submariner):
    assert is_match(
        listing("Rolex Submariner Review: Hands-On With the 16610", source="web_search"),
        submariner,
    ) == "no"

def test_article_domain_filtered_from_web_search(submariner):
    assert is_match(
        listing("Rolex Submariner", source="web_search", url="https://www.hodinkee.com/articles/rolex-sub"),
        submariner,
    ) == "no"

def test_article_title_not_filtered_from_ebay(submariner):
    # "review" in title from a non-web-search source should still match
    assert is_match(
        listing("Rolex Submariner 16610 — great review condition", source="ebay"),
        submariner,
    ) != "no"

def test_non_article_web_search_result(submariner):
    assert is_match(
        listing("Rolex Submariner 16610 for sale", source="web_search"),
        submariner,
    ) == "yes"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_title(submariner):
    assert is_match(listing(""), submariner) == "no"

def test_case_insensitive_match(submariner):
    assert is_match(listing("rolex submariner stainless"), submariner) == "yes"

def test_case_insensitive_forbidden(submariner):
    assert is_match(listing("Rolex Submariner REPLICA"), submariner) == "no"

def test_invalid_forbidden_keywords_json_ignored(submariner):
    submariner.forbidden_keywords = "not valid json"
    # Should not raise; falls back to ALWAYS_FORBIDDEN only
    assert is_match(listing("Rolex Submariner 16610"), submariner) == "yes"
