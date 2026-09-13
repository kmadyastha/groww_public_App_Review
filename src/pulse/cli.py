"""CLI: `pulse ingest --out data/raw`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from pulse.config import WINDOW_WEEKS_MAX, WINDOW_WEEKS_MIN, load_config
from pulse.ingest import IngestError, date_window, load_reviews, write_reviews


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse",
        description="Groww weekly review pulse (ingest, run, weekly send, API server).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Generate the pulse (add --send to mail operator.email)")
    sub.add_parser("weekly", help="Fetch, classify, write snapshot; send via Gmail plugin when hooked")
    sub.add_parser("serve", help="Run the dashboard API (FastAPI) for local or Railway")

    ingest = sub.add_parser(
        "ingest",
        help="Download public Play + App Store reviews (no credentials) into data/raw/",
    )
    ingest.add_argument(
        "--play",
        type=Path,
        help="Play Store CSV/JSON export (default: data/raw/play_reviews.csv|json)",
    )
    ingest.add_argument(
        "--app-store",
        type=Path,
        help="Saved App Store JSON export (default: data/raw/app_store_reviews.json)",
    )
    ingest.add_argument(
        "--raw-dir",
        type=Path,
        help="Directory to search for play_reviews.* and app_store_reviews.json",
    )
    ingest.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory for ingested.json (default: data/raw/)",
    )
    ingest.add_argument(
        "--fetch-rss",
        action="store_true",
        help="Fetch public iTunes RSS even if a local App Store file exists",
    )
    ingest.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not call public store APIs; only read local files",
    )
    ingest.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download public listings even if data/raw files already exist",
    )
    ingest.add_argument("--weeks", type=int, help="Lookback weeks (8–12). Default: config")
    ingest.add_argument(
        "--end-date",
        type=_parse_date,
        help="Window end date YYYY-MM-DD in IST (default: today IST)",
    )
    return parser


_COMMANDS = {
    "run": "pulse.run",
    "weekly": "pulse.weekly",
    "schedule": "pulse.schedule",
    "serve": "pulse.server",
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _COMMANDS:
        module = __import__(_COMMANDS[argv[0]], fromlist=["main"])
        return int(module.main(argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "ingest":
        parser.error(f"unknown command {args.command}")
        return 2
    try:
        config = load_config()
        weeks = args.weeks if args.weeks is not None else config.window.weeks
        if not WINDOW_WEEKS_MIN <= weeks <= WINDOW_WEEKS_MAX:
            raise IngestError(f"weeks must be {WINDOW_WEEKS_MIN}–{WINDOW_WEEKS_MAX}")
        window = date_window(weeks, end=args.end_date)
        raw_dir = args.raw_dir
        out_dir = args.out or raw_dir or Path("data/raw")
        fetch_public = not args.no_fetch
        reviews = load_reviews(
            window,
            config=config,
            play_path=args.play,
            app_store_path=args.app_store,
            raw_dir=raw_dir,
            fetch_rss=args.fetch_rss or fetch_public,
            fetch_public=fetch_public,
            refresh=args.refresh,
        )
        out_path = write_reviews(reviews, out_dir)
    except (IngestError, ValueError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1
    stores = sorted({row.store for row in reviews})
    print(f"wrote {len(reviews)} reviews ({', '.join(stores)}) to {out_path}")
    print(f"window {window.start_date.isoformat()} .. {window.end_date.isoformat()} (inclusive, IST)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
