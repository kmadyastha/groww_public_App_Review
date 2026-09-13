"""Phase 7 live MCP smoke (eval E7-03 … E7-05). Skipped unless PULSE_MCP=1."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from pulse.config import load_config
from pulse.graph import IntelligenceHooks
from pulse.run import initial_state, run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
WINDOW_END = date(2026, 9, 5)


pytestmark = [
    pytest.mark.live_mcp,
    pytest.mark.skipif(
        os.environ.get("PULSE_MCP") != "1",
        reason="set PULSE_MCP=1 for live Docs/Gmail MCP smoke",
    ),
]


def test_live_mcp_creates_doc_and_unsent_draft(tmp_path):
    """Requires a real McpInvoker injected by the operator environment.

    Cursor plugins authenticate in the IDE. This test documents the live
    contract; CI without PULSE_MCP=1 skips it.
    """
    pytest.skip("live Cursor Gmail/Drive plugins are not reachable from pytest CLI")
    config = load_config()
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        snapshot_dir=tmp_path,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase7-live"),
        hooks=IntelligenceHooks(),
    )
    assert result.doc is not None
    assert "Groww Weekly Review Pulse" in (result.pulse.title if result.pulse else "")
    assert result.email is not None
    assert result.email.draft_id
    assert result.status == "published"
