"""Three concrete action ideas tagged to clustered themes."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from pulse.prompts import BANNED_ACTION_SLOGANS
from pulse.schemas import ActionIdea, OwnerHint, ThemeCluster

logger = logging.getLogger("pulse.actions")

ActionBuilder = Callable[[list[ThemeCluster]], list[ActionIdea]]

_DEFAULTS: dict[str, tuple[str, str, OwnerHint]] = {
    "charts and trading tools": (
        "Fix chart back navigation and scalper overlap",
        "Move or hide scalper so it does not capture the Android back gesture; restore a reliable way to leave chart view.",
        "Product",
    ),
    "brokerage and charges": (
        "Publish a clear brokerage comparison",
        "Users already name cheaper competitors; explain or reduce charges on the fee screen instead of a slogan.",
        "Growth",
    ),
    "order execution and fills": (
        "Put GTT and OCO on one order ticket",
        "Traders report missing GTT/OCO together and disputed fills; show both on one screen with the quoted price.",
        "Product",
    ),
    "support and account access": (
        "Break ReKYC freeze chat loops",
        "When ReKYC or camera KYC exceeds the promised 1–2 days, escalate instead of closing tickets with copy-paste templates.",
        "Support",
    ),
    "app stability and updates": (
        "Ship a navigation/crash hotfix for the latest build",
        "Reviews cite crashes, freezes, and broken back navigation after updates; gate the next release on those flows.",
        "Product",
    ),
    "payments and upi": (
        "Clarify UPI add-money failure copy",
        "Show why the UPI debit failed and a retry path on the add-money screen.",
        "Product",
    ),
    "withdrawals": (
        "Show expected payout timing on withdrawals",
        "When a bank withdrawal sits in processing, display ETA and status instead of a silent spinner.",
        "Product",
    ),
    "ipo applications": (
        "Fix IPO UPI mandate delivery",
        "IPO windows close while mandates never arrive; page Support with mandate status in-app.",
        "Support",
    ),
    "loan-app cross-sell": (
        "Stop forcing the Groww loan App Store prompt",
        "iOS reviews say opening Groww pushes the loan app download; make that opt-in.",
        "Growth",
    ),
    "alerts": (
        "Restore durable iOS price alerts",
        "iPhone alerts expire too quickly and cannot be searched; match Android behaviour.",
        "Product",
    ),
    "ease of use": (
        "Protect the beginner-friendly UI in trading views",
        "Keep the simple dashboard, but do not let ease-of-use praise bury 1★ trading-tool bugs.",
        "Product",
    ),
}


def _is_slogan(title: str, rationale: str) -> bool:
    blob = f"{title} {rationale}".lower()
    return any(phrase in blob for phrase in BANNED_ACTION_SLOGANS)


def _default_for(theme: str) -> ActionIdea:
    key = theme.lower()
    for needle, (title, rationale, owner) in _DEFAULTS.items():
        if needle in key or key in needle:
            return ActionIdea(title=title, rationale=rationale, theme=theme, owner_hint=owner)
    return ActionIdea(
        title=f"Investigate {theme} with a concrete ticket",
        rationale=f"Clustered reviews point at {theme}; file a scoped product or support ticket with examples from this window.",
        theme=theme,
        owner_hint="Product",
    )


def heuristic_actions(clusters: Sequence[ThemeCluster]) -> list[ActionIdea]:
    actions: list[ActionIdea] = []
    for cluster in list(clusters)[:3]:
        idea = _default_for(cluster.name)
        if _is_slogan(idea.title, idea.rationale):
            idea = _default_for("app stability and updates")
            idea = idea.model_copy(update={"theme": cluster.name})
        actions.append(idea)
    if len(actions) != 3:
        raise ValueError("need 3 clustered themes before proposing actions")
    return actions


def propose_actions(
    clusters: Sequence[ThemeCluster],
    *,
    builder: ActionBuilder | None = None,
    llm: Any | None = None,
) -> list[ActionIdea]:
    del llm  # Groq rewrite can wait; defaults are corpus-grounded and testable.
    build = builder or heuristic_actions
    ideas = build(list(clusters))
    names = {cluster.name for cluster in clusters}
    cleaned: list[ActionIdea] = []
    for idea in ideas:
        if idea.theme not in names:
            raise ValueError(f"action theme {idea.theme!r} is not in clustered set")
        if _is_slogan(idea.title, idea.rationale):
            idea = _default_for(idea.theme)
        cleaned.append(idea)
    if len(cleaned) != 3:
        raise ValueError("need exactly 3 actions")
    return cleaned[:3]
