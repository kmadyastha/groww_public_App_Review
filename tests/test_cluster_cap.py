"""Phase 4 theme cap and export-backed labels (eval E4-01)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from pulse.cluster import cluster_reviews, finalize_clusters, keyword_assigner
from pulse.config import load_config
from pulse.ingest import load_reviews
from pulse.privacy import sanitize_reviews
from pulse.prompts import CANDIDATE_THEMES, FORBIDDEN_EMPTY_SEEDS
from pulse.schemas import DateWindow, ProductInfo, SanitizedReview, ThemeCluster
from pulse.state import PulseState

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW = DateWindow(start_date=date(2026, 6, 27), end_date=date(2026, 9, 5))
RSS_BODY = "The e-KYC camera step failed twice during account setup."

_SEVEN_THEMES = (
    "Charts and trading tools",
    "Brokerage and charges",
    "Order execution and fills",
    "Support and account access",
    "App stability and updates",
    "Payments and UPI",
    "Withdrawals",
)


def _review(i: int, *, text: str | None = None) -> SanitizedReview:
    return SanitizedReview(
        review_id=f"rev-{i}",
        store="play" if i % 2 == 0 else "app_store",
        rating=1 + (i % 5),
        title=None,
        text=text or f"Review body number {i} has enough words here.",
        date=date(2026, 8, 1),
        locale="en_IN",
    )


def _theme(name: str, i: int) -> ThemeCluster:
    return ThemeCluster(
        name=name,
        review_ids=[f"rev-{i}"],
        count=1,
        avg_rating=2.0,
        severity="high",
        play_count=1,
        app_store_count=0,
    )


def test_finalize_clusters_caps_seven_themes_at_five():
    extra = _theme("IPO applications", 7)
    clusters = [_theme(name, i) for i, name in enumerate(_SEVEN_THEMES)] + [extra]
    assert len(clusters) >= 7
    capped = finalize_clusters(clusters)
    assert len(capped) == 5
    assert len(capped) <= 5


def test_mock_assigner_returning_seven_themes_persists_at_most_five():
    reviews = [_review(i) for i in range(7)]

    def assigner(rows: list[SanitizedReview], _candidates) -> list[tuple[str, str]]:
        return [(row.review_id, _SEVEN_THEMES[i]) for i, row in enumerate(rows)]

    clusters = cluster_reviews(reviews, assigner=assigner)
    assert len(clusters) <= 5
    assert len(clusters) == 5
    names = {row.name for row in clusters}
    assert "statements" not in {name.lower() for name in names}


def test_pulse_state_still_rejects_six_clusters():
    product = ProductInfo(
        name="Groww",
        android_id="com.nextbillion.groww",
        ios_id="1404871703",
        locale="en_IN",
    )
    clusters = [_theme(f"Theme {i}", i) for i in range(6)]
    with pytest.raises(ValidationError, match="at most 5"):
        PulseState(run_id="cap", window=WINDOW, product=product, clusters=clusters)


def test_mock_llm_returning_seven_themes_is_capped():
    reviews = [_review(i) for i in range(7)]

    class FakeLLM:
        def invoke(self, _prompt):
            return {
                "assignments": [
                    {"review_id": f"rev-{i}", "theme": name}
                    for i, name in enumerate(_SEVEN_THEMES)
                ]
            }

    clusters = cluster_reviews(reviews, llm=FakeLLM())
    assert len(clusters) <= 5
    assert len(clusters) == 5


def test_llm_assigner_skips_remaining_chunks_after_groq_failure():
    reviews = [
        _review(i, text="Charts freeze and the back button is broken after the update.")
        for i in range(90)
    ]
    calls = {"n": 0}

    class Boom:
        def invoke(self, _prompt):
            calls["n"] += 1
            raise RuntimeError("Error code: 400 - tool_use_failed")

    clusters = cluster_reviews(reviews, llm=Boom())
    assert calls["n"] == 1
    assert clusters
    assert all(row.name in CANDIDATE_THEMES for row in clusters)


def test_rss_kyc_lands_in_support_not_statements():
    config = load_config()
    raw = load_reviews(
        WINDOW,
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_rss=False,
        fetch_public=False,
    )
    reviews = sanitize_reviews(raw)
    kyc = next(row for row in reviews if RSS_BODY in row.text)
    clusters = cluster_reviews(reviews, assigner=keyword_assigner)
    owner = next(row for row in clusters if kyc.review_id in row.review_ids)
    assert owner.name == "Support and account access"
    assert "statement" not in owner.name.lower()
    for forbidden in FORBIDDEN_EMPTY_SEEDS:
        assert forbidden not in owner.name.lower()
    assert all(row.name in CANDIDATE_THEMES for row in clusters)
    assert len(clusters) <= 5
