"""Phase 0 schema contracts (eval E0-03, E0-04)."""

from datetime import date

import pytest
from pydantic import ValidationError

from pulse.schemas import (
    ActionIdea,
    DateWindow,
    ProductInfo,
    PulseNote,
    Quote,
    RawReview,
    ThemeCluster,
    ThemeHighlight,
)
from pulse.state import PulseState


def _raw_review(**overrides) -> RawReview:
    payload = {
        "store": "play",
        "review_id_source": "src-1",
        "rating": 4,
        "title": "KYC delay",
        "text": "Verification took two days.",
        "date": date(2026, 8, 1),
        "locale": "en_IN",
    }
    payload.update(overrides)
    return RawReview.model_validate(payload)


def _quote(review_id: str, text: str = "Verification took two days.") -> Quote:
    return Quote(
        review_id=review_id,
        text=text,
        rating=2,
        store="play",
        date=date(2026, 8, 1),
    )


def _action(theme: str = "KYC") -> ActionIdea:
    return ActionIdea(
        title="Clarify KYC pending copy",
        rationale="Users do not know how long verification takes.",
        theme=theme,
        owner_hint="Product",
    )


def _themes() -> list[ThemeHighlight]:
    return [
        ThemeHighlight(name="KYC", summary="Verification delays"),
        ThemeHighlight(name="Payments", summary="UPI add-money failures"),
        ThemeHighlight(name="Withdrawals", summary="Payout timing"),
    ]


def _valid_pulse(*, quotes: list[Quote] | None = None, actions: list[ActionIdea] | None = None) -> PulseNote:
    return PulseNote(
        title="Groww Weekly Review Pulse — 2026-06-13 to 2026-08-22",
        themes=_themes(),
        quotes=quotes
        or [
            _quote("r1"),
            _quote("r2", "UPI failed at add money."),
            _quote("r3", "Withdrawal stuck for a day."),
        ],
        actions=actions or [_action("KYC"), _action("Payments"), _action("Withdrawals")],
        body="Top themes this window: KYC, payments, withdrawals.",
    )


def test_raw_review_round_trip():
    review = _raw_review()
    assert review.store == "play"
    assert review.rating == 4
    cloned = RawReview.model_validate(review.model_dump())
    assert cloned == review


def test_raw_review_rejects_author_field():
    with pytest.raises(ValidationError):
        RawReview.model_validate(
            {
                "store": "play",
                "review_id_source": "src-1",
                "rating": 4,
                "text": "ok",
                "date": date(2026, 8, 1),
                "author": "alice",
            }
        )


def test_raw_review_rejects_username_and_email_fields():
    base = {
        "store": "app_store",
        "review_id_source": "src-2",
        "rating": 5,
        "text": "ok",
        "date": date(2026, 8, 1),
    }
    with pytest.raises(ValidationError):
        RawReview.model_validate({**base, "username": "alice"})
    with pytest.raises(ValidationError):
        RawReview.model_validate({**base, "email": "alice@example.com"})


def test_raw_review_rating_must_be_one_to_five():
    with pytest.raises(ValidationError):
        _raw_review(rating=0)
    with pytest.raises(ValidationError):
        _raw_review(rating=6)


def test_pulse_note_accepts_exactly_three_quotes_and_actions():
    note = _valid_pulse()
    assert len(note.quotes) == 3
    assert len(note.actions) == 3
    assert len(note.themes) == 3


def test_pulse_note_rejects_four_quotes():
    quotes = [
        _quote("r1"),
        _quote("r2", "UPI failed."),
        _quote("r3", "Withdrawal stuck."),
        _quote("r4", "Onboarding unclear."),
    ]
    with pytest.raises(ValidationError):
        _valid_pulse(quotes=quotes)


def test_pulse_note_rejects_two_actions():
    with pytest.raises(ValidationError):
        _valid_pulse(actions=[_action("KYC"), _action("Payments")])


def test_pulse_note_rejects_duplicate_quote_review_ids():
    with pytest.raises(ValidationError):
        _valid_pulse(
            quotes=[
                _quote("r1"),
                _quote("r1", "other text"),
                _quote("r2", "UPI failed."),
            ]
        )


def test_pulse_state_rejects_more_than_five_clusters():
    window = DateWindow(start_date=date(2026, 6, 13), end_date=date(2026, 8, 22))
    product = ProductInfo(
        name="Groww",
        android_id="com.nextbillion.groww",
        ios_id="PLACEHOLDER",
        locale="en_IN",
    )
    clusters = [
        ThemeCluster(
            name=f"t{i}",
            review_ids=["r1"],
            count=1,
            avg_rating=3.0,
            severity="low",
        )
        for i in range(6)
    ]
    with pytest.raises(ValidationError):
        PulseState(run_id="run-1", window=window, product=product, clusters=clusters)
