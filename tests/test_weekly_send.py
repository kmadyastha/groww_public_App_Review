"""Instructor addendum: operator-only send via this project's Gmail plugin."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from pulse.config import load_config
from pulse.ingest.common import IST
from pulse.mcp_tools import McpDeliveryError, send_operator_email
from pulse.schedule import next_monday_0900
from pulse.schemas import PulseNote


def _note() -> PulseNote:
    return PulseNote(
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


class _SendFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def list_tool_names(self) -> list[str]:
        return ["send_message", "forward", "reply"]

    def invoke(self, tool_name: str, arguments: dict) -> dict:
        assert tool_name == "send_message"
        self.calls.append((tool_name, arguments))
        return {"id": "msg-1"}


def test_send_refuses_non_operator_recipient():
    fake = _SendFake()
    with pytest.raises(McpDeliveryError, match="operator.email"):
        send_operator_email(
            _note(),
            to="other@example.com",
            operator_email="karthik.katu@gmail.com",
            doc_url=None,
            invoker=fake,
        )
    assert fake.calls == []


def test_send_to_operator_only():
    fake = _SendFake()
    operator = load_config().operator.email
    ref = send_operator_email(
        _note(),
        to=operator,
        operator_email=operator,
        doc_url="https://docs.google.com/document/d/x/edit",
        invoker=fake,
    )
    assert ref.sent is True
    assert ref.message_id == "msg-1"
    name, args = fake.calls[0]
    assert name == "send_message"
    assert args["to"] == [operator]


def test_monday_0900_same_morning_waits_until_nine():
    now = datetime(2026, 9, 14, 8, 59, tzinfo=IST)  # Monday
    target = next_monday_0900(now)
    assert target == datetime(2026, 9, 14, 9, 0, tzinfo=IST)


def test_monday_0900_after_nine_is_next_week():
    now = datetime(2026, 9, 14, 9, 0, 1, tzinfo=IST)
    target = next_monday_0900(now)
    assert target == datetime(2026, 9, 21, 9, 0, tzinfo=IST)


def test_saturday_night_targets_next_monday():
    now = datetime(2026, 9, 12, 23, 0, tzinfo=IST)
    target = next_monday_0900(now)
    assert target.weekday() == 0
    assert target.hour == 9
    assert target.minute == 0
    assert target.date() == date(2026, 9, 14)
