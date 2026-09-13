"""Phase 2 privacy sanitizer (eval E2-01 … E2-05). No Groq / LLM."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from pulse.config import load_config
from pulse.ingest.app_store import load_app_store_reviews
from pulse.ingest.common import flatten_rss_entry, load_tabular_records, parse_records
from pulse.privacy import (
    USER_PLACEHOLDER,
    drop_identity_fields,
    format_attribution,
    is_name_like_title,
    opaque_review_id,
    repair_text_encoding,
    sanitize_review,
    sanitize_reviews,
    sanitize_text,
)
from pulse.schemas import DateWindow, RawReview, SanitizedReview

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW = DateWindow(start_date=date(2026, 6, 27), end_date=date(2026, 9, 5))
ATTR_RE = re.compile(r"^\(\d★, (Play Store|App Store), \d{4}-\d{2}-\d{2}\)$")


@pytest.fixture
def config():
    return load_config()


def _raw(**overrides) -> RawReview:
    payload = {
        "store": "play",
        "review_id_source": "src-1",
        "rating": 2,
        "title": "KYC delay for two full days",
        "text": "Verification has been pending for two full days now.",
        "date": date(2026, 8, 1),
        "locale": "en_IN",
    }
    payload.update(overrides)
    return RawReview.model_validate(payload)


def test_rss_fixture_sanitizes_without_author_or_source_id(config):
    reviews = load_app_store_reviews(
        FIXTURES / "app_store_rss.json",
        window=WINDOW,
        config=config,
    )
    assert len(reviews) == 1
    raw = reviews[0]
    assert raw.review_id_source == "ios-rss-1"
    assert raw.date == date(2026, 7, 20)

    payload = json.loads((FIXTURES / "app_store_rss.json").read_text(encoding="utf-8"))
    rss_entry = payload["feed"]["entry"][1]
    assert rss_entry["author"]["name"]["label"] == "ios.user"
    stripped = drop_identity_fields(rss_entry)
    assert "author" not in stripped
    flat = flatten_rss_entry(stripped)
    assert flat is not None
    assert "author" not in flat
    assert "ios.user" not in json.dumps(flat)

    sanitized = sanitize_review(raw)
    assert sanitized is not None
    dumped = sanitized.model_dump()
    assert "author" not in dumped
    assert "review_id_source" not in dumped
    assert "ios.user" not in sanitized.text
    assert "ios-rss-1" not in sanitized.text
    assert sanitized.review_id != "ios-rss-1"
    assert sanitized.review_id == opaque_review_id("app_store", "ios-rss-1")
    assert re.fullmatch(r"[0-9a-f]{32}", sanitized.review_id)
    assert "e-KYC camera" in sanitized.text
    assert sanitized.title == "KYC on iPhone"
    assert format_attribution(
        rating=sanitized.rating, store=sanitized.store, on=sanitized.date
    ) == "(2★, App Store, 2026-07-20)"


def test_planted_email_phone_username_device_and_agent_name(config):
    records = load_tabular_records(FIXTURES / "reviews_pii_planted.json")
    raw_rows = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
    )
    by_source = {row.review_id_source: row for row in raw_rows}
    assert "pii-play-1" in by_source
    assert "author" not in by_source["pii-play-1"].model_dump()

    cleaned = {row.review_id_source: sanitize_review(row) for row in raw_rows}
    play = cleaned["pii-play-1"]
    assert play is not None
    blob = f"{play.title} {play.text}".lower()
    assert "alice@example.com" not in blob
    assert "90000" not in play.text
    assert "+91" not in play.text
    assert "deadbeef" not in blob
    assert "@alice_user" not in play.text
    assert "ansh agarwal" not in blob
    assert USER_PLACEHOLDER in play.text
    assert play.review_id != "pii-play-1"


def test_name_like_ios_title_dropped_feature_title_kept(config):
    records = load_tabular_records(FIXTURES / "reviews_pii_planted.json")
    raw_rows = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
    )
    by_source = {row.review_id_source: sanitize_review(row) for row in raw_rows}
    named = by_source["pii-ios-name-title"]
    kyc = by_source["pii-ios-kyc-title"]
    assert named is not None
    assert named.title is None
    assert "document twice" in named.text
    assert kyc is not None
    assert kyc.title == "KYC on iPhone"
    assert is_name_like_title("Pradeep Sholapurkar")
    assert is_name_like_title("Kishor")
    assert not is_name_like_title("KYC on iPhone")
    assert not is_name_like_title("Groww")


def test_product_and_competitor_terms_are_not_redacted():
    text = sanitize_text(
        "Groww KYC and UPI beat Zerodha and 5paisa on this GTT TradingView chart."
    )
    assert "Groww" in text
    assert "KYC" in text
    assert "UPI" in text
    assert "Zerodha" in text
    assert "5paisa" in text
    assert "GTT" in text
    assert "TradingView" in text
    assert USER_PLACEHOLDER not in text


def test_upi_handle_redacted_not_competitor_name(config):
    records = load_tabular_records(FIXTURES / "reviews_pii_planted.json")
    raw_rows = parse_records(
        records,
        window=WINDOW,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
    )
    upi = next(row for row in raw_rows if row.review_id_source == "pii-play-upi")
    cleaned = sanitize_review(upi)
    assert cleaned is not None
    assert "name@oksbi" not in cleaned.text
    assert "[upi]" in cleaned.text
    assert "Zerodha" in cleaned.text
    assert "5paisa" in cleaned.text


def test_review_only_pii_is_dropped():
    only_email = _raw(
        review_id_source="pii-play-only-email",
        title=None,
        text="alice@example.com",
    )
    assert sanitize_review(only_email) is None


def test_all_empty_after_sanitize_returns_empty_list():
    rows = [
        _raw(review_id_source="e1", text="alice@example.com", title=None),
        _raw(review_id_source="e2", text="+91 90000 00000", title=None),
    ]
    assert sanitize_reviews(rows) == []


def test_attribution_helper_has_no_author_or_store_id():
    play = format_attribution(rating=4, store="play", on=date(2026, 8, 12))
    ios = format_attribution(rating=2, store="app_store", on=date(2026, 7, 20))
    assert play == "(4★, Play Store, 2026-08-12)"
    assert ios == "(2★, App Store, 2026-07-20)"
    assert ATTR_RE.match(play)
    assert ATTR_RE.match(ios)
    assert "author" not in play.lower()
    assert "ios-rss" not in ios
    assert "user" not in play.lower()


def test_sanitized_review_forbids_author_field():
    with pytest.raises(ValidationError):
        SanitizedReview.model_validate(
            {
                "review_id": "abc",
                "store": "play",
                "rating": 1,
                "title": None,
                "text": "Verification has been pending for two full days now.",
                "date": "2026-08-01",
                "locale": "en_IN",
                "author": "alice",
            }
        )


def test_mojibake_repaired_before_redaction():
    messy = "whoÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢s developed such an easy user interface for trading"
    fixed = repair_text_encoding(messy)
    assert "Ã" not in fixed
    assert "who" in fixed.lower()
    review = _raw(text=messy, title="Easy user interface on this app")
    cleaned = sanitize_review(review)
    assert cleaned is not None
    assert "Ã" not in cleaned.text


def test_opaque_id_is_stable_and_not_source():
    first = opaque_review_id("app_store", "ios-rss-1")
    second = opaque_review_id("app_store", "ios-rss-1")
    other = opaque_review_id("play", "ios-rss-1")
    assert first == second
    assert first != "ios-rss-1"
    assert first != other


def test_in_and_intl_phones_and_pan_are_redacted():
    phones = sanitize_text(
        "Reach support at 9876543210 or 09876543210 or +1-555-0100 during market hours today."
    )
    assert "9876543210" not in phones
    assert "09876543210" not in phones
    assert "+1-555-0100" not in phones
    assert "[phone]" in phones
    pan = sanitize_text("Do not share ABCDE1234F on the KYC form during account setup today.")
    assert "ABCDE1234F" not in pan
    assert "[id]" in pan
    assert "KYC" in pan
