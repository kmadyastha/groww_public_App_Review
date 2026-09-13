"""Weekly job: fetch reviews, generate pulse; send via this project's Gmail plugin when hooked."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from pulse.config import WINDOW_WEEKS_MAX, WINDOW_WEEKS_MIN, load_config, load_pulse_dotenv
from pulse.graph import IntelligenceHooks
from pulse.run import run
from pulse.snapshot import resolve_snapshot_dir
from pulse.state import PulseState
from pulse.write import word_count

DEFAULT_RAW_DIR = Path("data/raw")


def run_weekly(
    *,
    weeks: int | None = None,
    end: date | None = None,
    fetch: bool = True,
    send: bool = True,
    raw_dir: Path | None = None,
    snapshot_dir: Path | None = None,
    hooks: IntelligenceHooks | None = None,
) -> PulseState:
    """Download (optional), classify, publish Doc, and send mail to operator.email."""
    cfg = load_config()
    span = weeks if weeks is not None else cfg.window.weeks
    if not WINDOW_WEEKS_MIN <= span <= WINDOW_WEEKS_MAX:
        raise ValueError(f"weeks must be {WINDOW_WEEKS_MIN}–{WINDOW_WEEKS_MAX}")
    return run(
        config=cfg,
        raw_dir=raw_dir or DEFAULT_RAW_DIR,
        weeks=span,
        end=end,
        fetch_public=fetch,
        snapshot_dir=snapshot_dir if snapshot_dir is not None else resolve_snapshot_dir(),
        hooks=hooks,
        send_email=send,
    )


def format_weekly_result(result: PulseState, *, operator_email: str) -> str:
    lines = [
        f"run_id={result.run_id} status={result.status} reviews={len(result.reviews)}",
        f"window {result.window.start_date.isoformat()} .. {result.window.end_date.isoformat()}",
    ]
    if result.pulse is not None:
        lines.append(f"pulse={result.pulse.title}")
        lines.append("themes=" + "; ".join(row.name for row in result.pulse.themes))
        lines.append(f"words={word_count(result.pulse.body)}")
    if result.snapshot_path:
        lines.append(f"snapshot={result.snapshot_path}")
    if result.doc is not None:
        lines.append(f"doc={result.doc.url}")
    if result.email is not None and result.email.sent:
        lines.append(f"email=sent to={operator_email} message={result.email.message_id}")
    elif result.email is not None:
        lines.append(f"email=draft {result.email.draft_id} (not sent)")
    else:
        lines.append("email=not delivered")
    for warning in result.warnings:
        lines.append(f"warning: {warning}")
    for err in result.errors:
        lines.append(f"error: {err}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse.weekly",
        description="Fetch, classify, cache the dashboard, and email Gmail subscribers.",
    )
    parser.add_argument("--weeks", type=int, help="Lookback weeks (8–12)")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Window end YYYY-MM-DD IST")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Use existing data/raw files; do not download",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Create a Gmail draft instead of sending",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_pulse_dotenv()
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        result = run_weekly(
            weeks=args.weeks,
            end=args.end_date,
            fetch=not args.no_fetch,
            send=not args.no_send,
            raw_dir=args.raw_dir,
        )
    except (ValueError, OSError) as exc:
        print(f"weekly job failed: {exc}", file=sys.stderr)
        return 1
    print(format_weekly_result(result, operator_email=config.operator.email))
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
