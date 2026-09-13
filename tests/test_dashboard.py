"""Dashboard payload and subscriber list (no live Gmail)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pulse.config import load_config
from pulse.dashboard import (
    build_dashboard,
    cache_is_usable,
    pulse_note_from_dashboard,
    sentiment_of,
    write_dashboard,
)
from pulse.mail_gmail import pulse_email_bodies
from pulse.report_pdf import render_pulse_pdf
from pulse.run import initial_state, run
from pulse.subscribers import SubscriberError, normalize_email, upsert_subscriber

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW_END = date(2026, 9, 5)


def _result(tmp_path):
    config = load_config()
    return run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        snapshot_dir=tmp_path,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="dash-test"),
        send_email=False,
    )


def test_sentiment_buckets():
    assert sentiment_of(5) == "positive"
    assert sentiment_of(4) == "positive"
    assert sentiment_of(3) == "neutral"
    assert sentiment_of(1) == "negative"


def test_dashboard_from_fixture_run(tmp_path):
    result = _result(tmp_path)
    dash = build_dashboard(result, weeks=10)
    assert dash["overview"]["total_reviews"] == len(result.reviews)
    assert 1 <= dash["overview"]["avg_rating"] <= 5
    assert set(dash["overview"]["sentiment"]) == {"positive", "negative", "neutral"}
    assert dash["pulse"] is not None
    assert len(dash["pulse"]["themes"]) == 3
    assert len(dash["pulse"]["actions"]) == 3
    assert dash["iso_week"].startswith("W")
    assert all("theme" in row and "sentiment" in row for row in dash["reviews"])
    path = write_dashboard(result, weeks=10, directory=tmp_path)
    assert path.is_file()


def test_seed_cache_is_not_usable_when_raw_export_exists():
    payload = {
        "run_id": "ui-seed",
        "weeks": 10,
        "source": "seed",
        "overview": {"total_reviews": 6},
    }
    assert cache_is_usable(payload, 10) is False
    live = {
        "run_id": "abc",
        "weeks": 10,
        "source": "live",
        "overview": {"total_reviews": 1467},
    }
    assert cache_is_usable(live, 10) is True
    assert cache_is_usable(live, 8) is False


def test_pulse_pdf_is_pdf(tmp_path):
    result = _result(tmp_path)
    dash = build_dashboard(result, weeks=10)
    pdf = render_pulse_pdf(dash)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_email_body_includes_quotes_when_asked(tmp_path):
    result = _result(tmp_path)
    assert result.pulse is not None
    subject, with_quotes = pulse_email_bodies(result.pulse, include_quotes=True)
    _, without = pulse_email_bodies(result.pulse, include_quotes=False)
    assert "Groww" in subject
    assert result.pulse.quotes[0].text in with_quotes
    assert result.pulse.quotes[0].text not in without
    assert result.pulse.themes[0].name in without


def test_subscriber_upsert(tmp_path):
    path = tmp_path / "subs.json"
    row = upsert_subscriber("  Karthik.Katu@gmail.com ", include_quotes=True, path=path)
    assert row["email"] == "karthik.katu@gmail.com"
    again = upsert_subscriber("karthik.katu@gmail.com", include_quotes=False, path=path)
    assert again["include_quotes"] is False
    with pytest.raises(SubscriberError):
        normalize_email("not-an-email")


def test_pulse_note_from_dashboard(tmp_path):
    result = _result(tmp_path)
    assert result.pulse is not None
    dash = build_dashboard(result, weeks=10)
    note = pulse_note_from_dashboard(dash)
    assert note.title == result.pulse.title
    assert len(note.quotes) == 3
    assert note.quotes[0].text == dash["pulse"]["themes"][0]["quote"]


def test_subscribe_does_not_send_mail(monkeypatch):
    from fastapi.testclient import TestClient

    from pulse import server

    sent: list[str] = []
    monkeypatch.setattr(
        server,
        "upsert_subscriber",
        lambda email, include_quotes=True: {
            "email": email.lower().strip(),
            "include_quotes": include_quotes,
        },
    )
    monkeypatch.setattr(server, "load_subscribers", lambda: [{"email": "ops@example.com"}])
    monkeypatch.setattr(server, "gmail_configured", lambda: True)
    monkeypatch.setattr(server, "send_pulse", lambda *args, **kwargs: sent.append("x") or "id")

    response = TestClient(server.app).post(
        "/api/subscribe",
        json={"email": "ops@example.com", "include_quotes": True, "weeks": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is False
    assert body["email"] == "ops@example.com"
    assert sent == []


def test_send_now_emails_without_subscribing(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from pulse import server

    dash = build_dashboard(_result(tmp_path), weeks=10)
    called: dict[str, object] = {}
    monkeypatch.setattr(server, "gmail_configured", lambda: True)
    monkeypatch.setattr(server, "ensure_insights", lambda weeks: dash)
    monkeypatch.setattr(server, "load_subscribers", lambda: [])
    monkeypatch.setattr(
        server,
        "upsert_subscriber",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("send now must not subscribe")),
    )

    def fake_send(note, to, include_quotes=True):
        called["to"] = to
        called["quotes"] = include_quotes
        called["title"] = note.title
        return "mid-1"

    monkeypatch.setattr(server, "send_pulse", fake_send)
    response = TestClient(server.app).post(
        "/api/mail/send",
        json={"email": "Now.Me@Example.com", "include_quotes": False, "weeks": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is True
    assert body["email"] == "now.me@example.com"
    assert called["to"] == "now.me@example.com"
    assert called["quotes"] is False


def test_send_now_requires_gmail(monkeypatch):
    from fastapi.testclient import TestClient

    from pulse import server

    monkeypatch.setattr(server, "gmail_configured", lambda: False)
    response = TestClient(server.app).post(
        "/api/mail/send",
        json={"email": "ops@example.com", "include_quotes": True, "weeks": 10},
    )
    assert response.status_code == 503
