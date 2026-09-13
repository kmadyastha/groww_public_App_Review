"""Phase 5 validator (eval E5-01 … E5-05, E5-08). No Groq / MCP."""

from __future__ import annotations

from datetime import date

from pulse.actions import propose_actions
from pulse.quotes import heuristic_nominator, select_quotes
from pulse.schemas import (
    DateWindow,
    ProductInfo,
    PulseNote,
    Quote,
    SanitizedReview,
    ThemeCluster,
    ThemeHighlight,
)
from pulse.validate import MAX_PULSE_WORDS, validate_pulse
from pulse.write import word_count, write_pulse_note

RSS_BODY = "The e-KYC camera step failed twice during account setup."
WINDOW = DateWindow(start_date=date(2026, 6, 27), end_date=date(2026, 9, 5))
PRODUCT = ProductInfo(
    name="Groww",
    android_id="com.nextbillion.groww",
    ios_id="1404871703",
    locale="en_IN",
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


def _cluster(name: str, reviews: list[SanitizedReview]) -> ThemeCluster:
    ratings = [row.rating for row in reviews]
    return ThemeCluster(
        name=name,
        review_ids=[row.review_id for row in reviews],
        count=len(reviews),
        avg_rating=round(sum(ratings) / len(ratings), 2),
        severity="high",
        play_count=sum(1 for row in reviews if row.store == "play"),
        app_store_count=sum(1 for row in reviews if row.store == "app_store"),
    )


def _corpus() -> tuple[list[SanitizedReview], list[ThemeCluster]]:
    reviews = [
        _review(review_id="play-kyc", text="Verification has been pending for two full days."),
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


def _valid_note() -> tuple[PulseNote, list[SanitizedReview], list[ThemeCluster]]:
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
    return note, reviews, clusters


def _report_text(note: PulseNote, reviews, clusters, extra_needles=()) -> str:
    return " ".join(validate_pulse(note, reviews, clusters, extra_needles=extra_needles).errors)


def test_word_count_is_whitespace_split():
    assert word_count("Groww weekly pulse") == 3
    assert word_count("a  b\tc\nd") == 4
    assert MAX_PULSE_WORDS == 250


def test_valid_pulse_passes():
    note, reviews, clusters = _valid_note()
    report = validate_pulse(note, reviews, clusters)
    assert report.ok, report.errors
    assert word_count(note.body) <= 250


def test_exactly_250_words_passes():
    note, reviews, clusters = _valid_note()
    extra = 250 - word_count(note.body)
    if extra > 0:
        body = note.body.rstrip() + "\n" + " ".join(["pad"] * extra) + "\n"
        note = note.model_copy(update={"body": body})
    assert word_count(note.body) == 250
    report = validate_pulse(note, reviews, clusters)
    assert report.ok, report.errors


def test_251_words_fails():
    note, reviews, clusters = _valid_note()
    extra = 251 - word_count(note.body)
    body = note.body.rstrip() + "\n" + " ".join(["pad"] * extra) + "\n"
    note = note.model_copy(update={"body": body})
    assert word_count(note.body) == 251
    report = validate_pulse(note, reviews, clusters)
    assert not report.ok
    assert any(item.startswith("length:") for item in report.errors)


def test_missing_heading_fails():
    note, reviews, clusters = _valid_note()
    body = note.body.replace("1. Top 3 themes", "Themes this week")
    note = note.model_copy(update={"body": body})
    blob = _report_text(note, reviews, clusters)
    assert "shape:" in blob
    assert "Top 3 themes" in blob


def test_prose_quote_count_mismatch_fails():
    note, reviews, clusters = _valid_note()
    lines = note.body.splitlines()
    dropped = False
    out: list[str] = []
    for line in lines:
        if (not dropped) and line.strip().startswith("-") and "What users said" not in line and "“" in line:
            dropped = True
            continue
        out.append(line)
    note = note.model_copy(update={"body": "\n".join(out) + "\n"})
    report = validate_pulse(note, reviews, clusters)
    assert not report.ok
    assert any("3 quote bullets" in item or "locked text is missing" in item for item in report.errors)


def test_paraphrased_quote_in_body_fails():
    note, reviews, clusters = _valid_note()
    original = note.quotes[0].text
    body = note.body.replace(original, "KYC is slow and confusing overall")
    note = note.model_copy(update={"body": body})
    report = validate_pulse(note, reviews, clusters)
    assert not report.ok
    assert report.needs_quote_retry
    assert any(item.startswith("quote:") for item in report.errors)


def test_planted_email_fails():
    note, reviews, clusters = _valid_note()
    body = note.body.rstrip() + "\nContact alice@example.com for details.\n"
    note = note.model_copy(update={"body": body})
    blob = _report_text(note, reviews, clusters)
    assert "pii:" in blob
    assert "email" in blob


def test_leaked_rss_author_fails():
    note, reviews, clusters = _valid_note()
    body = note.body.rstrip() + "\nQuoted ios.user from the feed.\n"
    blob = _report_text(note.model_copy(update={"body": body}), reviews, clusters)
    assert "pii:" in blob
    assert "ios.user" in blob


def test_leaked_itunes_review_id_fails():
    note, reviews, clusters = _valid_note()
    body = note.body.rstrip() + "\nSource ios-rss-1 should never appear.\n"
    blob = _report_text(note.model_copy(update={"body": body}), reviews, clusters)
    assert "pii:" in blob


def test_extra_theme_in_prose_fails():
    note, reviews, clusters = _valid_note()
    body = note.body.replace(
        "1. Top 3 themes",
        "1. Top 3 themes\n   - Statements — users like PDF exports",
    )
    report = validate_pulse(note.model_copy(update={"body": body}), reviews, clusters)
    assert not report.ok
    assert any(item.startswith("theme:") or "4 theme bullets" in item or "3 theme bullets" in item for item in report.errors)


def test_theme_not_in_clusters_fails():
    note, reviews, clusters = _valid_note()
    themes = list(note.themes)
    themes[0] = ThemeHighlight(name="Onboarding", summary="Invented bucket")
    report = validate_pulse(note.model_copy(update={"themes": themes}), reviews, clusters)
    assert not report.ok
    assert any("Onboarding" in item for item in report.errors)


def test_name_like_quote_fails():
    note, reviews, clusters = _valid_note()
    quotes = list(note.quotes)
    quotes[0] = Quote(
        review_id=quotes[0].review_id,
        text="Pradeep Sholapurkar",
        rating=quotes[0].rating,
        store=quotes[0].store,
        date=quotes[0].date,
    )
    body = note.body.replace(note.quotes[0].text, "Pradeep Sholapurkar")
    report = validate_pulse(note.model_copy(update={"quotes": quotes, "body": body}), reviews, clusters)
    assert not report.ok
    assert report.needs_quote_retry


def test_missing_pulse_fails():
    _note, reviews, clusters = _valid_note()
    report = validate_pulse(None, reviews, clusters)
    assert not report.ok
    assert report.errors[0].startswith("shape:")
