"""Google Play reviews from the public listing (no login, no Play Console).

Prefers the ``google-play-scraper`` library; falls back to the same public
``batchexecute`` RPC the Play web UI uses.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pulse.config import AppConfig
from pulse.ingest.common import IngestError, load_tabular_records, parse_records
from pulse.schemas import DateWindow, RawReview

logger = logging.getLogger("pulse.ingest")

PLAY_FILENAMES = (
    "play_reviews.csv",
    "play_reviews.json",
    "play.csv",
    "play.json",
)

PLAY_RPC_ID = "oCPfdb"
PLAY_SORT_NEWEST = 2
PLAY_PAGE_SIZE = 200
PLAY_MAX_PAGES = 80
_BATCH_PREFIX = re.compile(r"^\)\]\}'\s*")


def discover_play_export(raw_dir: Path) -> Path | None:
    if not raw_dir.is_dir():
        return None
    for name in PLAY_FILENAMES:
        candidate = raw_dir / name
        if candidate.is_file():
            return candidate
    return None


def load_play_reviews(
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
        default_store="play",
    )


def scraper_item_to_record(item: dict[str, Any], *, play_id: str, locale: str) -> dict[str, Any]:
    """Map a google-play-scraper review dict. Drops userName / images."""
    at = item.get("at")
    if isinstance(at, datetime):
        day = at.date().isoformat()
    else:
        day = str(at)[:10]
    return {
        "store": "play",
        "review_id_source": str(item.get("reviewId") or item.get("review_id") or ""),
        "rating": item.get("score") or item.get("rating"),
        "title": None,
        "text": item.get("content") or item.get("text") or "",
        "date": day,
        "locale": locale,
        "package": play_id,
    }


def fetch_play_reviews(
    *,
    window: DateWindow,
    config: AppConfig,
) -> list[RawReview]:
    """Download newest public Play reviews until `window.start_date`."""
    try:
        records = _fetch_via_google_play_scraper(window=window, config=config)
        logger.info("Play reviews fetched with google-play-scraper (%s rows)", len(records))
    except ImportError:
        records = _fetch_via_batchexecute(window=window, config=config)
        logger.info("Play reviews fetched with public batchexecute RPC (%s rows)", len(records))
    parsed = parse_records(
        records,
        window=window,
        play_id=config.product.play_id,
        locale=config.product.play_hl,
        default_store="play",
    )
    if not parsed:
        raise IngestError("Play public listing returned no reviews in the date window")
    return parsed


def _fetch_via_google_play_scraper(*, window: DateWindow, config: AppConfig) -> list[dict[str, Any]]:
    from google_play_scraper import Sort, reviews as gp_reviews

    records: list[dict[str, Any]] = []
    continuation = None
    past_start = False
    pages = 0
    while not past_start and pages < PLAY_MAX_PAGES:
        pages += 1
        batch, continuation = gp_reviews(
            config.product.play_id,
            lang="en",
            country="in",
            sort=Sort.NEWEST,
            count=PLAY_PAGE_SIZE,
            continuation_token=continuation,
        )
        if not batch:
            break
        for item in batch:
            at = item.get("at")
            day = at.date() if isinstance(at, datetime) else None
            if day is not None and day < window.start_date:
                past_start = True
                continue
            records.append(
                scraper_item_to_record(
                    item,
                    play_id=config.product.play_id,
                    locale=config.product.play_hl,
                )
            )
        token = getattr(continuation, "token", None) if continuation is not None else None
        if not token:
            break
        time.sleep(0.25)
    return records


def _play_url(lang: str, country: str) -> str:
    return f"https://play.google.com/_/PlayStoreUi/data/batchexecute?hl={lang}&gl={country}"


def _play_body(app_id: str, count: int, token: str | None) -> bytes:
    if token:
        template = (
            "f.req=%5B%5B%5B%22oCPfdb%22%2C%22%5Bnull%2C%5B2%2C{sort}%2C%5B{count}%2Cnull%2C"
            "%5C%22{token}%5C%22%5D%2Cnull%2C%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2C"
            "null%2Cnull%2Cnull%5D%5D%2C%5B%5C%22{app_id}%5C%22%2C7%5D%5D%22%2Cnull%2C"
            "%22generic%22%5D%5D%5D%0A"
        )
        return template.format(sort=PLAY_SORT_NEWEST, count=count, token=token, app_id=app_id).encode()
    template = (
        "f.req=%5B%5B%5B%22oCPfdb%22%2C%22%5Bnull%2C%5B2%2C{sort}%2C%5B{count}%5D%2Cnull%2C"
        "%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%5D%5D%2C"
        "%5B%5C%22{app_id}%5C%22%2C7%5D%5D%22%2Cnull%2C%22generic%22%5D%5D%5D%0A"
    )
    return template.format(sort=PLAY_SORT_NEWEST, count=count, app_id=app_id).encode()


def _parse_batchexecute(dom: str) -> tuple[list[list[Any]], str | None]:
    text = _BATCH_PREFIX.sub("", dom.lstrip())
    start = text.find("[")
    if start < 0:
        raise IngestError("Play listing response was not JSON")
    outer = json.loads(text[start:])
    payload = None
    frames = outer if isinstance(outer, list) else [outer]
    for frame in frames:
        if not isinstance(frame, list) or len(frame) < 3:
            continue
        if frame[1] == PLAY_RPC_ID and isinstance(frame[2], str):
            payload = json.loads(frame[2])
            break
    if payload is None:
        raise IngestError("Play listing missing review payload")
    items = payload[0] if payload and isinstance(payload[0], list) else []
    token: str | None = None
    try:
        raw_token = payload[-2][-1]
        if isinstance(raw_token, str):
            token = raw_token
    except (IndexError, TypeError):
        token = None
    return items, token


def _item_to_record(row: list[Any], *, play_id: str, locale: str) -> dict[str, Any] | None:
    try:
        review_id = row[0]
        rating = row[2]
        text = row[4] or ""
        ts = row[5][0]
    except (IndexError, TypeError):
        return None
    day = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    return {
        "store": "play",
        "review_id_source": str(review_id),
        "rating": rating,
        "title": None,
        "text": str(text),
        "date": day,
        "locale": locale,
        "package": play_id,
    }


def _fetch_via_batchexecute(*, window: DateWindow, config: AppConfig) -> list[dict[str, Any]]:
    url = _play_url("en", "in")
    token: str | None = None
    records: list[dict[str, Any]] = []
    past_start = False
    pages = 0
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (compatible; GrowwWeeklyPulse/0.1)",
    }
    while not past_start and pages < PLAY_MAX_PAGES:
        pages += 1
        body = _play_body(config.product.play_id, PLAY_PAGE_SIZE, token)
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                dom = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise IngestError(f"Play public listing request failed: {exc}") from exc
        items, token = _parse_batchexecute(dom)
        if not items:
            break
        for row in items:
            if not isinstance(row, list):
                continue
            rec = _item_to_record(
                row,
                play_id=config.product.play_id,
                locale=config.product.play_hl,
            )
            if rec is None:
                continue
            if rec["date"] < window.start_date.isoformat():
                past_start = True
                continue
            records.append(rec)
        if not token:
            break
        time.sleep(0.25)
    return records
