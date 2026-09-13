"""Wait until Monday 09:00 IST, then run the weekly send job."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta

from pulse.config import load_pulse_dotenv
from pulse.ingest.common import IST
from pulse.weekly import main as weekly_main

logger = logging.getLogger("pulse.schedule")

MONDAY = 0
HOUR = 9
MINUTE = 0


def as_ist(now: datetime | None = None) -> datetime:
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        return current.replace(tzinfo=IST)
    return current.astimezone(IST)


def next_monday_0900(now: datetime | None = None) -> datetime:
    """Next Monday 09:00 IST strictly after `now` (or now if it is exactly 09:00)."""
    current = as_ist(now)
    days_ahead = (MONDAY - current.weekday()) % 7
    candidate = current.replace(
        hour=HOUR, minute=MINUTE, second=0, microsecond=0
    ) + timedelta(days=days_ahead)
    if candidate < current:
        candidate += timedelta(days=7)
    return candidate


def sleep_until(target: datetime, *, now: datetime | None = None) -> None:
    remaining = (target - as_ist(now)).total_seconds()
    if remaining <= 0:
        return
    logger.info("Sleeping %.0f seconds until %s", remaining, target.isoformat())
    # Chunked sleep so Ctrl+C is responsive on Windows.
    deadline = time.monotonic() + remaining
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 30.0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse.schedule",
        description="Loop: wait until Monday 09:00 IST, then fetch / classify / send.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one wait+job cycle, then exit (default: loop every week)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_pulse_dotenv()
    args = build_parser().parse_args(argv)
    logger.info("Scheduler armed for Monday %02d:%02d IST", HOUR, MINUTE)
    while True:
        target = next_monday_0900()
        logger.info("Next weekly send at %s", target.isoformat())
        sleep_until(target)
        code = weekly_main([])
        if code != 0:
            logger.error("Weekly job exited %s; waiting for the next Monday", code)
        if args.once:
            return code
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("scheduler stopped", file=sys.stderr)
        raise SystemExit(130)
