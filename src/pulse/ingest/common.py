"""Shared ingest helpers. Public exports only — no store-login scraping."""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping

from pulse.schemas import DateWindow, RawReview, Store

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

MIN_REVIEW_WORDS = 8
_CONTENT_RE = re.compile(r"[A-Za-z0-9\u0900-\u097F]")
_HTML_RE = re.compile(r"<[^>]+>")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_NON_LATIN_LETTER_RE = re.compile(
    r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u0980-\u09FF"
    r"\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0B80-\u0BFF"
    r"\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F\u0E00-\u0E7F"
    r"\u0F00-\u0FFF\u1000-\u109F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]"
)

# Romanized Hindi/Hinglish and other Indic markers (not English).
# Any hit drops the review — mixed English+Hinglish is still non-English.
_NON_ENGLISH_TOKENS = frozenset(
    {
        "aafat",
        "abhi",
        "accha",
        "acha",
        "achha",
        "ahe",
        "apna",
        "apni",
        "aur",
        "bahut",
        "bakwaas",
        "bakwas",
        "bekar",
        "bhai",
        "bhi",
        "bilkul",
        "bohot",
        "chahiye",
        "chala",
        "dhanyavad",
        "dikkat",
        "faltu",
        "galat",
        "gaya",
        "gaye",
        "ghatiya",
        "gya",
        "gye",
        "hai",
        "hain",
        "hoga",
        "hogi",
        "hua",
        "hui",
        "huye",
        "illai",
        "inko",
        "isko",
        "isliye",
        "jaata",
        "jaate",
        "jaise",
        "jaldi",
        "jyada",
        "karna",
        "karne",
        "karo",
        "kaunsa",
        "kaunsi",
        "kiya",
        "kiye",
        "kripya",
        "krdo",
        "kro",
        "krna",
        "krne",
        "kuch",
        "kya",
        "kyun",
        "kyunki",
        "leke",
        "lekin",
        "liye",
        "magar",
        "matlab",
        "mera",
        "meri",
        "mujhe",
        "nahi",
        "nahin",
        "namaste",
        "nandri",
        "nhi",
        "pagal",
        "paise",
        "pata",
        "pehle",
        "phir",
        "raha",
        "rahe",
        "rahi",
        "romba",
        "rupay",
        "rupaye",
        "sahi",
        "shukriya",
        "theek",
        "tarah",
        "thik",
        "thoda",
        "toh",
        "tumhe",
        "undi",
        "unko",
        "usko",
        "wala",
        "wale",
        "yaar",
        "yeh",
        "zabardast",
        "zaroor",
        "zyada",
    }
)

IDENTITY_KEYS = frozenset(
    {
        "author",
        "author_name",
        "device",
        "device_id",
        "deviceid",
        "email",
        "ip",
        "name",
        "reviewer",
        "reviewer_name",
        "user",
        "user_image",
        "user_name",
        "username",
        "userimage",
        "userName",
    }
)

TEXT_KEYS = ("text", "body", "content", "review", "comment", "review_text", "review_content")
TITLE_KEYS = ("title", "heading", "review_title", "subject")
RATING_KEYS = ("rating", "stars", "star", "score", "im_rating")
DATE_KEYS = (
    "date",
    "review_date",
    "time",
    "submitted_at",
    "created_at",
    "updated",
    "updated_at",
)
ID_KEYS = ("review_id_source", "review_id", "reviewid", "id")
PACKAGE_KEYS = ("package", "package_name", "app_id", "appid", "package_id")
LOCALE_KEYS = ("locale", "language", "hl", "lang")
STORE_KEYS = ("store",)


class IngestError(ValueError):
    """Fail-closed ingest failure (empty, stale, or unreadable export)."""


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        self.chunks.append(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.chunks.append(unescape(f"&#{name};"))


def date_window(weeks: int, *, end: date | None = None) -> DateWindow:
    end_date = end or datetime.now(IST).date()
    start_date = end_date - timedelta(weeks=weeks)
    return DateWindow(start_date=start_date, end_date=end_date)


def norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        nk = norm_key(str(key))
        if not nk or nk in IDENTITY_KEYS:
            continue
        out[nk] = value
    return out


def _first(row: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def strip_html(text: str) -> str:
    if not text:
        return ""
    if "<" in text or "&" in text:
        parser = _HTMLText()
        try:
            parser.feed(text)
            text = " ".join(parser.chunks) or _HTML_RE.sub(" ", text)
        except Exception:
            text = _HTML_RE.sub(" ", text)
        text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def has_review_content(text: str) -> bool:
    return bool(_CONTENT_RE.search(text or ""))


def review_word_count(text: str) -> int:
    """Count alphabetic words (emoji/punctuation-only tokens are ignored)."""
    return len(_LATIN_WORD_RE.findall(text or "")) + len(
        re.findall(r"[\u0900-\u097F]+", text or "")
    )


def is_english_text(text: str) -> bool:
    """Keep English-only review text. Drop other scripts and Hinglish/Indic copy."""
    raw = text or ""
    if _NON_LATIN_LETTER_RE.search(raw):
        return False
    tokens = [m.group(0).lower() for m in _LATIN_WORD_RE.finditer(raw)]
    if not tokens:
        return False
    if any(token in _NON_ENGLISH_TOKENS for token in tokens):
        return False
    return True


def passes_review_quality(text: str) -> bool:
    return review_word_count(text) >= MIN_REVIEW_WORDS and is_english_text(text)


def parse_rating(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 5 else None
    if isinstance(value, float):
        if value.is_integer() and 1 <= int(value) <= 5:
            return int(value)
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        as_float = float(raw)
    except ValueError:
        return None
    if as_float.is_integer() and 1 <= int(as_float) <= 5:
        return int(as_float)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=IST)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:10], fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def to_ist_date(value: Any) -> date | None:
    dt = _parse_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(IST).date()


def read_text(path: Path) -> str:
    if not path.is_file():
        raise IngestError(f"file not found: {path}")
    blob = path.read_bytes()
    if not blob or not blob.strip():
        raise IngestError(f"empty file: {path}")
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError(f"undecodable file (need UTF-8 or UTF-16): {path}")


def rss_label(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, Mapping):
        if "label" in node:
            return str(node["label"])
        inner = node.get("attributes")
        if isinstance(inner, Mapping) and "label" in inner:
            return str(inner["label"])
    return str(node)


def flatten_rss_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    rating = rss_label(entry.get("im:rating") or entry.get("im_rating"))
    if not rating:
        return None
    content = entry.get("content")
    text = rss_label(content)
    return {
        "store": "app_store",
        "review_id_source": rss_label(entry.get("id")),
        "rating": rating,
        "title": rss_label(entry.get("title")),
        "text": text,
        "date": rss_label(entry.get("updated") or entry.get("im:releaseDate")),
        "locale": "en_IN",
    }


def entries_from_rss_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    feed = payload.get("feed")
    if not isinstance(feed, Mapping):
        raise IngestError("RSS JSON missing feed object")
    entry = feed.get("entry")
    if entry is None:
        raise IngestError("RSS JSON missing feed.entry")
    if isinstance(entry, Mapping):
        entries = [entry]
    elif isinstance(entry, list):
        entries = entry
    else:
        raise IngestError("RSS feed.entry has unknown shape")
    flattened = [row for item in entries if isinstance(item, Mapping) for row in [flatten_rss_entry(item)] if row]
    if not flattened:
        raise IngestError("RSS feed contained no review entries")
    return flattened


def _records_from_json(payload: Any, *, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        if not payload:
            raise IngestError(f"empty JSON array: {path}")
        if not isinstance(payload[0], dict):
            raise IngestError(f"JSON array must contain objects: {path}")
        return payload
    if not isinstance(payload, dict):
        raise IngestError(f"JSON must be a list or object: {path}")
    if "reviews" in payload and isinstance(payload["reviews"], list):
        if not payload["reviews"]:
            raise IngestError(f"empty reviews list: {path}")
        return payload["reviews"]
    if "feed" in payload and isinstance(payload["feed"], dict):
        return entries_from_rss_payload(payload)
    raise IngestError(f"unknown JSON schema: {path}")


def load_tabular_records(path: Path) -> list[dict[str, Any]]:
    text = read_text(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise IngestError(f"malformed JSON {path}: {exc}") from exc
        return _records_from_json(payload, path=path)
    if suffix in {".csv", ".txt"}:
        try:
            reader = csv.DictReader(StringIO(text))
            if not reader.fieldnames:
                raise IngestError(f"CSV has no header: {path}")
            if not csv_has_required_headers(reader.fieldnames):
                raise IngestError(
                    f"CSV missing required columns (rating, date, text/title): {path}"
                )
            rows = [dict(row) for row in reader]
        except csv.Error as exc:
            raise IngestError(f"malformed CSV {path}: {exc}") from exc
        if not rows:
            raise IngestError(f"header-only or empty CSV: {path}")
        return rows
    raise IngestError(f"unsupported export type {path.suffix}: {path}")


def _infer_store(row: Mapping[str, Any], default: Store | None) -> Store | None:
    raw = _first(row, STORE_KEYS)
    if raw is None:
        return default
    token = norm_key(str(raw))
    if token in {"play", "play_store", "google_play", "android"}:
        return "play"
    if token in {"app_store", "appstore", "ios", "itunes", "apple"}:
        return "app_store"
    return default


def row_to_review(
    row: Mapping[str, Any],
    *,
    default_store: Store | None,
    play_id: str,
    locale: str,
    window: DateWindow,
) -> RawReview | None:
    clean = _normalize_row(row)
    store = _infer_store(clean, default_store)
    if store is None:
        return None

    if store == "play":
        package = _first(clean, PACKAGE_KEYS)
        if package not in (None, "") and str(package).strip() != play_id:
            return None
        row_locale = _first(clean, LOCALE_KEYS)
        if row_locale not in (None, ""):
            compact = str(row_locale).strip().lower().replace("-", "_")
            if compact != locale.lower():
                return None

    rating = parse_rating(_first(clean, RATING_KEYS))
    if rating is None:
        return None

    review_date = to_ist_date(_first(clean, DATE_KEYS))
    if review_date is None:
        return None
    if review_date < window.start_date or review_date > window.end_date:
        return None

    title_raw = _first(clean, TITLE_KEYS)
    text_raw = _first(clean, TEXT_KEYS)
    title = strip_html(str(title_raw)) if title_raw not in (None, "") else None
    text = strip_html(str(text_raw)) if text_raw not in (None, "") else ""
    if not has_review_content(text) and title and has_review_content(title):
        text = title
    if not has_review_content(text):
        return None
    if not passes_review_quality(text):
        return None

    source_id = _first(clean, ID_KEYS)
    if source_id in (None, ""):
        source_id = f"{store}:{review_date.isoformat()}:{text[:48]}"
    else:
        source_id = str(source_id)

    row_locale = _first(clean, LOCALE_KEYS)
    resolved_locale = locale
    if row_locale not in (None, ""):
        resolved_locale = str(row_locale).strip().replace("-", "_")

    try:
        return RawReview(
            store=store,
            review_id_source=source_id,
            rating=rating,
            title=title or None,
            text=text,
            date=review_date,
            locale=resolved_locale,
        )
    except Exception:
        return None


def parse_records(
    records: Iterable[Mapping[str, Any]],
    *,
    window: DateWindow,
    play_id: str,
    locale: str,
    default_store: Store | None = None,
) -> list[RawReview]:
    reviews: list[RawReview] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        parsed = row_to_review(
            record,
            default_store=default_store,
            play_id=play_id,
            locale=locale,
            window=window,
        )
        if parsed is not None:
            reviews.append(parsed)
    return dedupe_reviews(reviews)


def dedupe_reviews(reviews: list[RawReview]) -> list[RawReview]:
    best: dict[tuple[str, str], RawReview] = {}
    for review in reviews:
        key = (review.store, review.review_id_source)
        previous = best.get(key)
        if previous is None or review.date > previous.date:
            best[key] = review
    return sorted(best.values(), key=lambda item: (item.date, item.store, item.review_id_source))


def csv_has_required_headers(fieldnames: Iterable[str] | None) -> bool:
    if not fieldnames:
        return False
    keys = {norm_key(name) for name in fieldnames if name}
    keys -= IDENTITY_KEYS
    has_rating = bool(keys & set(RATING_KEYS))
    has_date = bool(keys & set(DATE_KEYS))
    has_body = bool(keys & (set(TEXT_KEYS) | set(TITLE_KEYS)))
    return has_rating and has_date and has_body
