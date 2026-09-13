"""Deterministic pulse guardrails. Fail closed before any publish.

Word count uses the same tokenizer as the writer: Unicode whitespace split
(`str.split()`, no markdown stripping). A body of exactly 250 words passes;
251 fails.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pulse.privacy import is_name_like_title, leak_labels
from pulse.prompts import CANDIDATE_THEMES, FORBIDDEN_EMPTY_SEEDS
from pulse.schemas import PulseNote, SanitizedReview, ThemeCluster
from pulse.write import MAX_PULSE_WORDS, word_count

MAX_WRITE_ATTEMPTS = 3
MAX_THEMES = 5

HEADING_THEMES = re.compile(r"1\.\s+Top 3 themes", re.I)
HEADING_QUOTES = re.compile(r"2\.\s+What users said \(3 quotes\)", re.I)
HEADING_ACTIONS = re.compile(r"3\.\s+Three action ideas", re.I)
_BULLET_RE = re.compile(r"^\s*[-*]\s+", re.M)
_QUOTED_RE = re.compile(r"[“\"](.+?)[”\"]")


def quoted_snippets(body: str) -> list[str]:
    return _QUOTED_RE.findall(body or "")


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def needs_quote_retry(self) -> bool:
        return any(item.startswith("quote:") for item in self.errors)


def _section(body: str, start: re.Pattern[str], end: re.Pattern[str] | None) -> str:
    found = start.search(body)
    if not found:
        return ""
    begin = found.end()
    if end is None:
        return body[begin:]
    stop = end.search(body, begin)
    return body[begin : stop.start() if stop else len(body)]


def _bullets(section: str) -> list[str]:
    return [line.strip() for line in section.splitlines() if _BULLET_RE.match(line)]


def _quote_in_reviews(snippet: str, reviews: Sequence[SanitizedReview]) -> bool:
    if not snippet:
        return False
    for row in reviews:
        if snippet in (row.text or ""):
            return True
        if row.title and snippet in row.title and not is_name_like_title(row.title):
            return True
    return False


def validate_pulse(
    pulse: PulseNote | None,
    reviews: Sequence[SanitizedReview],
    clusters: Sequence[ThemeCluster],
    *,
    extra_needles: Sequence[str] = (),
) -> ValidationReport:
    """Return a report. `ok` means the pulse may proceed toward publish."""
    errors: list[str] = []
    if pulse is None:
        return ValidationReport(("shape: missing pulse note",))

    if len(pulse.themes) != 3:
        errors.append(f"shape: expected 3 themes in the note, got {len(pulse.themes)}")
    if len(pulse.quotes) != 3:
        errors.append(f"shape: expected 3 quotes in the note, got {len(pulse.quotes)}")
    if len(pulse.actions) != 3:
        errors.append(f"shape: expected 3 actions in the note, got {len(pulse.actions)}")

    body = pulse.body or ""
    n_words = word_count(body)
    if n_words > MAX_PULSE_WORDS:
        errors.append(f"length: pulse is {n_words} words; cap is {MAX_PULSE_WORDS}")

    if not HEADING_THEMES.search(body):
        errors.append("shape: missing heading '1. Top 3 themes'")
    if not HEADING_QUOTES.search(body):
        errors.append("shape: missing heading '2. What users said (3 quotes)'")
    if not HEADING_ACTIONS.search(body):
        errors.append("shape: missing heading '3. Three action ideas'")

    if len(clusters) > MAX_THEMES:
        errors.append(f"theme: clustered set has {len(clusters)} themes; cap is {MAX_THEMES}")

    cluster_names = {row.name for row in clusters}
    for highlight in pulse.themes:
        if highlight.name not in cluster_names:
            errors.append(f"theme: {highlight.name!r} is not in the clustered set")

    theme_section = _section(body, HEADING_THEMES, HEADING_QUOTES)
    quote_section = _section(body, HEADING_QUOTES, HEADING_ACTIONS)
    action_section = _section(body, HEADING_ACTIONS, None)

    theme_bullets = _bullets(theme_section)
    if HEADING_THEMES.search(body) and len(theme_bullets) != 3:
        errors.append(f"shape: expected 3 theme bullets in prose, got {len(theme_bullets)}")
    quote_bullets = _bullets(quote_section)
    if HEADING_QUOTES.search(body) and len(quote_bullets) != 3:
        errors.append(f"shape: expected 3 quote bullets in prose, got {len(quote_bullets)}")
    action_bullets = _bullets(action_section)
    if HEADING_ACTIONS.search(body) and len(action_bullets) != 3:
        errors.append(f"shape: expected 3 action bullets in prose, got {len(action_bullets)}")

    lowered_body_themes = theme_section.lower()
    for name in CANDIDATE_THEMES:
        if name.lower() in lowered_body_themes and name not in cluster_names:
            errors.append(f"theme: prose mentions {name!r} which is not in the clustered set")
    for forbidden in FORBIDDEN_EMPTY_SEEDS:
        if forbidden in lowered_body_themes and not any(
            forbidden in name.lower() for name in cluster_names
        ):
            errors.append(f"theme: prose uses empty seed {forbidden!r}")

    for quote in pulse.quotes:
        if is_name_like_title(quote.text):
            errors.append("quote: refusing name-like title as a quote")
        if not _quote_in_reviews(quote.text, reviews):
            errors.append("quote: locked text is not a substring of a sanitized review")
        if quote.text not in body:
            errors.append("quote: locked text is missing from the pulse body")

    for snippet in quoted_snippets(body):
        if is_name_like_title(snippet):
            errors.append("quote: body quote looks like a reviewer name")
        if not _quote_in_reviews(snippet, reviews):
            errors.append("quote: body wording is not a substring of a sanitized review")

    action_names = {idea.theme for idea in pulse.actions}
    for idea in pulse.actions:
        if idea.theme not in cluster_names:
            errors.append(f"theme: action {idea.title!r} tagged to {idea.theme!r} not in clusters")
    del action_names

    for label in leak_labels(body, extra_needles=extra_needles):
        errors.append(f"pii: {label} leaked into the pulse body")

    # Preserve order, drop duplicates.
    unique: list[str] = []
    seen: set[str] = set()
    for item in errors:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return ValidationReport(tuple(unique))
