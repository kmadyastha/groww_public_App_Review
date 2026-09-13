"""MCP-first Docs + Gmail. Never Google REST. Send is operator-only and opt-in."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import yaml

from pulse.prompts import pulse_title
from pulse.schemas import DateWindow, DocRef, EmailRef, ProductInfo, PulseNote

logger = logging.getLogger("pulse.mcp")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MCP_CONFIG = _REPO_ROOT / "config" / "mcp.yaml"

DOC_MIME = "application/vnd.google-apps.document"
TEXT_MIME = "text/plain"

DOC_CAPABILITIES = frozenset(
    {
        "search_files",
        "create_file",
        "trash_file",
        "create_document",
        "docs_create",
    }
)
DRAFT_CAPABILITIES = frozenset({"create_draft", "gmail_create_draft"})
SEND_CAPABILITIES = frozenset({"send_message", "gmail_send_email"})
ALLOWLIST = DOC_CAPABILITIES | DRAFT_CAPABILITIES

_TOOL_ALIASES = {
    "create_draft": ("create_draft", "gmail_create_draft"),
    "gmail_create_draft": ("gmail_create_draft", "create_draft"),
    "send_message": ("send_message", "gmail_send_email"),
    "gmail_send_email": ("gmail_send_email", "send_message"),
    "create_file": ("create_file",),
    "search_files": ("search_files",),
    "trash_file": ("trash_file",),
}

_SEND_MARKERS = (
    "send_message",
    "send_email",
    "send_mail",
    "messages.send",
    "gmail.send",
)
_SEND_EXACT = frozenset({"send", "forward", "reply"})


class McpInvoker(Protocol):
    def list_tool_names(self) -> Sequence[str]: ...

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any: ...


DocPublisher = Callable[[PulseNote, DateWindow, ProductInfo], DocRef]
DraftCreator = Callable[[PulseNote, str, str | None], EmailRef]


class McpDeliveryError(RuntimeError):
    """Docs or Gmail MCP call failed after the pulse was already validated."""


def mcp_enabled() -> bool:
    flag = (os.environ.get("PULSE_MCP") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def load_mcp_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_MCP_CONFIG
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise McpDeliveryError("config/mcp.yaml must be a mapping")
    return raw


def _norm_tool(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def is_send_tool(name: str) -> bool:
    lowered = _norm_tool(name)
    if lowered in _SEND_EXACT:
        return True
    if lowered.endswith(".send") or lowered.endswith("_send"):
        return True
    return any(marker in lowered for marker in _SEND_MARKERS)


def bind_tools(names: Sequence[str], *, allow_send: bool = False) -> list[str]:
    """Allow-list Doc + draft tools. Operator send is opt-in (`allow_send`)."""
    allowed = set(ALLOWLIST)
    if allow_send:
        allowed |= SEND_CAPABILITIES
    bound: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = _norm_tool(name)
        leaf = key.rsplit(".", 1)[-1]
        if leaf in {"forward", "reply"} or key in {"forward", "reply"}:
            continue
        if not allow_send and is_send_tool(name):
            continue
        if leaf not in allowed and key not in allowed:
            continue
        if name not in seen:
            bound.append(name)
            seen.add(name)
    return bound


def pulse_doc_title(note: PulseNote, window: DateWindow, product: ProductInfo) -> str:
    if note.title.strip():
        return note.title.strip()
    return pulse_title(product, window)


def _as_mapping(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        dumped = payload.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(payload, "content"):
        return _as_mapping(payload.content)
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _first_file(payload: Any) -> dict[str, Any]:
    data = _as_mapping(payload)
    if data.get("id") or data.get("fileId"):
        return data
    for key in ("files", "items", "results"):
        rows = data.get(key)
        if isinstance(rows, list) and rows:
            row = rows[0]
            return row if isinstance(row, dict) else _as_mapping(row)
    nested = data.get("file")
    if isinstance(nested, dict):
        return nested
    return data


def _doc_ref(payload: Any) -> DocRef:
    data = _first_file(payload)
    file_id = str(data.get("id") or data.get("fileId") or data.get("documentId") or "").strip()
    if not file_id:
        raise McpDeliveryError("Docs MCP did not return a document id")
    url = str(
        data.get("webViewLink")
        or data.get("url")
        or data.get("alternateLink")
        or f"https://docs.google.com/document/d/{file_id}/edit"
    )
    return DocRef(document_id=file_id, url=url)


def _draft_ref(payload: Any) -> EmailRef:
    data = _as_mapping(payload)
    nested = data.get("draft")
    if isinstance(nested, dict):
        data = nested
    draft_id = str(data.get("id") or data.get("draftId") or data.get("draft_id") or "").strip()
    if not draft_id:
        raise McpDeliveryError("Gmail MCP did not return a draft id")
    return EmailRef(draft_id=draft_id)


def _require_bound(invoker: McpInvoker, name: str, *, allow_send: bool = False) -> str:
    aliases = _TOOL_ALIASES.get(_norm_tool(name), (_norm_tool(name),))
    bound = bind_tools(list(invoker.list_tool_names()), allow_send=allow_send)
    for alias in aliases:
        for item in bound:
            leaf = _norm_tool(item).rsplit(".", 1)[-1]
            if leaf == alias or _norm_tool(item) == alias:
                if is_send_tool(item) and not allow_send:
                    raise McpDeliveryError(f"refusing to bind send-mail tool {item}")
                return item
    raise McpDeliveryError(f"MCP tool {name} is not bound")


def _escape_title(title: str) -> str:
    return title.replace("\\", "\\\\").replace("'", "\\'")


def pulse_mail_body(note: PulseNote, doc_url: str | None) -> str:
    body = note.body.strip()
    if doc_url:
        body = f"{body}\n\nGoogle Doc: {doc_url}\n"
    return body


def publish_doc_via_mcp(
    note: PulseNote,
    window: DateWindow,
    product: ProductInfo,
    *,
    invoker: McpInvoker,
) -> DocRef:
    title = pulse_doc_title(note, window, product)
    bound = bind_tools(list(invoker.list_tool_names()))
    if any(is_send_tool(name) for name in bound):
        raise McpDeliveryError("send-mail tools leaked into the allow-list")
    return _publish_via_create_file(note, title, invoker)


def _publish_via_create_file(note: PulseNote, title: str, invoker: McpInvoker) -> DocRef:
    search_name = None
    try:
        search_name = _require_bound(invoker, "search_files")
    except McpDeliveryError:
        search_name = None
    if search_name:
        query = (
            f"title = '{_escape_title(title)}' and "
            f"mimeType = '{DOC_MIME}'"
        )
        found = invoker.invoke(
            search_name,
            {"query": query, "pageSize": 5, "excludeContentSnippets": True},
        )
        existing = _first_file(found)
        existing_id = str(existing.get("id") or existing.get("fileId") or "").strip()
        if existing_id:
            try:
                trash_name = _require_bound(invoker, "trash_file")
                invoker.invoke(trash_name, {"fileId": existing_id})
            except McpDeliveryError:
                logger.warning("Existing Doc %s left in place; creating a new file", existing_id)
    create_name = _require_bound(invoker, "create_file")
    raw = invoker.invoke(
        create_name,
        {
            "title": title,
            "textContent": note.body,
            "contentMimeType": TEXT_MIME,
        },
    )
    return _doc_ref(raw)


def create_draft_via_mcp(
    note: PulseNote,
    *,
    to: str,
    doc_url: str | None,
    invoker: McpInvoker,
) -> EmailRef:
    assert_no_send_bound(invoker.list_tool_names())
    draft_name = _require_bound(invoker, "create_draft")
    raw = invoker.invoke(
        draft_name,
        {
            "to": [to],
            "subject": note.title,
            "body": pulse_mail_body(note, doc_url),
        },
    )
    return _draft_ref(raw)


def send_operator_email(
    note: PulseNote,
    *,
    to: str,
    operator_email: str,
    doc_url: str | None,
    invoker: McpInvoker,
) -> EmailRef:
    """Send to the configured operator only. Never a bulk/list send."""
    if to.strip().lower() != operator_email.strip().lower():
        raise McpDeliveryError("refusing to send mail to anyone except operator.email")
    send_name = _require_bound(invoker, "send_message", allow_send=True)
    body = pulse_mail_body(note, doc_url)
    raw = invoker.invoke(
        send_name,
        {
            "to": [to],
            "subject": note.title,
            "body": body,
        },
    )
    data = _as_mapping(raw)
    nested = data.get("message") if isinstance(data.get("message"), dict) else data
    message_id = str(nested.get("id") or nested.get("messageId") or "sent").strip()
    return EmailRef(draft_id="", message_id=message_id, sent=True)


def assert_no_send_bound(names: Sequence[str]) -> None:
    bound = bind_tools(names, allow_send=False)
    leaked = [name for name in bound if is_send_tool(name)]
    if leaked:
        raise McpDeliveryError(f"send-mail tools must not be bound: {leaked}")
