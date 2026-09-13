"""Load public Play Store and App Store reviews into RawReview rows."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pulse.config import AppConfig, load_config
from pulse.ingest.app_store import (
    discover_app_store_export,
    fetch_app_store_rss,
    load_app_store_reviews,
)
from pulse.ingest.common import IngestError, date_window, dedupe_reviews
from pulse.ingest.play_store import discover_play_export, fetch_play_reviews, load_play_reviews
from pulse.schemas import DateWindow, RawReview

logger = logging.getLogger("pulse.ingest")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"


def resolve_raw_dir(raw_dir: Path | None = None) -> Path:
    if raw_dir is not None:
        return raw_dir
    cwd_raw = Path.cwd() / "data" / "raw"
    if cwd_raw.is_dir():
        return cwd_raw
    return DEFAULT_RAW_DIR


def load_reviews(
    window: DateWindow,
    *,
    config: AppConfig | None = None,
    play_path: Path | None = None,
    app_store_path: Path | None = None,
    raw_dir: Path | None = None,
    fetch_rss: bool = False,
    fetch_public: bool = False,
    refresh: bool = False,
) -> list[RawReview]:
    """Merge Play + App Store public reviews for `window`. Fail closed if none remain.

    When ``fetch_public`` is true, downloads public listings (no store login)
    if a local export is missing. ``refresh`` re-downloads even if files exist.
    """
    cfg = config or load_config()
    directory = resolve_raw_dir(raw_dir)
    play_file = None if refresh else (play_path or discover_play_export(directory))
    app_file = None if refresh else (app_store_path or discover_app_store_export(directory))

    play_reviews: list[RawReview] = []
    app_reviews: list[RawReview] = []
    play_error: IngestError | None = None
    app_error: IngestError | None = None
    attempted = False

    if play_file is not None:
        attempted = True
        try:
            play_reviews = load_play_reviews(play_file, window=window, config=cfg)
        except IngestError as exc:
            play_error = exc
            logger.warning("Play export failed: %s", exc)
    elif fetch_public:
        attempted = True
        try:
            play_reviews = fetch_play_reviews(window=window, config=cfg)
            write_reviews(play_reviews, directory, filename="play_reviews.json")
        except IngestError as exc:
            play_error = exc
            logger.warning("Play public listing failed: %s", exc)

    if app_file is not None:
        attempted = True
        try:
            app_reviews = load_app_store_reviews(app_file, window=window, config=cfg)
        except IngestError as exc:
            app_error = exc
            logger.warning("App Store export failed: %s", exc)
    elif fetch_public or fetch_rss:
        attempted = True
        try:
            app_reviews = fetch_app_store_rss(window=window, config=cfg)
            write_reviews(app_reviews, directory, filename="app_store_reviews.json")
        except IngestError as exc:
            app_error = exc
            logger.warning("App Store RSS failed: %s", exc)

    merged = dedupe_reviews(play_reviews + app_reviews)
    if merged:
        if app_error and play_reviews:
            logger.warning("Continuing with Play reviews only")
        if play_error and app_reviews:
            logger.warning("Continuing with App Store reviews only")
        return merged

    if not attempted:
        raise IngestError(
            "no public reviews found. Re-run with fetch enabled "
            "(`python -m pulse ingest`) — no Play Console login required."
        )
    if play_error and app_file is None and not fetch_rss and not fetch_public:
        raise play_error
    if app_error and play_file is None and not fetch_public:
        raise app_error
    if play_error and app_error:
        raise IngestError(f"{play_error}; {app_error}")
    raise IngestError(
        "no reviews in the date window after filters (empty or stale public export)"
    )


def write_reviews(
    reviews: list[RawReview],
    out_dir: Path,
    filename: str = "ingested.json",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    payload = [review.model_dump(mode="json") for review in reviews]
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


__all__ = [
    "IngestError",
    "date_window",
    "load_reviews",
    "write_reviews",
]
