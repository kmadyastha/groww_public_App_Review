"""LangGraph pulse pipeline: ingest, sanitize, intelligence, local snapshot."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from pulse.actions import propose_actions as build_action_ideas
from pulse.cluster import cluster_reviews
from pulse.config import AppConfig, ConfigError, load_config
from pulse.ingest import IngestError, load_reviews
from pulse.llm import chat_model
from pulse.mcp_tools import (
    McpDeliveryError,
    create_draft_via_mcp,
    mcp_enabled,
    publish_doc_via_mcp,
    send_operator_email,
)
from pulse.privacy import sanitize_reviews
from pulse.quotes import QuoteLockError, select_quotes as lock_quotes
from pulse.snapshot import write_snapshot
from pulse.state import PulseState
from pulse.validate import MAX_WRITE_ATTEMPTS, validate_pulse
from pulse.write import write_pulse_note

logger = logging.getLogger("pulse.graph")

GRAPH_NODES = (
    "LoadReviews",
    "SanitizePII",
    "ClusterThemes",
    "SelectQuotes",
    "ProposeActions",
    "WritePulse",
    "ValidatePulse",
    "PublishDoc",
    "DraftEmail",
)

SKIP_PUBLISH_MCP = "PublishDoc skipped: MCP not enabled"
SKIP_DRAFT_MCP = "DraftEmail skipped: MCP not enabled"

AfterSanitize = Literal["ClusterThemes", "end"]
AfterQuotes = Literal["ProposeActions", "WritePulse", "end"]
AfterValidate = Literal["PublishDoc", "WritePulse", "SelectQuotes", "end"]
NodeFn = Callable[[PulseState], dict[str, Any]]


@dataclass
class IntelligenceHooks:
    """Optional test/production overrides. LLM is Groq-only when used."""

    assigner: Any | None = None
    nominator: Any | None = None
    action_builder: Any | None = None
    llm: Any | None = None
    writer: Any | None = None
    doc_publisher: Any | None = None
    draft_creator: Any | None = None
    mcp_invoker: Any | None = None


class GraphState(TypedDict, total=False):
    """LangGraph channel schema. Nodes validate through PulseState."""

    run_id: str
    window: Any
    product: Any
    reviews: list
    raw_reviews: list
    clusters: list
    quotes: list
    actions: list
    pulse: Any
    snapshot_path: str
    doc: Any
    email: Any
    errors: list
    warnings: list
    status: str
    write_attempts: int
    validation_passed: bool


def coerce_state(state: PulseState | dict[str, Any] | Any) -> PulseState:
    if isinstance(state, PulseState):
        return state
    if hasattr(state, "model_dump") and not isinstance(state, dict):
        return PulseState.model_validate(state.model_dump())
    return PulseState.model_validate(dict(state))


def _store_mix_warnings(raw: Sequence[Any]) -> list[str]:
    play_n = sum(1 for row in raw if row.store == "play")
    ios_n = sum(1 for row in raw if row.store == "app_store")
    warnings: list[str] = []
    if play_n and ios_n:
        warnings.append(
            "App Store public RSS is recent-only; Play covers the configured window."
        )
    elif play_n and not ios_n:
        warnings.append("Continuing with Play reviews only (App Store missing or empty).")
    elif ios_n and not play_n:
        warnings.append("Continuing with App Store reviews only (Play missing or empty).")
    return warnings


def load_reviews_node(
    state: PulseState,
    *,
    config: AppConfig,
    play_path: Path | None,
    app_store_path: Path | None,
    raw_dir: Path | None,
    fetch_public: bool,
) -> dict[str, Any]:
    st = coerce_state(state)
    try:
        raw = load_reviews(
            st.window,
            config=config,
            play_path=play_path,
            app_store_path=app_store_path,
            raw_dir=raw_dir,
            fetch_rss=fetch_public,
            fetch_public=fetch_public,
            refresh=False,
        )
    except IngestError as exc:
        logger.warning("LoadReviews failed closed: %s", exc)
        return {
            "raw_reviews": [],
            "reviews": [],
            "status": "failed",
            "errors": st.errors + [str(exc)],
        }
    logger.info("LoadReviews kept %s raw reviews (not downsampled)", len(raw))
    return {
        "raw_reviews": raw,
        "warnings": st.warnings + _store_mix_warnings(raw),
        "status": "loading",
    }


def sanitize_pii_node(state: PulseState) -> dict[str, Any]:
    st = coerce_state(state)
    if st.status == "failed":
        return {"raw_reviews": [], "reviews": []}
    sanitized = sanitize_reviews(st.raw_reviews)
    # Drop source ids before any later node (including stubs).
    if not sanitized:
        return {
            "reviews": [],
            "raw_reviews": [],
            "status": "failed",
            "errors": st.errors + ["no reviews remaining after PII sanitization"],
        }
    stores = sorted({row.store for row in sanitized})
    logger.info("SanitizePII produced %s reviews (%s)", len(sanitized), ",".join(stores))
    return {
        "reviews": sanitized,
        "raw_reviews": [],
        "status": "ready",
    }


def route_after_sanitize(state: PulseState | dict[str, Any]) -> AfterSanitize:
    st = coerce_state(state)
    if st.status == "failed" or not st.reviews:
        return "end"
    return "ClusterThemes"


def _resolve_llm(
    config: AppConfig,
    hooks: IntelligenceHooks | None,
    *,
    skip: bool = False,
) -> Any | None:
    if skip:
        return None
    if hooks is not None and hooks.llm is not None:
        return hooks.llm
    if not config.llm_api_key():
        return None
    try:
        return chat_model(config)
    except ConfigError:
        return None


def _window_weeks(state: PulseState, config: AppConfig) -> int:
    span = (state.window.end_date - state.window.start_date).days // 7
    if 8 <= span <= 12:
        return span
    return config.window.weeks


def cluster_themes_node(
    state: PulseState,
    *,
    config: AppConfig,
    hooks: IntelligenceHooks | None,
) -> dict[str, Any]:
    st = coerce_state(state)
    if st.status == "failed":
        return {}
    assigner = hooks.assigner if hooks is not None else None
    llm = _resolve_llm(config, hooks, skip=assigner is not None)
    try:
        clusters = cluster_reviews(st.reviews, assigner=assigner, llm=llm)
    except Exception as exc:  # noqa: BLE001 — fail closed, do not call later LLM nodes
        logger.warning("ClusterThemes failed closed: %s", exc)
        return {
            "clusters": [],
            "status": "failed",
            "errors": st.errors + [str(exc)],
        }
    if not clusters:
        return {
            "clusters": [],
            "status": "failed",
            "errors": st.errors + ["clustering produced no themes"],
        }
    return {"clusters": [row.model_dump() for row in clusters[:5]]}


def select_quotes_node(
    state: PulseState,
    *,
    config: AppConfig,
    hooks: IntelligenceHooks | None,
) -> dict[str, Any]:
    st = coerce_state(state)
    if st.status == "failed":
        return {}
    nominator = hooks.nominator if hooks is not None else None
    llm = _resolve_llm(config, hooks, skip=nominator is not None)
    try:
        quotes = lock_quotes(st.reviews, st.clusters, nominator=nominator, llm=llm)
    except QuoteLockError as exc:
        logger.warning("SelectQuotes failed closed: %s", exc)
        return {
            "quotes": [],
            "status": "failed",
            "errors": st.errors + [str(exc)],
        }
    return {"quotes": [row.model_dump() for row in quotes]}


def propose_actions_node(
    state: PulseState,
    *,
    config: AppConfig,
    hooks: IntelligenceHooks | None,
) -> dict[str, Any]:
    st = coerce_state(state)
    if st.status == "failed":
        return {}
    builder = hooks.action_builder if hooks is not None else None
    llm = _resolve_llm(config, hooks, skip=builder is not None)
    try:
        ideas = build_action_ideas(st.clusters, builder=builder, llm=llm)
    except ValueError as exc:
        logger.warning("ProposeActions failed closed: %s", exc)
        return {
            "actions": [],
            "status": "failed",
            "errors": st.errors + [str(exc)],
        }
    return {"actions": [row.model_dump() for row in ideas]}


def write_pulse_node(
    state: PulseState,
    *,
    config: AppConfig,
    hooks: IntelligenceHooks | None,
    max_write_attempts: int,
) -> dict[str, Any]:
    st = coerce_state(state)
    if st.status == "failed":
        return {}
    attempts = st.write_attempts + 1
    writer = hooks.writer if hooks is not None and hooks.writer is not None else write_pulse_note
    try:
        pulse = writer(
            product=st.product,
            window=st.window,
            clusters=st.clusters,
            quotes=st.quotes,
            actions=st.actions,
            weeks=_window_weeks(st, config),
            reviews=st.reviews,
            feedback=st.errors,
        )
    except ValueError as exc:
        logger.warning("WritePulse failed: %s", exc)
        payload = {
            "pulse": None,
            "write_attempts": attempts,
            "validation_passed": False,
            "errors": st.errors + [str(exc)],
        }
        if attempts >= max_write_attempts:
            payload["status"] = "failed"
        return payload
    return {
        "pulse": pulse.model_dump(),
        "write_attempts": attempts,
        "validation_passed": False,
        "status": "ready",
    }


def validate_pulse_node(
    state: PulseState,
    *,
    max_write_attempts: int,
) -> dict[str, Any]:
    st = coerce_state(state)
    if st.status == "failed":
        return {}
    report = validate_pulse(st.pulse, st.reviews, st.clusters)
    if report.ok:
        logger.info("ValidatePulse passed (%s words)", len((st.pulse.body if st.pulse else "").split()))
        return {"validation_passed": True, "errors": [], "status": "ready"}
    logger.warning("ValidatePulse failed: %s", "; ".join(report.errors))
    exhausted = st.write_attempts >= max_write_attempts
    return {
        "validation_passed": False,
        "errors": list(report.errors),
        "status": "failed" if exhausted else "ready",
    }


def route_after_quotes(state: PulseState | dict[str, Any]) -> AfterQuotes:
    st = coerce_state(state)
    if st.status == "failed" or not st.quotes:
        return "end"
    if st.pulse is not None:
        return "WritePulse"
    return "ProposeActions"


def route_after_validate(
    state: PulseState | dict[str, Any],
    *,
    max_write_attempts: int,
) -> AfterValidate:
    st = coerce_state(state)
    if st.validation_passed and st.status != "failed" and st.pulse is not None:
        return "PublishDoc"
    if st.status == "failed":
        return "end"
    report_needs_quotes = any(item.startswith("quote:") for item in st.errors)
    if st.write_attempts >= max_write_attempts:
        return "end"
    if report_needs_quotes:
        return "SelectQuotes"
    if st.pulse is None and not st.quotes:
        return "end"
    return "WritePulse"


def publish_doc(
    state: PulseState,
    *,
    snapshot_dir: Path | None,
    config: AppConfig,
    hooks: IntelligenceHooks | None,
    send_email: bool = False,
) -> dict[str, Any]:
    """Write the local snapshot, then publish the validated pulse via Docs MCP."""
    del config  # operator email is used in DraftEmail; Doc title comes from the pulse
    st = coerce_state(state)
    if st.status == "failed" or not st.validation_passed or st.pulse is None:
        return {}
    warnings = list(st.warnings)
    payload: dict[str, Any] = {
        "warnings": warnings,
        "doc": None,
        "status": "ready",
    }
    if snapshot_dir is not None:
        path = write_snapshot(st.pulse, run_id=st.run_id, directory=snapshot_dir)
        payload["snapshot_path"] = str(path)
        logger.info("Wrote local snapshot %s", path)

    publisher = hooks.doc_publisher if hooks is not None else None
    invoker = hooks.mcp_invoker if hooks is not None else None
    want_mcp = mcp_enabled() or send_email
    if publisher is None and invoker is None and not want_mcp:
        if SKIP_PUBLISH_MCP not in warnings:
            warnings.append(SKIP_PUBLISH_MCP)
        payload["warnings"] = warnings
        return payload

    try:
        if publisher is not None:
            doc = publisher(st.pulse, st.window, st.product)
        elif invoker is not None:
            doc = publish_doc_via_mcp(st.pulse, st.window, st.product, invoker=invoker)
        else:
            if SKIP_PUBLISH_MCP not in warnings:
                warnings.append(
                    "PublishDoc skipped: no MCP invoker "
                    "(Google Drive plugin in this Cursor project)"
                )
            payload["warnings"] = warnings
            return payload
    except McpDeliveryError as exc:
        logger.warning("PublishDoc MCP failed: %s", exc)
        warnings.append(f"PublishDoc failed: {exc}")
        payload["warnings"] = warnings
        payload["errors"] = st.errors + [str(exc)]
        return payload

    payload["doc"] = doc.model_dump()
    payload["warnings"] = [item for item in warnings if item != SKIP_PUBLISH_MCP]
    logger.info("PublishDoc created %s", doc.url)
    return payload


def draft_email(
    state: PulseState,
    *,
    config: AppConfig,
    hooks: IntelligenceHooks | None,
    send_email: bool = False,
) -> dict[str, Any]:
    """Create a Gmail draft, or send to operator.email when send_email is set."""
    st = coerce_state(state)
    if st.status == "failed" or not st.validation_passed or st.pulse is None:
        return {}
    warnings = list(st.warnings)
    creator = hooks.draft_creator if hooks is not None else None
    invoker = hooks.mcp_invoker if hooks is not None else None
    want_mcp = mcp_enabled() or send_email
    if creator is None and invoker is None and not want_mcp:
        if SKIP_DRAFT_MCP not in warnings:
            warnings.append(SKIP_DRAFT_MCP)
        return {"warnings": warnings, "email": None, "status": "ready"}

    to = config.operator.email
    doc_url = st.doc.url if st.doc is not None else None
    try:
        if creator is not None:
            email = creator(st.pulse, to, doc_url)
        elif invoker is not None and send_email:
            email = send_operator_email(
                st.pulse,
                to=to,
                operator_email=config.operator.email,
                doc_url=doc_url,
                invoker=invoker,
            )
        elif invoker is not None:
            email = create_draft_via_mcp(
                st.pulse, to=to, doc_url=doc_url, invoker=invoker
            )
        else:
            if SKIP_DRAFT_MCP not in warnings:
                warnings.append(
                    "DraftEmail skipped: no MCP invoker "
                    "(Gmail plugin in this Cursor project — not a second MCP server)"
                )
            return {"warnings": warnings, "email": None, "status": "ready"}
    except McpDeliveryError as exc:
        logger.warning("DraftEmail MCP failed: %s", exc)
        if SKIP_DRAFT_MCP not in warnings:
            warnings.append(f"DraftEmail failed: {exc}")
        return {
            "warnings": warnings,
            "email": None,
            "status": "ready",
            "errors": st.errors + [str(exc)],
        }

    warnings = [item for item in warnings if item != SKIP_DRAFT_MCP]
    status = "published" if st.doc is not None else "ready"
    if email.sent:
        logger.info("Sent weekly pulse to %s (message %s)", to, email.message_id)
    else:
        logger.info("DraftEmail created draft %s (not sent)", email.draft_id)
    return {"warnings": warnings, "email": email.model_dump(), "status": status}


def _wrap(name: str, fn: NodeFn, visited: list[str] | None) -> NodeFn:
    def node(state: PulseState) -> dict[str, Any]:
        if visited is not None:
            visited.append(name)
        return fn(state)

    node.__name__ = name
    return node


def compile_pulse_graph(
    *,
    config: AppConfig | None = None,
    play_path: Path | None = None,
    app_store_path: Path | None = None,
    raw_dir: Path | None = None,
    fetch_public: bool = False,
    visited: list[str] | None = None,
    hooks: IntelligenceHooks | None = None,
    max_write_attempts: int = MAX_WRITE_ATTEMPTS,
    snapshot_dir: Path | None = None,
    send_email: bool = False,
):
    """Compile the pulse StateGraph. MCP publish/draft run only when enabled."""
    cfg = config or load_config()
    intel = hooks if hooks is not None else IntelligenceHooks()
    attempts_cap = max(1, max_write_attempts)

    def load_node(state: PulseState) -> dict[str, Any]:
        return load_reviews_node(
            state,
            config=cfg,
            play_path=play_path,
            app_store_path=app_store_path,
            raw_dir=raw_dir,
            fetch_public=fetch_public,
        )

    def cluster_node(state: PulseState) -> dict[str, Any]:
        return cluster_themes_node(state, config=cfg, hooks=intel)

    def quotes_node(state: PulseState) -> dict[str, Any]:
        return select_quotes_node(state, config=cfg, hooks=intel)

    def actions_node(state: PulseState) -> dict[str, Any]:
        return propose_actions_node(state, config=cfg, hooks=intel)

    def write_node(state: PulseState) -> dict[str, Any]:
        return write_pulse_node(
            state, config=cfg, hooks=intel, max_write_attempts=attempts_cap
        )

    def validate_node(state: PulseState) -> dict[str, Any]:
        return validate_pulse_node(state, max_write_attempts=attempts_cap)

    def validate_route(state: PulseState) -> AfterValidate:
        return route_after_validate(state, max_write_attempts=attempts_cap)

    def publish_node(state: PulseState) -> dict[str, Any]:
        return publish_doc(
            state,
            snapshot_dir=snapshot_dir,
            config=cfg,
            hooks=intel,
            send_email=send_email,
        )

    def draft_node(state: PulseState) -> dict[str, Any]:
        return draft_email(state, config=cfg, hooks=intel, send_email=send_email)

    builder = StateGraph(GraphState)
    builder.add_node("LoadReviews", _wrap("LoadReviews", load_node, visited))
    builder.add_node("SanitizePII", _wrap("SanitizePII", sanitize_pii_node, visited))
    builder.add_node("ClusterThemes", _wrap("ClusterThemes", cluster_node, visited))
    builder.add_node("SelectQuotes", _wrap("SelectQuotes", quotes_node, visited))
    builder.add_node("ProposeActions", _wrap("ProposeActions", actions_node, visited))
    builder.add_node("WritePulse", _wrap("WritePulse", write_node, visited))
    builder.add_node("ValidatePulse", _wrap("ValidatePulse", validate_node, visited))
    builder.add_node("PublishDoc", _wrap("PublishDoc", publish_node, visited))
    builder.add_node("DraftEmail", _wrap("DraftEmail", draft_node, visited))

    builder.set_entry_point("LoadReviews")
    builder.add_edge("LoadReviews", "SanitizePII")
    builder.add_conditional_edges(
        "SanitizePII",
        route_after_sanitize,
        {"ClusterThemes": "ClusterThemes", "end": END},
    )
    builder.add_edge("ClusterThemes", "SelectQuotes")
    builder.add_conditional_edges(
        "SelectQuotes",
        route_after_quotes,
        {"ProposeActions": "ProposeActions", "WritePulse": "WritePulse", "end": END},
    )
    builder.add_edge("ProposeActions", "WritePulse")
    builder.add_edge("WritePulse", "ValidatePulse")
    builder.add_conditional_edges(
        "ValidatePulse",
        validate_route,
        {
            "PublishDoc": "PublishDoc",
            "WritePulse": "WritePulse",
            "SelectQuotes": "SelectQuotes",
            "end": END,
        },
    )
    builder.add_edge("PublishDoc", "DraftEmail")
    builder.add_edge("DraftEmail", END)
    return builder.compile()


def invoke_pulse(graph: Any, state: PulseState) -> PulseState:
    result = graph.invoke(state.model_dump(), config={"recursion_limit": 50})
    return coerce_state(result)


if __name__ == "__main__":
    from pulse.run import main as run_main

    raise SystemExit(run_main())
