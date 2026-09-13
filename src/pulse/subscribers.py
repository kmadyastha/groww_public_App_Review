"""Local subscriber list for weekly Gmail delivery. No PII from store reviews."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "data" / "subscribers.json"

_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class SubscriberError(ValueError):
    """Invalid subscribe request."""


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not _EMAIL.match(email) or ".." in email:
        raise SubscriberError("enter a valid email address")
    return email


def load_subscribers(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DEFAULT_PATH
    if not target.is_file():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict) and row.get("email"):
            out.append(row)
    return out


def save_subscribers(rows: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or DEFAULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def upsert_subscriber(
    email: str,
    *,
    include_quotes: bool = True,
    path: Path | None = None,
) -> dict[str, Any]:
    address = normalize_email(email)
    rows = load_subscribers(path)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for row in rows:
        if str(row.get("email", "")).lower() == address:
            row["include_quotes"] = bool(include_quotes)
            row["updated_at"] = now
            save_subscribers(rows, path)
            return row
    created = {
        "email": address,
        "include_quotes": bool(include_quotes),
        "created_at": now,
    }
    rows.append(created)
    save_subscribers(rows, path)
    return created
