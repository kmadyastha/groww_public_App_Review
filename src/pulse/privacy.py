"""Deterministic PII redaction. Runs before any Groq/LLM call.

ClusterThemes and later nodes accept only SanitizedReview rows. Store source
ids, RSS authors, and name-like App Store titles never appear on those rows.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from pulse.ingest.common import IDENTITY_KEYS, has_review_content, norm_key
from pulse.schemas import RawReview, SanitizedReview, Store

USER_PLACEHOLDER = "[user]"
EMAIL_PLACEHOLDER = "[email]"
PHONE_PLACEHOLDER = "[phone]"
ID_PLACEHOLDER = "[id]"
HANDLE_PLACEHOLDER = "[handle]"
UPI_PLACEHOLDER = "[upi]"

STORE_LABEL: dict[Store, str] = {
    "play": "Play Store",
    "app_store": "App Store",
}

# Product / market terms that must not be treated as person names.
_ALLOW_WORDS = frozenset(
    {
        "5paisa",
        "aadhaar",
        "aadhar",
        "android",
        "angel",
        "app",
        "apple",
        "axis",
        "bse",
        "camarilla",
        "chain",
        "chart",
        "customer",
        "dhan",
        "english",
        "etf",
        "fivepaisa",
        "fund",
        "funds",
        "fyers",
        "gmail",
        "google",
        "grow",
        "groww",
        "gtt",
        "hni",
        "icloud",
        "india",
        "indian",
        "ios",
        "iphone",
        "ipo",
        "kyc",
        "mutual",
        "nse",
        "oco",
        "one",
        "option",
        "otp",
        "paisa",
        "pan",
        "paytm",
        "play",
        "rekyc",
        "sebi",
        "sensex",
        "sip",
        "smartexit",
        "store",
        "support",
        "team",
        "tpin",
        "trading",
        "tradingview",
        "upi",
        "view",
        "vtt",
        "whatsapp",
        "zerodha",
    }
)

# Single-word App Store titles that are review labels, not given names.
_TITLE_KEEP = _ALLOW_WORDS | frozenset(
    {
        "alert",
        "awesome",
        "awe",
        "best",
        "brokerage",
        "charge",
        "class",
        "deposit",
        "easy",
        "excellent",
        "experience",
        "feedback",
        "good",
        "great",
        "interface",
        "invest",
        "investing",
        "issue",
        "nice",
        "on",
        "poor",
        "secure",
        "simple",
        "stocks",
        "superb",
        "the",
        "third",
        "update",
        "user",
        "very",
        "wonderful",
        "worst",
    }
)

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
_UPI_RE = re.compile(
    r"\b[\w.-]{2,}@(?:oksbi|okhdfcbank|okicici|okaxis|okyesbank|upi|ybl|paytm|ibl|apl|axl)\b",
    re.I,
)
_PHONE_RE = re.compile(
    r"""
    (?<!\w)
    (?:
        \+91[\s\-]*[6-9]\d{4}[\s\-]*\d{5}
        | 0[6-9]\d{9}
        | [6-9]\d{9}
        | \+\d{1,3}[\s\-]?\d{2,4}[\s\-]?\d{3,4}(?:[\s\-]?\d{3,4})?
    )
    (?!\w)
    """,
    re.VERBOSE,
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_HEX_ID_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
_LONG_ID_RE = re.compile(
    r"\b(?:order|folio|client|account|ref)[\s:#-]*[A-Z0-9]{6,}\b",
    re.I,
)
_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9])@[A-Za-z][A-Za-z0-9_.]{1,30}\b")
_IOS_USER_RE = re.compile(r"\bios\.user\b", re.I)
_ITUNES_URL_RE = re.compile(r"itunes\.apple\.com/\S*", re.I)
_IOS_RSS_ID_RE = re.compile(r"\bios-rss-\d+\b", re.I)
_PERSON_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})\b")
_COURTESY_NAME_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]{2,}\b")
_TRIGGER_NAME_RE = re.compile(
    r"\b((?:call|called|agent|executive|employee|employees like|officer)\s+)([A-Z][a-z]{2,})\b",
    re.I,
)
_NAME_TOKEN_RE = re.compile(r"[A-Za-z]+")
_PLACEHOLDER_RE = re.compile(r"\[(?:user|email|phone|id|handle|upi)\]", re.I)
_MOJIBAKE_MARK = re.compile(r"[ÃÂâ�]")
_MOJIBAKE_FIXES = (
    ("ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢", "'"),
    ("Ã¢â‚¬â„¢", "'"),
    ("Ã¢â‚¬Ëœ", "'"),
    ("Ã¢â‚¬Å“", '"'),
    ("Ã¢â‚¬Â", '"'),
    ("â€™", "'"),
    ("â€˜", "'"),
    ("â€œ", '"'),
    ("â€", '"'),
    ("Ã‚", ""),
)


def _has_substance(text: str) -> bool:
    return has_review_content(_PLACEHOLDER_RE.sub(" ", text or ""))


def opaque_review_id(store: Store, source_id: str) -> str:
    """SHA-256 of store + source id. Hex prefix is not the store's raw id."""
    payload = f"{store}\0{source_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def format_attribution(*, rating: int, store: Store, on: date) -> str:
    """Quote citation: `(2★, App Store, 2026-07-20)` — never a name or store id."""
    return f"({rating}★, {STORE_LABEL[store]}, {on.isoformat()})"


def drop_identity_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Strip author/email/device keys, including nested RSS `author.name`."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == "author" or norm_key(str(key)) in IDENTITY_KEYS:
            continue
        if isinstance(value, Mapping):
            out[key] = drop_identity_fields(value)
        else:
            out[key] = value
    return out


def repair_text_encoding(text: str) -> str:
    """Undo common RSS/UTF-8 mojibake (`Ã¢â‚¬â„¢` → apostrophe) without an LLM."""
    if not text:
        return ""
    current = text
    for src, dst in _MOJIBAKE_FIXES:
        current = current.replace(src, dst)
    for _ in range(3):
        if not _MOJIBAKE_MARK.search(current):
            break
        try:
            fixed = current.encode("latin-1").decode("utf-8")
        except UnicodeError:
            break
        if fixed == current:
            break
        current = fixed
    cleaned = current.replace("\ufffd", " ")
    return unicodedata.normalize("NFC", cleaned)


def is_name_like_title(title: str | None) -> bool:
    """True for personal-name titles such as `Pradeep Sholapurkar` or `Kishor`."""
    if not title or not title.strip():
        return False
    tokens = _NAME_TOKEN_RE.findall(title)
    if not tokens or len(tokens) > 3:
        return False
    lowered = {token.lower() for token in tokens}
    if lowered & _TITLE_KEEP:
        return False
    if not all(re.fullmatch(r"[A-Z][a-z]+", token) for token in tokens):
        return False
    if len(tokens) >= 2:
        return True
    return len(tokens[0]) >= 3


def _keep_name_phrase(phrase: str) -> bool:
    return any(token.lower() in _ALLOW_WORDS for token in phrase.split())


def _redact_person_names(text: str) -> str:
    def replace_phrase(match: re.Match[str]) -> str:
        phrase = match.group(0)
        if _keep_name_phrase(phrase):
            return phrase
        return USER_PLACEHOLDER

    text = _PERSON_NAME_RE.sub(replace_phrase, text)
    text = _COURTESY_NAME_RE.sub(USER_PLACEHOLDER, text)

    def replace_trigger(match: re.Match[str]) -> str:
        lead, name = match.group(1), match.group(2)
        if name.lower() in _ALLOW_WORDS:
            return match.group(0)
        return f"{lead}{USER_PLACEHOLDER}"

    return _TRIGGER_NAME_RE.sub(replace_trigger, text)


def sanitize_text(text: str | None) -> str:
    raw = repair_text_encoding(text or "")
    raw = _EMAIL_RE.sub(EMAIL_PLACEHOLDER, raw)
    raw = _UPI_RE.sub(UPI_PLACEHOLDER, raw)
    raw = _PHONE_RE.sub(PHONE_PLACEHOLDER, raw)
    raw = _UUID_RE.sub(ID_PLACEHOLDER, raw)
    raw = _HEX_ID_RE.sub(ID_PLACEHOLDER, raw)
    raw = _PAN_RE.sub(ID_PLACEHOLDER, raw)
    raw = _AADHAAR_RE.sub(ID_PLACEHOLDER, raw)
    raw = _LONG_ID_RE.sub(ID_PLACEHOLDER, raw)
    raw = _HANDLE_RE.sub(HANDLE_PLACEHOLDER, raw)
    raw = _IOS_USER_RE.sub(USER_PLACEHOLDER, raw)
    raw = _redact_person_names(raw)
    return re.sub(r"\s+", " ", raw).strip()


def sanitize_review(review: RawReview) -> SanitizedReview | None:
    title_raw = repair_text_encoding(review.title or "")
    text = sanitize_text(review.text)
    if is_name_like_title(title_raw):
        title = None
    else:
        title = sanitize_text(title_raw) or None
    if not _has_substance(text) and title and _has_substance(title):
        text = title
        title = None
    if not _has_substance(text):
        return None
    return SanitizedReview(
        review_id=opaque_review_id(review.store, review.review_id_source),
        store=review.store,
        rating=review.rating,
        title=title,
        text=text,
        date=review.date,
        locale=review.locale,
    )


def leak_labels(text: str, *, extra_needles: Sequence[str] = ()) -> list[str]:
    """Labels for PII / store-id leaks in pulse prose. Empty means the text is clean."""
    blob = text or ""
    hits: list[str] = []
    if _EMAIL_RE.search(blob):
        hits.append("email")
    if _PHONE_RE.search(blob):
        hits.append("phone")
    if _IOS_USER_RE.search(blob):
        hits.append("ios.user")
    if _HANDLE_RE.search(blob):
        hits.append("handle")
    if _ITUNES_URL_RE.search(blob):
        hits.append("itunes-url")
    if _IOS_RSS_ID_RE.search(blob):
        hits.append("itunes-review-id")
    for needle in extra_needles:
        raw = (needle or "").strip()
        if raw and raw in blob:
            hits.append(f"source-id:{raw}")
    return hits


def sanitize_reviews(reviews: Iterable[RawReview]) -> list[SanitizedReview]:
    """Map RawReview → SanitizedReview. Rows that are empty after redaction are dropped."""
    out: list[SanitizedReview] = []
    for review in reviews:
        sanitized = sanitize_review(review)
        if sanitized is not None:
            out.append(sanitized)
    return out
