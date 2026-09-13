"""Gmail API send as the operator mailbox. Isolated from analysis/PII code.

OAuth secrets live in env / data/gmail_token.json (gitignored). Railway can
set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from pulse.config import load_config, load_pulse_dotenv
from pulse.schemas import PulseNote

logger = logging.getLogger("pulse.mail")

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = REPO_ROOT / "data" / "gmail_token.json"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GmailNotConfigured(RuntimeError):
    """OAuth client or refresh token missing."""


class GmailSendError(RuntimeError):
    """Gmail API rejected the send."""


def sender_address() -> str:
    load_pulse_dotenv()
    override = (os.environ.get("GMAIL_SENDER") or "").strip()
    if override:
        return override
    return load_config().operator.email


def gmail_configured() -> bool:
    load_pulse_dotenv()
    if not (os.environ.get("GMAIL_CLIENT_ID") and os.environ.get("GMAIL_CLIENT_SECRET")):
        return False
    if (os.environ.get("GMAIL_REFRESH_TOKEN") or "").strip():
        return True
    return TOKEN_PATH.is_file()


def redirect_uri() -> str:
    load_pulse_dotenv()
    return (
        os.environ.get("GMAIL_REDIRECT_URI")
        or "http://localhost:8000/api/auth/gmail/callback"
    ).strip()


def _client_config() -> dict[str, Any]:
    load_pulse_dotenv()
    client_id = (os.environ.get("GMAIL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GMAIL_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise GmailNotConfigured("set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri()],
        }
    }


def authorization_url() -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        _client_config(), scopes=[SEND_SCOPE], redirect_uri=redirect_uri()
    )
    url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url


def exchange_code(code: str) -> None:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        _client_config(), scopes=[SEND_SCOPE], redirect_uri=redirect_uri()
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(
        json.dumps(
            {
                "refresh_token": creds.refresh_token,
                "token": creds.token,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or [SEND_SCOPE]),
            }
        ),
        encoding="utf-8",
    )


def _credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    load_pulse_dotenv()
    client_id = (os.environ.get("GMAIL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GMAIL_CLIENT_SECRET") or "").strip()
    refresh = (os.environ.get("GMAIL_REFRESH_TOKEN") or "").strip()
    token = None
    if TOKEN_PATH.is_file():
        stored = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        refresh = refresh or str(stored.get("refresh_token") or "")
        token = stored.get("token")
        client_id = client_id or str(stored.get("client_id") or "")
        client_secret = client_secret or str(stored.get("client_secret") or "")
    if not (client_id and client_secret and refresh):
        raise GmailNotConfigured("Gmail OAuth is not connected")
    creds = Credentials(
        token=token,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[SEND_SCOPE],
    )
    if not creds.valid:
        creds.refresh(Request())
    return creds


def pulse_email_bodies(note: PulseNote, *, include_quotes: bool) -> tuple[str, str]:
    subject = note.title
    lines = [
        "Hello,",
        "",
        f"Here is the weekly Groww review pulse ({note.title}).",
        "",
    ]
    if include_quotes:
        for index, (theme, quote) in enumerate(zip(note.themes, note.quotes), start=1):
            lines.append(f"{index}. {theme.name}")
            lines.append(f"   “{quote.text}”")
            lines.append("")
    else:
        for index, theme in enumerate(note.themes, start=1):
            lines.append(f"{index}. {theme.name} — {theme.summary}")
        lines.append("")
    lines.append("Actions")
    for idea in note.actions:
        lines.append(f"- {idea.title} ({idea.owner_hint}): {idea.rationale}")
    lines.append("")
    lines.append("— Groww Weekly Review Pulse")
    return subject, "\n".join(lines)


def send_gmail(to: str, subject: str, body: str) -> str:
    """Send from the connected Gmail account. Returns Gmail message id."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    sender = sender_address()
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    try:
        service = build("gmail", "v1", credentials=_credentials(), cache_discovery=False)
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
    except HttpError as exc:
        raise GmailSendError(str(exc)) from exc
    message_id = str(sent.get("id") or "sent")
    logger.info("Gmail sent to %s id=%s", to, message_id)
    return message_id


def send_pulse(note: PulseNote, to: str, *, include_quotes: bool = True) -> str:
    subject, body = pulse_email_bodies(note, include_quotes=include_quotes)
    return send_gmail(to, subject, body)


def deliver_to_subscribers(note: PulseNote, subscribers: list[dict[str, Any]]) -> dict[str, Any]:
    sent = 0
    errors: list[str] = []
    for row in subscribers:
        address = str(row.get("email") or "").strip()
        if not address:
            continue
        try:
            send_pulse(note, address, include_quotes=bool(row.get("include_quotes", True)))
            sent += 1
        except (GmailNotConfigured, GmailSendError, OSError) as exc:
            errors.append(f"{address}: {exc}")
            logger.warning("Gmail fan-out failed for %s: %s", address, exc)
    return {"attempted": len(subscribers), "sent": sent, "errors": errors}
