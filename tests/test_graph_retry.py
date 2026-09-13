"""Phase 5 graph retry (eval E5-06, E5-07). No live Groq / MCP."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pulse.config import load_config
from pulse.graph import IntelligenceHooks
from pulse.run import initial_state, run
from pulse.write import write_pulse_note

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW_END = date(2026, 9, 5)


@pytest.fixture(autouse=True)
def _no_live_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PULSE_MCP", raising=False)


def _start(config):
    return initial_state(config, weeks=10, end=WINDOW_END, run_id="phase5-retry")


def _run(*, visited: list[str], hooks: IntelligenceHooks, max_write_attempts: int = 3):
    config = load_config()
    return run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        visited=visited,
        state=_start(config),
        hooks=hooks,
        max_write_attempts=max_write_attempts,
    )


def test_invalid_pulse_retries_write_and_skips_mcp_until_valid():
    calls = {"n": 0}

    def flaky_writer(**kwargs):
        calls["n"] += 1
        note = write_pulse_note(**kwargs)
        if calls["n"] == 1:
            return note.model_copy(update={"body": note.body.rstrip() + "\nalice@example.com\n"})
        return note

    visited: list[str] = []
    result = _run(visited=visited, hooks=IntelligenceHooks(writer=flaky_writer))
    assert calls["n"] == 2
    assert visited.count("WritePulse") == 2
    assert visited.count("ValidatePulse") == 2
    assert "PublishDoc" in visited
    first_validate = visited.index("ValidatePulse")
    second_write = visited.index("WritePulse", first_validate)
    second_validate = visited.index("ValidatePulse", second_write)
    publish = visited.index("PublishDoc")
    assert first_validate < second_write < second_validate < publish
    assert "PublishDoc" not in visited[:second_write]
    assert result.status == "ready"
    assert result.validation_passed is True
    assert result.doc is None
    assert result.email is None
    assert "alice@example.com" not in (result.pulse.body if result.pulse else "")


def test_after_n_write_failures_graph_stops_without_publish():
    def always_email(**kwargs):
        note = write_pulse_note(**kwargs)
        return note.model_copy(update={"body": note.body.rstrip() + "\nalice@example.com\n"})

    visited: list[str] = []
    result = _run(
        visited=visited,
        hooks=IntelligenceHooks(writer=always_email),
        max_write_attempts=2,
    )
    assert visited.count("WritePulse") == 2
    assert visited.count("ValidatePulse") == 2
    assert "PublishDoc" not in visited
    assert "DraftEmail" not in visited
    assert result.status == "failed"
    assert result.validation_passed is False
    assert result.errors
    assert any("pii:" in item for item in result.errors)
    assert result.doc is None
    assert result.email is None


def test_quote_failure_retries_select_quotes_then_write():
    calls = {"n": 0}

    def paraphrase_once(**kwargs):
        calls["n"] += 1
        note = write_pulse_note(**kwargs)
        if calls["n"] == 1:
            original = note.quotes[0].text
            body = note.body.replace(original, "KYC is slow and confusing overall")
            return note.model_copy(update={"body": body})
        return note

    visited: list[str] = []
    result = _run(visited=visited, hooks=IntelligenceHooks(writer=paraphrase_once))
    assert calls["n"] == 2
    assert visited.count("SelectQuotes") == 2
    assert visited.count("WritePulse") == 2
    first_validate = visited.index("ValidatePulse")
    assert visited[first_validate + 1] == "SelectQuotes"
    assert "PublishDoc" in visited
    assert result.status == "ready"
    assert result.validation_passed is True
    assert result.doc is None
