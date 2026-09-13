"""App Store reviews from the official public RSS/JSON feed or a saved export.

Feed: https://itunes.apple.com/in/rss/customerreviews/id={app_id}/sortBy=mostRecent/json
The public RSS is typically a recent page only; prefer a saved export for 8–12 weeks.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from pulse.config import AppConfig
from pulse.ingest.common import (
    IngestError,
    entries_from_rss_payload,
    load_tabular_records,
    parse_records,
)
from pulse.schemas import DateWindow, RawReview

logger = logging.getLogger("pulse.ingest")

APP_STORE_FILENAMES = (
    "app_store_reviews.json",
    "app_store.json",
    "appstore.json",
    "itunes.json",
)
RSS_TIMEOUT_SEC = 15
RSS_MAX_PAGES = 10


def app_store_id_configured(app_store_id: str) -> bool:
    token = (app_store_id or "").strip()
    return bool(token) and token.upper() != "PLACEHOLDER" and token.isdigit()


def rss_url(app_store_id: str, *, country: str = "in", page: int = 1) -> str:
    if page <= 1:
        return (
            f"https://itunes.apple.com/{country}/rss/customerreviews/"
            f"id={app_store_id}/sortBy=mostRecent/json"
        )
    return (
        f"https://itunes.apple.com/{country}/rss/customerreviews/"
        f"page={page}/id={app_store_id}/sortBy=mostRecent/json"
    )


def discover_app_store_export(raw_dir: Path) -> Path | None:
    if not raw_dir.is_dir():
        return None
    for name in APP_STORE_FILENAMES:
        candidate = raw_dir / name
        if candidate.is_file():
            return candidate
    return None


def load_app_store_reviews(
    path: Path,
    *,
    window: DateWindow,
    config: AppConfig,
) -> list[RawReview]:
    records = load_tabular_records(path)
    return parse_records(
        records,
        window=window,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
        default_store="app_store",
    )


def _fetch_rss_page(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GrowwWeeklyPulse/0.1 (public iTunes RSS)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=RSS_TIMEOUT_SEC) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise IngestError(f"App Store RSS request failed: {exc}") from exc
    except TimeoutError as exc:
        raise IngestError("App Store RSS timed out") from exc
    except json.JSONDecodeError as exc:
        raise IngestError(f"App Store RSS was not JSON: {exc}") from exc


def fetch_app_store_rss(
    *,
    window: DateWindow,
    config: AppConfig,
    country: str = "in",
) -> list[RawReview]:
    app_id = config.product.app_store_id
    if not app_store_id_configured(app_id):
        raise IngestError("app_store_id is not set; cannot fetch public RSS")
    records: list[dict] = []
    for page in range(1, RSS_MAX_PAGES + 1):
        url = rss_url(app_id, country=country, page=page)
        try:
            payload = _fetch_rss_page(url)
            records.extend(entries_from_rss_payload(payload))
        except IngestError as exc:
            if page == 1:
                raise
            logger.warning("App Store RSS page %s skipped: %s", page, exc)
            break
    logger.info(
        "App Store public RSS returned %s review rows (Apple caps ~500 per storefront)",
        len(records),
    )
    parsed = parse_records(
        records,
        window=window,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
        default_store="app_store",
    )
    if not parsed:
        raise IngestError("App Store RSS returned no reviews in the date window")
    return parsed
