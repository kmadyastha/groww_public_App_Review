"""Local / Railway HTTP API for the dashboard. Analysis stays in pulse.run."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from pulse.config import WINDOW_WEEKS_MAX, WINDOW_WEEKS_MIN, load_config, load_pulse_dotenv
from pulse.dashboard import load_dashboard, pulse_note_from_dashboard, write_dashboard
from pulse.mail_gmail import (
    GmailNotConfigured,
    GmailSendError,
    authorization_url,
    exchange_code,
    gmail_configured,
    send_pulse,
    sender_address,
)
from pulse.run import run
from pulse.subscribers import SubscriberError, load_subscribers, normalize_email, upsert_subscriber

logger = logging.getLogger("pulse.server")
DEFAULT_RAW = Path("data/raw")

load_pulse_dotenv()

app = FastAPI(title="Groww Review Pulse", version="0.2.0")


def _cors_origins() -> list[str]:
    raw = (os.environ.get("PULSE_API_CORS") or "http://localhost:5173,http://127.0.0.1:5173").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubscribeIn(BaseModel):
    email: str
    include_quotes: bool = True
    weeks: int = Field(default=10, ge=WINDOW_WEEKS_MIN, le=WINDOW_WEEKS_MAX)


def _weeks(weeks: int) -> int:
    if not WINDOW_WEEKS_MIN <= weeks <= WINDOW_WEEKS_MAX:
        raise HTTPException(400, f"weeks must be {WINDOW_WEEKS_MIN}–{WINDOW_WEEKS_MAX}")
    return weeks


def ensure_insights(weeks: int, *, refresh: bool = False) -> dict[str, Any]:
    span = _weeks(weeks)
    if not refresh:
        cached = load_dashboard(span)
        if cached:
            return cached
    has_raw = (DEFAULT_RAW / "play_reviews.json").is_file() or (
        DEFAULT_RAW / "app_store_reviews.json"
    ).is_file()
    logger.info("Building dashboard cache for %s weeks (fetch_public=%s)", span, not has_raw)
    config = load_config()
    result = run(
        config=config,
        raw_dir=DEFAULT_RAW if has_raw else None,
        weeks=span,
        fetch_public=not has_raw,
        send_email=False,
    )
    if result.status == "failed" or result.pulse is None:
        raise HTTPException(500, "pulse run failed: " + ("; ".join(result.errors) or result.status))
    write_dashboard(result, weeks=span)
    cached = load_dashboard(span)
    if not cached:
        raise HTTPException(500, "dashboard cache was not written")
    return cached


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "pulse-api", "ui": "http://localhost:5173"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "gmail": gmail_configured(), "sender": sender_address()}


@app.get("/api/insights")
def insights(weeks: int = Query(default=10)) -> dict[str, Any]:
    return ensure_insights(weeks)


@app.post("/api/insights/refresh")
def refresh_insights(weeks: int = Query(default=10)) -> dict[str, Any]:
    return ensure_insights(weeks, refresh=True)


@app.get("/api/export.pdf")
def export_pdf(weeks: int = Query(default=10)) -> Response:
    from pulse.report_pdf import render_pulse_pdf

    data = ensure_insights(weeks)
    payload = render_pulse_pdf(data)
    name = f"groww-pulse-{data.get('iso_week', 'week')}-{data.get('year', '')}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/mail/status")
def mail_status() -> dict[str, Any]:
    return {
        "connected": gmail_configured(),
        "sender": sender_address(),
        "subscribers": len(load_subscribers()),
    }


@app.get("/api/auth/gmail")
def gmail_start() -> RedirectResponse:
    try:
        return RedirectResponse(authorization_url())
    except GmailNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/auth/gmail/callback")
def gmail_callback(code: str = Query(default="")) -> RedirectResponse:
    if not code:
        raise HTTPException(400, "missing OAuth code")
    try:
        exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Gmail OAuth exchange failed")
        raise HTTPException(400, f"Gmail OAuth failed: {exc}") from exc
    frontend = _cors_origins()[0].rstrip("/")
    return RedirectResponse(f"{frontend}/subscribe?gmail=connected")


@app.post("/api/subscribe")
def subscribe(payload: SubscribeIn) -> dict[str, Any]:
    try:
        row = upsert_subscriber(payload.email, include_quotes=payload.include_quotes)
    except SubscriberError as exc:
        raise HTTPException(400, str(exc)) from exc
    warning = None
    if not gmail_configured():
        warning = "subscribed; connect Gmail on the server before Monday send"
    return {
        "ok": True,
        "email": row["email"],
        "include_quotes": row.get("include_quotes", True),
        "sent": False,
        "message_id": None,
        "warning": warning,
        "subscribers": len(load_subscribers()),
    }


@app.post("/api/mail/send")
def send_now(payload: SubscribeIn) -> dict[str, Any]:
    try:
        address = normalize_email(payload.email)
    except SubscriberError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not gmail_configured():
        raise HTTPException(503, "connect Gmail on the server before sending")
    dash = ensure_insights(payload.weeks)
    try:
        note = pulse_note_from_dashboard(dash)
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, "pulse not ready yet") from exc
    try:
        message_id = send_pulse(note, address, include_quotes=payload.include_quotes)
    except (GmailNotConfigured, GmailSendError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "ok": True,
        "email": address,
        "include_quotes": payload.include_quotes,
        "sent": True,
        "message_id": message_id,
        "warning": None,
        "subscribers": len(load_subscribers()),
    }


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    del argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_pulse_dotenv()
    host = os.environ.get("PULSE_API_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT") or os.environ.get("PULSE_API_PORT") or "8000")
    uvicorn.run("pulse.server:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    main()
