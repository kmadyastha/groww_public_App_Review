"""Quote selection: model nominates ids; Python copies sanitized substrings."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

from pulse.llm import response_text
from pulse.privacy import format_attribution, is_name_like_title
from pulse.prompts import quote_nominate_prompt
from pulse.schemas import Quote, SanitizedReview, ThemeCluster

logger = logging.getLogger("pulse.quotes")

Nominator = Callable[[list[SanitizedReview], list[ThemeCluster]], list[Any]]
EXCERPT_WORDS = 28
QUOTE_PROMPT_PER_THEME = 6
QUOTE_PROMPT_MAX = 18


class QuoteLockError(ValueError):
    """Nominated wording is not a substring of sanitized review text."""


def _verbatim_excerpt(text: str, *, max_words: int = EXCERPT_WORDS) -> str:
    """Copy a contiguous sanitized substring; never paraphrase."""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    for sentence in sentences:
        snippet = sentence.strip()
        if not snippet or snippet not in text:
            continue
        if 4 <= len(snippet.split()) <= max_words:
            return snippet
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    prefix = " ".join(words[:max_words])
    if prefix in cleaned:
        return prefix
    return cleaned[: min(len(cleaned), 160)]


def quote_attribution(quote: Quote) -> str:
    return format_attribution(rating=quote.rating, store=quote.store, on=quote.date)


def lock_quote(review: SanitizedReview, nominated_text: str | None = None) -> Quote:
    """Copy verbatim text. Never paraphrase; never use a name-like iOS title."""
    if nominated_text:
        nominated = nominated_text.strip()
        if is_name_like_title(nominated):
            raise QuoteLockError("refusing name-like title as a quote")
        if nominated and nominated in review.text:
            snippet = nominated
        elif (
            nominated
            and review.title
            and nominated in review.title
            and not is_name_like_title(review.title)
        ):
            snippet = nominated
        else:
            raise QuoteLockError(
                "nominated text is not a substring of sanitized review text"
            )
    else:
        snippet = _verbatim_excerpt(review.text)
        if not snippet:
            raise QuoteLockError("review has no quoteable text")
        if snippet not in review.text:
            raise QuoteLockError("excerpt is not a substring of sanitized review text")
    return Quote(
        review_id=review.review_id,
        text=snippet,
        rating=review.rating,
        store=review.store,
        date=review.date,
    )


def _parse_ids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        raw = payload.get("review_ids") or payload.get("ids") or []
        return [str(item) for item in raw]
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.removeprefix("json").strip()
        try:
            return _parse_ids(json.loads(text))
        except json.JSONDecodeError:
            return []
    if hasattr(payload, "content"):
        return _parse_ids(payload.content)
    if isinstance(payload, list):
        return [str(item) for item in payload]
    return []


def heuristic_nominator(
    reviews: list[SanitizedReview],
    clusters: list[ThemeCluster],
) -> list[str]:
    """Pick 3 ids from distinct top themes; prefer 1–3★ and mix stores."""
    by_id = {row.review_id: row for row in reviews}
    chosen: list[str] = []
    used: set[str] = set()
    top = clusters[:3] or clusters
    for cluster in top:
        candidates = [by_id[rid] for rid in cluster.review_ids if rid in by_id and rid not in used]
        if not candidates:
            continue
        candidates.sort(
            key=lambda row: (
                0 if row.rating <= 3 else 1,
                0 if row.store == "play" else 1,
                row.rating,
            )
        )
        chosen.append(candidates[0].review_id)
        used.add(candidates[0].review_id)
        if len(chosen) == 3:
            return chosen
    leftover = [row for row in reviews if row.review_id not in used]
    leftover.sort(key=lambda row: (row.rating, 0 if row.store == "play" else 1))
    for row in leftover:
        chosen.append(row.review_id)
        if len(chosen) == 3:
            break
    return chosen


def _quote_prompt_pool(
    reviews: list[SanitizedReview],
    clusters: list[ThemeCluster],
) -> list[SanitizedReview]:
    """Send Groq a small candidate set, not the full 1.5k corpus."""
    by_id = {row.review_id: row for row in reviews}
    picked: list[SanitizedReview] = []
    seen: set[str] = set()
    for cluster in clusters[:3]:
        rows = [by_id[rid] for rid in cluster.review_ids if rid in by_id and rid not in seen]
        rows.sort(
            key=lambda row: (
                0 if row.rating <= 3 else 1,
                0 if row.store == "play" else 1,
                row.rating,
            )
        )
        for row in rows[:QUOTE_PROMPT_PER_THEME]:
            picked.append(row)
            seen.add(row.review_id)
            if len(picked) >= QUOTE_PROMPT_MAX:
                return picked
    if len(picked) < 3:
        for row in reviews:
            if row.review_id not in seen:
                picked.append(row)
                seen.add(row.review_id)
            if len(picked) >= 3:
                break
    return picked


def llm_nominator(llm: Any) -> Nominator:
    def nominate(reviews: list[SanitizedReview], clusters: list[ThemeCluster]) -> list[str]:
        pool = _quote_prompt_pool(reviews, clusters)
        prompt = quote_nominate_prompt(pool, [c.name for c in clusters[:5]])
        try:
            raw = response_text(llm.invoke(prompt))
            ids = _parse_ids(raw)
        except Exception as exc:  # noqa: BLE001 — provider 413/429 must not crash the run
            logger.warning("Quote nominator failed, using heuristic: %s", exc)
            return heuristic_nominator(reviews, clusters)
        if len(ids) >= 3:
            return ids[:3]
        logger.warning("Quote nominator incomplete; using heuristic")
        return heuristic_nominator(reviews, clusters)

    return nominate


def select_quotes(
    reviews: Sequence[SanitizedReview],
    clusters: Sequence[ThemeCluster],
    *,
    nominator: Nominator | None = None,
    llm: Any | None = None,
) -> list[Quote]:
    rows = list(reviews)
    themes = list(clusters)
    by_id = {row.review_id: row for row in rows}
    if nominator is None:
        nominator = llm_nominator(llm) if llm is not None else heuristic_nominator
    nominated = nominator(rows, themes)
    quotes: list[Quote] = []
    seen: set[str] = set()
    for item in nominated:
        review_id = item if isinstance(item, str) else getattr(item, "review_id", None)
        nominated_text = None if isinstance(item, str) else getattr(item, "text", None)
        if review_id not in by_id:
            raise QuoteLockError(f"unknown review_id {review_id}")
        if review_id in seen:
            continue
        quotes.append(lock_quote(by_id[review_id], nominated_text))
        seen.add(review_id)
        if len(quotes) == 3:
            break
    if len(quotes) != 3:
        raise QuoteLockError("need exactly 3 quotes from distinct reviews")
    return quotes
