"""Phase 7 MCP allow-list (eval E7-01, E7-02). No live Google."""

from __future__ import annotations

from pathlib import Path

from pulse.mcp_tools import (
    bind_tools,
    is_send_tool,
    load_mcp_config,
)

SRC = Path(__file__).resolve().parents[1] / "src"
REPO = Path(__file__).resolve().parents[1]


def test_bind_tools_drops_send_and_keeps_draft_and_doc():
    offered = [
        "search_files",
        "create_file",
        "trash_file",
        "create_draft",
        "send_message",
        "forward",
        "reply",
        "messages.send",
        "list_drafts",
        "get_thread",
    ]
    bound = bind_tools(offered)
    assert "create_draft" in bound
    assert "create_file" in bound
    assert "search_files" in bound
    for name in bound:
        assert not is_send_tool(name)
    assert "send_message" not in bound
    assert "forward" not in bound
    assert "reply" not in bound
    assert "messages.send" not in bound
    assert "list_drafts" not in bound


def test_mcp_yaml_send_is_opt_in_never_forward():
    cfg = load_mcp_config()
    allow = {str(item) for item in cfg.get("allow") or []}
    allow_send = {str(item) for item in cfg.get("allow_send") or []}
    never = {str(item).lower() for item in cfg.get("never_bind") or []}
    assert "create_draft" in allow
    assert "create_file" in allow
    assert "send_message" not in allow
    assert "gmail_send_email" not in allow
    assert "send_message" in allow_send
    assert "gmail_send_email" not in allow_send
    assert "forward" in never
    assert "reply" in never
    bound = bind_tools(list(allow) + list(allow_send) + list(never))
    assert "send_message" not in bound
    assert "gmail_send_email" not in bound
    assert all(not is_send_tool(name) for name in bound)
    sent = bind_tools(list(allow) + list(allow_send) + list(never), allow_send=True)
    assert "send_message" in sent
    assert "forward" not in sent
    assert "reply" not in sent


def test_bind_tools_allow_send_keeps_send_message_not_forward():
    offered = [
        "create_draft",
        "send_message",
        "forward",
        "reply",
        "google_docs_append_content",
    ]
    assert "send_message" not in bind_tools(offered)
    bound = bind_tools(offered, allow_send=True)
    assert "send_message" in bound
    assert "google_docs_append_content" not in bound
    assert "forward" not in bound
    assert "reply" not in bound


def test_src_has_no_google_rest_or_oauth_client():
    forbidden = (
        "googleapis.com",
        "googleapiclient",
        "google.oauth",
        "google_auth",
        "docs.google.com/feeds",
    )
    allowed = {"src/pulse/mail_gmail.py"}
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{rel}: {token}")
    assert hits == []
