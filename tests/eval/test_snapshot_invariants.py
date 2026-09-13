"""Phase 6 local snapshot invariants (eval E6-01 … E6-06). No Groq / MCP."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pulse.config import load_config
from pulse.graph import SKIP_DRAFT_MCP, SKIP_PUBLISH_MCP
from pulse.privacy import leak_labels
from pulse.run import initial_state, main, run
from pulse.snapshot import REPO_ROOT, snapshot_filename
from pulse.validate import HEADING_ACTIONS, HEADING_QUOTES, HEADING_THEMES, quoted_snippets
from pulse.write import word_count

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
WINDOW_END = date(2026, 9, 5)
LIVE_PLAY = REPO_ROOT / "data" / "raw" / "play_reviews.json"
LIVE_IOS = REPO_ROOT / "data" / "raw" / "app_store_reviews.json"


@pytest.fixture(autouse=True)
def _no_live_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PULSE_MCP", raising=False)


def _fixture_run(snapshot_dir: Path, *, visited: list[str] | None = None):
    config = load_config()
    return run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        visited=visited,
        snapshot_dir=snapshot_dir,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase6-fixture"),
    )


def _assert_snapshot_invariants(result, snapshot_dir: Path):
    assert result.status == "ready"
    assert result.validation_passed is True
    assert result.doc is None
    assert result.email is None
    assert result.pulse is not None
    assert SKIP_PUBLISH_MCP in result.warnings
    assert SKIP_DRAFT_MCP in result.warnings

    assert result.snapshot_path
    path = Path(result.snapshot_path)
    assert path.is_file()
    assert path.parent.resolve() == snapshot_dir.resolve()
    assert path.name == snapshot_filename(result.run_id)

    text = path.read_text(encoding="utf-8")
    assert text == result.pulse.body.strip() + "\n"
    assert HEADING_THEMES.search(text)
    assert HEADING_QUOTES.search(text)
    assert HEADING_ACTIONS.search(text)
    assert len(result.pulse.themes) == 3
    assert len(result.pulse.quotes) == 3
    assert len(result.pulse.actions) == 3
    assert word_count(text) <= 250
    assert leak_labels(text) == []
    assert "ios.user" not in text
    assert "ios-rss-1" not in text
    assert "alice@example.com" not in text

    snippets = quoted_snippets(text)
    assert len(snippets) == 3
    review_blobs = [f"{row.title or ''} {row.text}" for row in result.reviews]
    for snippet in snippets:
        assert any(snippet in blob for blob in review_blobs)
    for quote in result.pulse.quotes:
        assert quote.text in text
        assert any(quote.text in (row.text or "") or (row.title and quote.text in row.title) for row in result.reviews)


def test_fixture_snapshot_invariants(tmp_path):
    visited: list[str] = []
    result = _fixture_run(tmp_path, visited=visited)
    _assert_snapshot_invariants(result, tmp_path)
    assert "PublishDoc" in visited
    assert "DraftEmail" in visited
    assert result.status != "published"


def test_cli_prints_run_id_themes_words_and_snapshot(tmp_path, capsys):
    code = main(
        [
            "--play",
            str(FIXTURES / "reviews_sample.json"),
            "--app-store",
            str(FIXTURES / "app_store_rss.json"),
            "--end-date",
            "2026-09-05",
            "--snapshot-dir",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    out = captured.out
    assert code == 0
    assert "run_id=" in out
    assert "status=ready" in out
    assert "themes=" in out
    assert "words=" in out
    assert "snapshot=" in out
    snap = next(line for line in out.splitlines() if line.startswith("snapshot="))
    path = Path(snap.split("=", 1)[1])
    assert path.is_file()
    assert path.parent.resolve() == tmp_path.resolve()


def test_failed_run_does_not_write_snapshot(tmp_path):
    config = load_config()
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_all_pii.json",
        raw_dir=tmp_path,
        fetch_public=False,
        snapshot_dir=tmp_path / "snaps",
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase6-fail"),
    )
    assert result.status == "failed"
    assert result.snapshot_path is None
    assert list(tmp_path.rglob("*.md")) == []
    assert SKIP_PUBLISH_MCP not in result.warnings


@pytest.mark.skipif(not (LIVE_PLAY.is_file() and LIVE_IOS.is_file()), reason="live data/raw export missing")
def test_live_raw_export_snapshot_invariants(tmp_path):
    config = load_config()
    result = run(
        config=config,
        raw_dir=LIVE_PLAY.parent,
        fetch_public=False,
        snapshot_dir=tmp_path,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase6-raw"),
    )
    _assert_snapshot_invariants(result, tmp_path)
    assert result.pulse is not None
    stores = {row.store for row in result.reviews}
    assert "play" in stores
    names = " ".join(row.name.lower() for row in result.pulse.themes)
    assert "statements" not in names
    assert "onboarding" not in names
    ratings = [quote.rating for quote in result.pulse.quotes]
    play_low = any(
        quote.store == "play" and quote.rating <= 2 for quote in result.pulse.quotes
    )
    if any(row.store == "play" and row.rating <= 2 for row in result.reviews):
        assert play_low or min(ratings) <= 3
