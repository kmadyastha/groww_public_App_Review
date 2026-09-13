"""Phase 3–4 LangGraph: ingest, sanitize, intelligence (eval E3-01 … E4)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pulse.config import load_config
from pulse.graph import GRAPH_NODES, compile_pulse_graph
from pulse.run import initial_state, run
from pulse.schemas import GROW_APP_STORE_ID

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW_END = date(2026, 9, 5)


@pytest.fixture(autouse=True)
def _no_live_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PULSE_MCP", raising=False)


def _start(config):
    return initial_state(config, weeks=10, end=WINDOW_END, run_id="phase3-test")


def test_graph_compiles():
    compiled = compile_pulse_graph(fetch_public=False)
    assert callable(getattr(compiled, "invoke", None))
    nodes = getattr(compiled, "nodes", None)
    if nodes is not None:
        node_ids = set(nodes)
    else:
        node_ids = set(compiled.get_graph().nodes)
    assert set(GRAPH_NODES) <= node_ids


def test_fixture_run_fills_sanitized_reviews_from_both_stores():
    config = load_config()
    visited: list[str] = []
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        visited=visited,
        state=_start(config),
    )
    assert visited[:2] == ["LoadReviews", "SanitizePII"]
    assert "ClusterThemes" in visited
    assert "DraftEmail" in visited
    assert result.status == "ready"
    assert result.product.ios_id == GROW_APP_STORE_ID
    assert result.product.ios_id == "1404871703"
    stores = {row.store for row in result.reviews}
    assert stores == {"play", "app_store"}
    assert len(result.reviews) >= 4
    assert result.raw_reviews == []
    texts = " ".join(row.text for row in result.reviews)
    assert "e-KYC camera" in texts
    assert "ios.user" not in texts
    assert "ios-rss-1" not in texts
    assert "alice@example.com" not in texts
    assert "should-not-appear" not in texts
    assert 3 <= len(result.clusters) <= 5
    for row in result.reviews:
        dumped = row.model_dump()
        assert "author" not in dumped
        assert "review_id_source" not in dumped
        assert row.review_id != "ios-rss-1"
        assert row.review_id != "p-kyc-1"


def test_rss_metadata_entry_never_appears_in_state_reviews():
    config = load_config()
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        state=_start(config),
    )
    blob = " ".join(
        f"{row.title or ''} {row.text} {row.review_id}" for row in result.reviews
    )
    assert "https://itunes.apple.com/id1404871703" not in blob
    assert not any(
        (row.title or "") == "Groww" and "e-KYC" not in row.text for row in result.reviews
    )


def test_empty_input_fails_and_does_not_cluster(tmp_path):
    config = load_config()
    visited: list[str] = []
    result = run(
        config=config,
        raw_dir=tmp_path,
        fetch_public=False,
        visited=visited,
        state=_start(config),
    )
    assert result.status == "failed"
    assert result.reviews == []
    assert result.raw_reviews == []
    assert result.errors
    assert "ClusterThemes" not in visited
    assert "LoadReviews" in visited
    assert "SelectQuotes" not in visited


def test_all_dropped_after_sanitize_skips_cluster(tmp_path):
    config = load_config()
    visited: list[str] = []
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_all_pii.json",
        raw_dir=tmp_path,
        fetch_public=False,
        visited=visited,
        state=_start(config),
    )
    assert result.status == "failed"
    assert result.reviews == []
    assert "no reviews remaining after PII sanitization" in " ".join(result.errors)
    assert "ClusterThemes" not in visited
    assert "SanitizePII" in visited


def test_intelligence_nodes_fill_pulse_without_publishing():
    config = load_config()
    visited: list[str] = []
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        visited=visited,
        state=_start(config),
    )
    assert result.status == "ready"
    assert 3 <= len(result.clusters) <= 5
    assert result.pulse is not None
    assert len(result.pulse.themes) == 3
    assert len(result.pulse.quotes) == 3
    assert len(result.pulse.actions) == 3
    by_id = {row.review_id: row for row in result.reviews}
    for quote in result.pulse.quotes:
        assert quote.text in by_id[quote.review_id].text
        assert "ios.user" not in quote.text
        assert "ios-rss-1" not in quote.text
    names = {row.name for row in result.clusters}
    assert all(idea.theme in names for idea in result.pulse.actions)
    assert "1. Top 3 themes" in result.pulse.body
    assert "2. What users said (3 quotes)" in result.pulse.body
    assert "3. Three action ideas" in result.pulse.body
    assert result.doc is None
    assert result.email is None
    assert result.validation_passed is True
    assert visited == [
        "LoadReviews",
        "SanitizePII",
        "ClusterThemes",
        "SelectQuotes",
        "ProposeActions",
        "WritePulse",
        "ValidatePulse",
        "PublishDoc",
        "DraftEmail",
    ]
