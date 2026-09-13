"""Phase 7 graph MCP wiring with a fake invoker (no live Google)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pulse.config import load_config
from pulse.graph import IntelligenceHooks, SKIP_DRAFT_MCP, SKIP_PUBLISH_MCP
from pulse.mcp_tools import bind_tools, create_draft_via_mcp, publish_doc_via_mcp
from pulse.run import initial_state, run
from pulse.schemas import DateWindow, DocRef, EmailRef, ProductInfo, PulseNote

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WINDOW_END = date(2026, 9, 5)


class FakeMcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.existing: dict | None = None

    def list_tool_names(self) -> list[str]:
        return [
            "search_files",
            "create_file",
            "trash_file",
            "create_draft",
            "send_message",
            "forward",
            "reply",
        ]

    def invoke(self, tool_name: str, arguments: dict) -> dict:
        assert tool_name not in {"send_message", "forward", "reply"}
        self.calls.append((tool_name, arguments))
        if tool_name == "search_files":
            return {"files": [self.existing] if self.existing else []}
        if tool_name == "trash_file":
            self.existing = None
            return {}
        if tool_name == "create_file":
            return {
                "id": "doc-groww-1",
                "webViewLink": "https://docs.google.com/document/d/doc-groww-1/edit",
            }
        if tool_name == "create_draft":
            return {"id": "draft-groww-1"}
        if tool_name in {"gmail_send_email", "send_message"}:
            raise AssertionError("send tools must not be called unless send_email is set")
        raise AssertionError(f"unexpected tool {tool_name}")


class FakeSendMcp(FakeMcp):
    def invoke(self, tool_name: str, arguments: dict) -> dict:
        if tool_name == "send_message":
            assert arguments["to"] == ["karthik.katu@gmail.com"]
            self.calls.append((tool_name, arguments))
            return {"id": "msg-groww-1"}
        return super().invoke(tool_name, arguments)


def test_fake_invoker_never_exposes_send_in_bind_list():
    fake = FakeMcp()
    bound = bind_tools(fake.list_tool_names())
    assert "send_message" not in bound
    assert "create_draft" in bound


def test_graph_publishes_doc_and_draft_via_mcp_invoker(tmp_path):
    config = load_config()
    fake = FakeMcp()
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        snapshot_dir=tmp_path,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase7-mcp"),
        hooks=IntelligenceHooks(mcp_invoker=fake),
    )
    assert result.validation_passed is True
    assert result.doc is not None
    assert result.doc.document_id == "doc-groww-1"
    assert "docs.google.com" in result.doc.url
    assert result.email is not None
    assert result.email.draft_id == "draft-groww-1"
    assert result.status == "published"
    assert SKIP_PUBLISH_MCP not in result.warnings
    assert SKIP_DRAFT_MCP not in result.warnings
    names = [name for name, _ in fake.calls]
    assert "send_message" not in names
    assert "create_file" in names
    assert "create_draft" in names
    draft_args = next(args for name, args in fake.calls if name == "create_draft")
    assert draft_args["to"] == [config.operator.email]
    assert result.pulse is not None
    assert result.pulse.title in draft_args["subject"]
    assert result.pulse.body.strip() in draft_args["body"]
    assert result.doc.url in draft_args["body"]
    create_args = next(args for name, args in fake.calls if name == "create_file")
    assert create_args["title"] == result.pulse.title
    assert create_args["textContent"] == result.pulse.body


def test_hooks_publishers_without_invoker(tmp_path):
    config = load_config()

    def publish(note, window, product):
        del window, product
        return DocRef(
            document_id="hook-doc",
            url="https://docs.google.com/document/d/hook-doc/edit",
        )

    def draft(note, to, url):
        del note, to, url
        return EmailRef(draft_id="hook-draft")

    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        snapshot_dir=tmp_path,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase7-hooks"),
        hooks=IntelligenceHooks(doc_publisher=publish, draft_creator=draft),
    )
    assert result.status == "published"
    assert result.doc is not None and result.doc.document_id == "hook-doc"
    assert result.email is not None and result.email.draft_id == "hook-draft"


def test_publish_via_mcp_trashes_existing_title():
    fake = FakeMcp()
    fake.existing = {"id": "old-doc"}
    note = PulseNote(
        title="Groww Weekly Review Pulse — 2026-06-27 to 2026-09-05",
        themes=[
            {"name": "A", "summary": "a"},
            {"name": "B", "summary": "b"},
            {"name": "C", "summary": "c"},
        ],
        quotes=[
            {
                "review_id": "r1",
                "text": "quote one here",
                "rating": 1,
                "store": "play",
                "date": "2026-07-01",
            },
            {
                "review_id": "r2",
                "text": "quote two here",
                "rating": 2,
                "store": "play",
                "date": "2026-07-02",
            },
            {
                "review_id": "r3",
                "text": "quote three here",
                "rating": 3,
                "store": "app_store",
                "date": "2026-07-03",
            },
        ],
        actions=[
            {
                "title": "Fix one",
                "rationale": "Because users said so in reviews this week.",
                "theme": "A",
                "owner_hint": "Product",
            },
            {
                "title": "Fix two",
                "rationale": "Because users said so in reviews this week.",
                "theme": "B",
                "owner_hint": "Support",
            },
            {
                "title": "Fix three",
                "rationale": "Because users said so in reviews this week.",
                "theme": "C",
                "owner_hint": "Growth",
            },
        ],
        body="Groww Weekly Review Pulse — 2026-06-27 to 2026-09-05\n\n1. Top 3 themes\n",
    )
    window = DateWindow(start_date=date(2026, 6, 27), end_date=date(2026, 9, 5))
    product = ProductInfo(
        name="Groww",
        android_id="com.nextbillion.groww",
        ios_id="1404871703",
        locale="en_IN",
    )
    doc = publish_doc_via_mcp(note, window, product, invoker=fake)
    assert doc.document_id == "doc-groww-1"
    assert [name for name, _ in fake.calls] == ["search_files", "trash_file", "create_file"]
    email = create_draft_via_mcp(note, to="karthik.katu@gmail.com", doc_url=doc.url, invoker=fake)
    assert email.draft_id == "draft-groww-1"


def test_graph_sends_operator_email_when_flagged(tmp_path):
    config = load_config()
    fake = FakeSendMcp()
    result = run(
        config=config,
        play_path=FIXTURES / "reviews_sample.json",
        app_store_path=FIXTURES / "app_store_rss.json",
        fetch_public=False,
        snapshot_dir=tmp_path,
        state=initial_state(config, weeks=10, end=WINDOW_END, run_id="phase9-send"),
        hooks=IntelligenceHooks(mcp_invoker=fake),
        send_email=True,
    )
    assert result.validation_passed is True
    assert result.email is not None
    assert result.email.sent is True
    assert result.email.message_id == "msg-groww-1"
    names = [name for name, _ in fake.calls]
    assert "send_message" in names
    assert "create_draft" not in names
    assert "forward" not in names
