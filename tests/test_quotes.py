"""Phase 4 quote lock, actions, and pulse template (eval E4-02 … E4-06)."""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from pulse.actions import propose_actions
from pulse.quotes import (
    QuoteLockError,
    _quote_prompt_pool,
    heuristic_nominator,
    llm_nominator,
    lock_quote,
    select_quotes,
)
from pulse.schemas import (
    ActionIdea,
    DateWindow,
    ProductInfo,
    Quote,
    SanitizedReview,
    ThemeCluster,
)
from pulse.write import word_count, write_pulse_note

RSS_BODY = "The e-KYC camera step failed twice during account setup."
WINDOW = DateWindow(start_date=date(2026, 6, 27), end_date=date(2026, 9, 5))
PRODUCT = ProductInfo(
    name="Groww",
    android_id="com.nextbillion.groww",
    ios_id="1404871703",
    locale="en_IN",
)


@pytest.fixture(autouse=True)
def _no_live_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "pulse.llm.chat_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("live LLM must not be called in quote tests")
        ),
    )


def _review(**overrides) -> SanitizedReview:
    payload = {
        "review_id": "rev-1",
        "store": "play",
        "rating": 2,
        "title": "KYC stuck",
        "text": "Verification has been pending for two full days.",
        "date": date(2026, 7, 15),
        "locale": "en_IN",
    }
    payload.update(overrides)
    return SanitizedReview.model_validate(payload)


def _cluster(name: str, reviews: list[SanitizedReview], *, severity: str = "high") -> ThemeCluster:
    ratings = [row.rating for row in reviews]
    return ThemeCluster(
        name=name,
        review_ids=[row.review_id for row in reviews],
        count=len(reviews),
        avg_rating=round(sum(ratings) / len(ratings), 2),
        severity=severity,
        play_count=sum(1 for row in reviews if row.store == "play"),
        app_store_count=sum(1 for row in reviews if row.store == "app_store"),
    )


def _corpus() -> tuple[list[SanitizedReview], list[ThemeCluster]]:
    reviews = [
        _review(
            review_id="play-kyc",
            text="Verification has been pending for two full days.",
            rating=2,
        ),
        _review(
            review_id="play-upi",
            title="UPI failed",
            text="Add money with UPI failed twice today again.",
            rating=1,
            date=date(2026, 8, 1),
        ),
        _review(
            review_id="play-wd",
            title="Withdrawal delay",
            text="Bank withdrawal sat in processing for a day.",
            rating=2,
            date=date(2026, 8, 20),
        ),
        _review(
            review_id="ios-kyc",
            store="app_store",
            title="KYC on iPhone",
            text=RSS_BODY,
            rating=2,
            date=date(2026, 7, 20),
        ),
    ]
    clusters = [
        _cluster("Support and account access", [reviews[0], reviews[3]]),
        _cluster("Payments and UPI", [reviews[1]]),
        _cluster("Withdrawals", [reviews[2]]),
    ]
    return reviews, clusters


def test_paraphrase_is_rejected():
    review = _review(text=RSS_BODY, store="app_store", title="KYC on iPhone")
    with pytest.raises(QuoteLockError, match="not a substring"):
        lock_quote(review, "The e-KYC camera step failed twice and the app also crashed")


def test_name_like_title_is_not_used_as_a_quote():
    review = _review(text=RSS_BODY, title=None, store="app_store")
    with pytest.raises(QuoteLockError, match="name-like"):
        lock_quote(review, "Pradeep Sholapurkar")


def test_rss_body_copied_not_author_or_source_id():
    review = _review(
        review_id="hashed-ios",
        store="app_store",
        title="KYC on iPhone",
        text=RSS_BODY,
        date=date(2026, 7, 20),
    )
    quote = lock_quote(review, "The e-KYC camera step failed twice")
    assert quote.text == "The e-KYC camera step failed twice"
    assert quote.text in review.text
    assert "ios.user" not in quote.text
    assert "ios-rss-1" not in quote.text
    full = lock_quote(review)
    assert full.text == RSS_BODY


def test_select_quotes_locks_three_distinct_ids():
    reviews, clusters = _corpus()
    quotes = select_quotes(reviews, clusters, nominator=heuristic_nominator)
    assert len(quotes) == 3
    ids = [row.review_id for row in quotes]
    assert len(set(ids)) == 3
    by_id = {row.review_id: row for row in reviews}
    for quote in quotes:
        assert quote.text in by_id[quote.review_id].text


def test_nominated_paraphrase_fails_closed():
    reviews, clusters = _corpus()

    def nominator(_reviews, _clusters):
        return [
            SimpleNamespace(review_id="play-kyc", text="KYC is slow and confusing overall"),
            "play-upi",
            "play-wd",
        ]

    with pytest.raises(QuoteLockError, match="not a substring"):
        select_quotes(reviews, clusters, nominator=nominator)


def test_three_actions_tagged_to_clustered_themes():
    _reviews, clusters = _corpus()
    ideas = propose_actions(clusters)
    names = {row.name for row in clusters}
    assert len(ideas) == 3
    assert all(idea.theme in names for idea in ideas)


def test_slogan_actions_are_replaced():
    _reviews, clusters = _corpus()

    def builder(rows: list[ThemeCluster]) -> list[ActionIdea]:
        return [
            ActionIdea(
                title="Improve UX",
                rationale="Listen to users and enhance experience.",
                theme=row.name,
                owner_hint="Product",
            )
            for row in rows[:3]
        ]

    ideas = propose_actions(clusters, builder=builder)
    blob = " ".join(f"{idea.title} {idea.rationale}" for idea in ideas).lower()
    assert "improve ux" not in blob
    assert "listen to users" not in blob
    assert all(idea.theme in {row.name for row in clusters} for idea in ideas)


def test_pulse_body_matches_three_section_template():
    reviews, clusters = _corpus()
    quotes = select_quotes(reviews, clusters, nominator=heuristic_nominator)
    actions = propose_actions(clusters)
    note = write_pulse_note(
        product=PRODUCT,
        window=WINDOW,
        clusters=clusters,
        quotes=quotes,
        actions=actions,
        weeks=10,
        reviews=reviews,
    )
    body = note.body
    assert "Groww Weekly Review Pulse" in note.title
    assert re.search(r"1\.\s+Top 3 themes", body)
    assert re.search(r"2\.\s+What users said \(3 quotes\)", body)
    assert re.search(r"3\.\s+Three action ideas", body)
    assert word_count(body) <= 250
    for quote in quotes:
        assert quote.text in body
    assert len(note.themes) == 3
    assert len(note.quotes) == 3
    assert len(note.actions) == 3


def test_quote_prompt_pool_stays_small():
    reviews, clusters = _corpus()
    extra = [
        _review(review_id=f"extra-{i}", text=f"Extra complaint number {i} about charts.")
        for i in range(40)
    ]
    reviews = reviews + extra
    clusters[0].review_ids.extend([row.review_id for row in extra])
    clusters[0].count = len(clusters[0].review_ids)
    pool = _quote_prompt_pool(reviews, clusters)
    assert 3 <= len(pool) <= 18


def test_llm_nominator_falls_back_when_groq_rejects():
    reviews, clusters = _corpus()

    class Boom:
        def invoke(self, _prompt):
            raise RuntimeError("Error code: 413 - Request too large")

    ids = llm_nominator(Boom())(reviews, clusters)
    assert len(ids) == 3
    assert set(ids).issubset({row.review_id for row in reviews})


def test_quote_tests_do_not_call_live_model(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("live Groq must not be called in quote tests")

    monkeypatch.setattr("pulse.graph.chat_model", forbidden)
    monkeypatch.setattr("pulse.quotes.llm_nominator", forbidden)

    reviews, clusters = _corpus()
    quotes = select_quotes(reviews, clusters, nominator=heuristic_nominator)
    assert len(quotes) == 3
    assert all(isinstance(row, Quote) for row in quotes)
