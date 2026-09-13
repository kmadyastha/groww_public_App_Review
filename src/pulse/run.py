"""CLI entry: `python -m pulse.run` -- weekly pulse; MCP delivery when enabled."""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import date
from pathlib import Path

from pulse.config import WINDOW_WEEKS_MAX, WINDOW_WEEKS_MIN, AppConfig, load_config, load_pulse_dotenv
from pulse.graph import IntelligenceHooks, compile_pulse_graph, invoke_pulse
from pulse.ingest import date_window
from pulse.schemas import ProductInfo
from pulse.snapshot import resolve_snapshot_dir
from pulse.state import PulseState
from pulse.validate import MAX_WRITE_ATTEMPTS
from pulse.write import word_count


def product_from_config(config: AppConfig) -> ProductInfo:
    return ProductInfo(
        name=config.product.name,
        android_id=config.product.play_id,
        ios_id=config.product.app_store_id,
        locale=config.product.play_hl,
    )


def initial_state(
    config: AppConfig,
    *,
    weeks: int | None = None,
    end: date | None = None,
    run_id: str | None = None,
) -> PulseState:
    span = weeks if weeks is not None else config.window.weeks
    window = date_window(span, end=end)
    return PulseState(
        run_id=run_id or uuid.uuid4().hex[:12],
        window=window,
        product=product_from_config(config),
        status="loading",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse.run",
        description="Run the Groww weekly pulse graph (local snapshot; MCP Docs/Gmail when enabled).",
    )
    parser.add_argument("--play", type=Path, help="Play JSON/CSV export")
    parser.add_argument("--app-store", type=Path, help="App Store JSON or RSS export")
    parser.add_argument("--raw-dir", type=Path, help="Directory with data/raw exports")
    parser.add_argument("--weeks", type=int, help="Lookback weeks (8–12)")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Window end YYYY-MM-DD IST")
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Download public listings if local files are missing",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        help="Directory for data/snapshots/{run_id}.md (default: data/snapshots)",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Do not write a local markdown snapshot",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the pulse via Gmail API to saved subscribers (From: operator Gmail).",
    )
    return parser


def run(
    *,
    config: AppConfig | None = None,
    play_path: Path | None = None,
    app_store_path: Path | None = None,
    raw_dir: Path | None = None,
    weeks: int | None = None,
    end: date | None = None,
    fetch_public: bool = False,
    visited: list[str] | None = None,
    state: PulseState | None = None,
    hooks: IntelligenceHooks | None = None,
    max_write_attempts: int | None = None,
    snapshot_dir: Path | None = None,
    send_email: bool = False,
) -> PulseState:
    cfg = config or load_config()
    start = state or initial_state(cfg, weeks=weeks, end=end)
    graph = compile_pulse_graph(
        config=cfg,
        play_path=play_path,
        app_store_path=app_store_path,
        raw_dir=raw_dir,
        fetch_public=fetch_public,
        visited=visited,
        hooks=hooks,
        max_write_attempts=max_write_attempts if max_write_attempts is not None else MAX_WRITE_ATTEMPTS,
        snapshot_dir=snapshot_dir,
        send_email=send_email,
    )
    result = invoke_pulse(graph, start)
    span = weeks if weeks is not None else cfg.window.weeks
    if result.pulse is not None and result.validation_passed:
        from pulse.dashboard import write_dashboard

        write_dashboard(result, weeks=span)
        if send_email:
            from pulse.mail_gmail import deliver_to_subscribers, gmail_configured
            from pulse.subscribers import load_subscribers

            if gmail_configured() and result.pulse is not None:
                deliver_to_subscribers(result.pulse, load_subscribers())
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_pulse_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config()
        weeks = args.weeks if args.weeks is not None else config.window.weeks
        if not WINDOW_WEEKS_MIN <= weeks <= WINDOW_WEEKS_MAX:
            raise ValueError(f"weeks must be {WINDOW_WEEKS_MIN}–{WINDOW_WEEKS_MAX}")
        snap_dir = None if args.no_snapshot else (args.snapshot_dir or resolve_snapshot_dir())
        result = run(
            config=config,
            play_path=args.play,
            app_store_path=args.app_store,
            raw_dir=args.raw_dir,
            weeks=weeks,
            end=args.end_date,
            fetch_public=args.fetch,
            snapshot_dir=snap_dir,
            send_email=args.send,
        )
    except (ValueError, OSError) as exc:
        print(f"pulse run failed: {exc}", file=sys.stderr)
        return 1
    stores = sorted({row.store for row in result.reviews})
    print(f"run_id={result.run_id} status={result.status} reviews={len(result.reviews)}")
    if stores:
        print(f"stores={', '.join(stores)}")
    print(
        f"window {result.window.start_date.isoformat()} .. {result.window.end_date.isoformat()}"
    )
    print(f"app_store_id={result.product.ios_id}")
    if result.clusters:
        mix = "; ".join(f"{row.name} ({row.count})" for row in result.clusters)
        print(f"clusters={mix}")
    if result.pulse is not None:
        print(f"pulse={result.pulse.title}")
        print("themes=" + "; ".join(row.name for row in result.pulse.themes))
        print(f"words={word_count(result.pulse.body)}")
    if result.snapshot_path:
        print(f"snapshot={result.snapshot_path}")
    if result.status == "published" and result.doc is not None and result.email is not None:
        if result.email.sent:
            print(
                f"delivery=sent to={config.operator.email} "
                f"message={result.email.message_id} doc={result.doc.url}"
            )
        else:
            print(f"delivery=published doc={result.doc.url} draft={result.email.draft_id} (not sent)")
    elif result.email is not None and result.email.sent:
        print(f"delivery=sent to={config.operator.email} message={result.email.message_id}")
    elif result.status == "ready" and result.validation_passed:
        print("delivery=pending (subscribe in the dashboard or pass --send when Gmail OAuth is connected)")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for err in result.errors:
        print(f"error: {err}", file=sys.stderr)
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
