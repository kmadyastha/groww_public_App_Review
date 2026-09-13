"""Theme clustering: batched assign, rank, hard cap of 5. Groq optional."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from pulse.llm import response_text
from pulse.prompts import CANDIDATE_THEMES, cluster_chunk_prompt
from pulse.schemas import SanitizedReview, Severity, ThemeCluster

logger = logging.getLogger("pulse.cluster")

CHUNK_SIZE = 80
MAX_THEMES = 5
MAX_LLM_RETRIES = 3

Assigner = Callable[[list[SanitizedReview], Sequence[str]], list[tuple[str, str]]]

_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Charts and trading tools": (
        "chart",
        "scalper",
        "scalping",
        "gtt",
        "oco",
        "vtt",
        "option chain",
        "indicator",
        "tradingview",
        "trading view",
        "back button",
        "back switch",
        "camarilla",
    ),
    "Brokerage and charges": (
        "brokerage",
        "charges",
        "charge",
        "fees",
        "fee",
        "commission",
        "5paisa",
        "tariff",
    ),
    "Order execution and fills": (
        "slippage",
        "execution",
        "fill",
        "buy price",
        "order flow",
        "smartexit",
        "trailing stop",
    ),
    "Support and account access": (
        "support",
        "customer care",
        "customer service",
        "chat",
        "ticket",
        "kyc",
        "rekyc",
        "re-kyc",
        "e-kyc",
        "ekyc",
        "verification",
        "frozen",
        "freeze",
        "camera",
        "account setup",
        "account opening",
        "onboarding is not allowed",
    ),
    "App stability and updates": (
        "crash",
        "crashes",
        "crashed",
        "glitch",
        "hang",
        "hangs",
        "lag",
        "bug",
        "latest update",
        "last update",
        "navigation",
        "freeze",
        "freezes",
        "frozen",
    ),
    "Payments and UPI": (
        "upi",
        "add money",
        "wallet",
        "payment",
        "mandate",
    ),
    "Withdrawals": (
        "withdraw",
        "withdrawal",
        "withdrawals",
        "payout",
        "bank withdrawal",
    ),
    "IPO applications": (
        "ipo",
        "hni",
    ),
    "Loan-app cross-sell": (
        "loan app",
        "groww loan",
    ),
    "Alerts": (
        "alert",
        "alerts",
    ),
    "Ease of use": (
        "user friendly",
        "user-friendly",
        "easy to use",
        "easy to understand",
        "beginner",
        "intuitive",
        "simple interface",
    ),
}


class ThemeAssignment(BaseModel):
    review_id: str
    theme: str


class ChunkAssignments(BaseModel):
    assignments: list[ThemeAssignment] = Field(default_factory=list)


class ClusterError(ValueError):
    """Clustering failed closed."""


def _blob(review: SanitizedReview) -> str:
    return f"{review.title or ''} {review.text}".lower()


def _score_theme(blob: str, keywords: Sequence[str]) -> int:
    score = 0
    for key in keywords:
        if " " in key:
            if key in blob:
                score += 1
        elif re.search(rf"\b{re.escape(key)}\b", blob):
            score += 1
    return score


def keyword_assigner(
    reviews: list[SanitizedReview],
    candidates: Sequence[str],
) -> list[tuple[str, str]]:
    """Deterministic assigner used when Groq is absent and in tests."""
    allowed = {name: _THEME_KEYWORDS[name] for name in candidates if name in _THEME_KEYWORDS}
    out: list[tuple[str, str]] = []
    for review in reviews:
        blob = _blob(review)
        ranked = sorted(
            ((name, _score_theme(blob, keys)) for name, keys in allowed.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        if ranked and ranked[0][1] > 0:
            out.append((review.review_id, ranked[0][0]))
    return out


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _canonical_name(name: str, candidates: Sequence[str]) -> str | None:
    needle = _norm_name(name)
    if not needle:
        return None
    if "statement" in needle and "support" not in needle:
        # Do not revive the unused problem-statement example label.
        if needle in {"statements", "p l statement", "pnl"}:
            return None
    for cand in candidates:
        if needle == _norm_name(cand):
            return cand
    for cand in candidates:
        cnorm = _norm_name(cand)
        if needle in cnorm or cnorm in needle:
            return cand
    if "kyc" in needle or "support" in needle or "account" in needle:
        return "Support and account access"
    return None


def _severity(avg_rating: float, negative_share: float) -> Severity:
    if avg_rating <= 2.3 or negative_share >= 0.5:
        return "high"
    if avg_rating <= 3.4 or negative_share >= 0.3:
        return "medium"
    return "low"


def _rank_key(cluster: ThemeCluster) -> tuple[float, int, int]:
    negative_weight = max(0.0, 5.0 - cluster.avg_rating)
    score = cluster.count * (1.0 + negative_weight)
    return (score, cluster.count, -int(cluster.avg_rating * 10))


def build_clusters(
    reviews: Sequence[SanitizedReview],
    assignments: Iterable[tuple[str, str]],
    *,
    candidates: Sequence[str] = CANDIDATE_THEMES,
) -> list[ThemeCluster]:
    by_id = {row.review_id: row for row in reviews}
    grouped: dict[str, list[SanitizedReview]] = defaultdict(list)
    for review_id, theme in assignments:
        name = _canonical_name(theme, candidates)
        review = by_id.get(review_id)
        if name is None or review is None:
            continue
        grouped[name].append(review)

    clusters: list[ThemeCluster] = []
    for name, rows in grouped.items():
        if not rows:
            continue
        ratings = [row.rating for row in rows]
        avg = sum(ratings) / len(ratings)
        neg = sum(1 for rating in ratings if rating <= 2) / len(ratings)
        play_n = sum(1 for row in rows if row.store == "play")
        ios_n = len(rows) - play_n
        clusters.append(
            ThemeCluster(
                name=name,
                review_ids=[row.review_id for row in rows],
                count=len(rows),
                avg_rating=round(avg, 2),
                severity=_severity(avg, neg),
                play_count=play_n,
                app_store_count=ios_n,
            )
        )
    return finalize_clusters(clusters)


def finalize_clusters(clusters: Sequence[ThemeCluster]) -> list[ThemeCluster]:
    """Merge aliases, drop empty labels, rank, cap at 5. Never persist 6+."""
    merged: dict[str, ThemeCluster] = {}
    for cluster in clusters:
        if cluster.count <= 0 or not cluster.review_ids:
            continue
        key = _norm_name(cluster.name)
        if "statement" in key and "support" not in key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = cluster
            continue
        ids = list(dict.fromkeys(existing.review_ids + cluster.review_ids))
        total = existing.count + cluster.count
        avg = (
            existing.avg_rating * existing.count + cluster.avg_rating * cluster.count
        ) / total
        merged[key] = ThemeCluster(
            name=existing.name,
            review_ids=ids,
            count=len(ids),
            avg_rating=round(avg, 2),
            severity=existing.severity
            if existing.severity == "high" or cluster.severity != "high"
            else cluster.severity,
            play_count=existing.play_count + cluster.play_count,
            app_store_count=existing.app_store_count + cluster.app_store_count,
        )
    ranked = sorted(merged.values(), key=_rank_key, reverse=True)
    return ranked[:MAX_THEMES]


def _parse_assignments(payload: Any) -> list[tuple[str, str]]:
    if isinstance(payload, ChunkAssignments):
        return [(row.review_id, row.theme) for row in payload.assignments]
    if isinstance(payload, BaseModel):
        payload = payload.model_dump()
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        payload = json.loads(text)
    if isinstance(payload, dict) and "assignments" in payload:
        payload = payload["assignments"]
    if not isinstance(payload, list):
        return []
    out: list[tuple[str, str]] = []
    for item in payload:
        if isinstance(item, dict) and item.get("review_id") and item.get("theme"):
            out.append((str(item["review_id"]), str(item["theme"])))
    return out


def _hard_groq_failure(exc: Exception) -> bool:
    blob = str(exc).lower()
    return any(
        token in blob
        for token in (
            "413",
            "429",
            "too large",
            "tool_use_failed",
            "rate_limit",
            "payload too large",
        )
    )


def _llm_chunk(llm: Any, reviews: list[SanitizedReview]) -> list[tuple[str, str]] | None:
    """Return Groq assignments, or None so the caller can keyword-fallback."""
    prompt = cluster_chunk_prompt(reviews)
    last_error: Exception | None = None
    for attempt in range(MAX_LLM_RETRIES):
        try:
            # Plain JSON only. Groq tool/structured output returns 400 tool_use_failed
            # on this free-tier model and is not worth retrying.
            raw = response_text(llm.invoke(prompt))
            parsed = _parse_assignments(raw)
            if parsed:
                return parsed
        except Exception as exc:  # noqa: BLE001 — Groq 400/413/429
            last_error = exc
            if _hard_groq_failure(exc):
                break
            time.sleep(0.4 * (attempt + 1))
    if last_error:
        logger.warning("LLM cluster chunk failed, falling back to keywords: %s", last_error)
    return None


def llm_assigner(llm: Any) -> Assigner:
    def assign(reviews: list[SanitizedReview], candidates: Sequence[str]) -> list[tuple[str, str]]:
        del candidates
        out: list[tuple[str, str]] = []
        use_keywords = False
        for start in range(0, len(reviews), CHUNK_SIZE):
            chunk = reviews[start : start + CHUNK_SIZE]
            parsed = None if use_keywords else _llm_chunk(llm, chunk)
            if parsed is None:
                if not use_keywords:
                    logger.warning(
                        "Skipping remaining Groq cluster chunks after failure (%s reviews left)",
                        len(reviews) - start,
                    )
                    use_keywords = True
                out.extend(keyword_assigner(chunk, CANDIDATE_THEMES))
            else:
                out.extend(parsed)
        return out

    return assign


def cluster_reviews(
    reviews: Sequence[SanitizedReview],
    *,
    assigner: Assigner | None = None,
    llm: Any | None = None,
    candidates: Sequence[str] = CANDIDATE_THEMES,
) -> list[ThemeCluster]:
    """Assign reviews to ≤ 5 ranked themes. Prefer Groq when `llm` is set."""
    rows = list(reviews)
    if not rows:
        return []
    if assigner is None:
        assigner = llm_assigner(llm) if llm is not None else keyword_assigner
    assignments = assigner(rows, candidates)
    clusters = build_clusters(rows, assignments, candidates=candidates)
    if len(clusters) > MAX_THEMES:
        clusters = clusters[:MAX_THEMES]
    return clusters
