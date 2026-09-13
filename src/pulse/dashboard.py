"""Dashboard payload from a validated pulse run. No Google."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pulse.schemas import PulseNote, ThemeCluster
from pulse.state import PulseState
from pulse.write import word_count

Sentiment = Literal["positive", "negative", "neutral"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "cache"


def sentiment_of(rating: int) -> Sentiment:
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def cache_path(weeks: int, directory: Path | None = None) -> Path:
    root = directory or DEFAULT_CACHE_DIR
    return root / f"dashboard-{weeks}.json"


def iso_week_label(end: date) -> tuple[str, int]:
    iso = end.isocalendar()
    return f"W{iso.week:02d}", iso.year


def _theme_for_review(review_id: str, clusters: list[ThemeCluster]) -> str:
    for cluster in clusters:
        if review_id in cluster.review_ids:
            return cluster.name
    return "Other"


def _share(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * count / total, 1)


def _sentiment_counts(ratings: list[int]) -> dict[str, int]:
    tallies = Counter(sentiment_of(rating) for rating in ratings)
    return {
        "positive": int(tallies.get("positive", 0)),
        "negative": int(tallies.get("negative", 0)),
        "neutral": int(tallies.get("neutral", 0)),
    }


def build_dashboard(state: PulseState, *, weeks: int) -> dict[str, Any]:
    reviews = list(state.reviews)
    clusters = list(state.clusters)
    total = len(reviews)
    ratings = [row.rating for row in reviews]
    dist = {str(star): sum(1 for rating in ratings if rating == star) for star in range(1, 6)}
    avg = round(sum(ratings) / total, 1) if total else 0.0
    week_label, year = iso_week_label(state.window.end_date)
    id_to_theme = {
        review_id: cluster.name
        for cluster in clusters
        for review_id in cluster.review_ids
    }

    theme_rows = []
    for cluster in clusters:
        cluster_reviews = [row for row in reviews if row.review_id in set(cluster.review_ids)]
        theme_rows.append(
            {
                "name": cluster.name,
                "count": cluster.count,
                "share": _share(cluster.count, total),
                "avg_rating": round(cluster.avg_rating, 1),
                "severity": cluster.severity,
                "play_count": cluster.play_count,
                "app_store_count": cluster.app_store_count,
                "sentiment": _sentiment_counts([row.rating for row in cluster_reviews]),
            }
        )

    quote_theme = []
    if state.pulse is not None:
        for quote, highlight in zip(state.pulse.quotes, state.pulse.themes):
            quote_theme.append(
                {
                    "theme": highlight.name,
                    "summary": highlight.summary,
                    "quote": quote.text,
                    "rating": quote.rating,
                    "store": quote.store,
                    "date": quote.date.isoformat(),
                    "sentiment": sentiment_of(quote.rating),
                }
            )

    executive = ""
    if total and theme_rows:
        names = ", ".join(row["name"] for row in theme_rows[:3])
        split = _sentiment_counts(ratings)
        executive = (
            f"Across {total} public Groww reviews from "
            f"{state.window.start_date.isoformat()} to {state.window.end_date.isoformat()}, "
            f"average rating is {avg}★. Top themes: {names}. "
            f"Sentiment split: {split['positive']} positive, {split['negative']} negative, "
            f"{split['neutral']} neutral."
        )

    pulse_block = None
    if state.pulse is not None:
        pulse_block = {
            "title": state.pulse.title,
            "body": state.pulse.body,
            "words": word_count(state.pulse.body),
            "executive_summary": executive,
            "themes": quote_theme,
            "actions": [
                {
                    "title": idea.title,
                    "rationale": idea.rationale,
                    "theme": idea.theme,
                    "owner_hint": idea.owner_hint,
                }
                for idea in state.pulse.actions
            ],
        }

    return {
        "run_id": state.run_id,
        "weeks": weeks,
        "window": {
            "start": state.window.start_date.isoformat(),
            "end": state.window.end_date.isoformat(),
        },
        "iso_week": week_label,
        "year": year,
        "product": state.product.name,
        "overview": {
            "total_reviews": total,
            "avg_rating": avg,
            "sentiment": _sentiment_counts(ratings),
            "rating_distribution": dist,
            "top_themes": [
                {"name": row["name"], "count": row["count"], "share": row["share"]}
                for row in theme_rows
            ],
        },
        "themes": theme_rows,
        "reviews": [
            {
                "review_id": row.review_id,
                "store": row.store,
                "rating": row.rating,
                "title": row.title,
                "text": row.text,
                "date": row.date.isoformat(),
                "theme": id_to_theme.get(row.review_id, _theme_for_review(row.review_id, clusters)),
                "sentiment": sentiment_of(row.rating),
            }
            for row in reviews
        ],
        "pulse": pulse_block,
        "status": state.status,
        "warnings": list(state.warnings),
        "source": "live",
    }


def write_dashboard(
    state: PulseState,
    *,
    weeks: int,
    directory: Path | None = None,
) -> Path:
    root = directory or DEFAULT_CACHE_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = cache_path(weeks, root)
    path.write_text(
        json.dumps(build_dashboard(state, weeks=weeks), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def cache_is_usable(payload: dict[str, Any], weeks: int) -> bool:
    """Drop fixture seeds and caches built for a different lookback."""
    if int(payload.get("weeks") or 0) != weeks:
        return False
    if str(payload.get("run_id") or "") == "ui-seed":
        return False
    if str(payload.get("source") or "") == "seed":
        return False
    raw_play = REPO_ROOT / "data" / "raw" / "play_reviews.json"
    total = int((payload.get("overview") or {}).get("total_reviews") or 0)
    if raw_play.is_file() and total < 50:
        return False
    return True


def load_dashboard(weeks: int, directory: Path | None = None) -> dict[str, Any] | None:
    path = cache_path(weeks, directory)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    root = (directory or DEFAULT_CACHE_DIR).resolve()
    if root == DEFAULT_CACHE_DIR.resolve() and not cache_is_usable(raw, weeks):
        return None
    return raw


def pulse_note_from_dashboard(dash: dict[str, Any]) -> PulseNote:
    """Rebuild a PulseNote from cached dashboard JSON for Gmail send."""
    pulse = dash.get("pulse")
    if not pulse:
        raise ValueError("pulse not ready yet")
    return PulseNote.model_validate(
        {
            "title": pulse["title"],
            "themes": [
                {"name": item["theme"], "summary": item.get("summary") or item["theme"]}
                for item in pulse["themes"]
            ],
            "quotes": [
                {
                    "review_id": f"q{index}",
                    "text": item["quote"],
                    "rating": item.get("rating") or 3,
                    "store": item.get("store") or "play",
                    "date": item.get("date"),
                }
                for index, item in enumerate(pulse["themes"])
            ],
            "actions": pulse["actions"],
            "body": pulse.get("body") or "",
        }
    )
