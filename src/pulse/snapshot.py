"""Local sanitized pulse snapshot (Phase 6). No Google / MCP."""

from __future__ import annotations

import re
from pathlib import Path

from pulse.schemas import PulseNote

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"

_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_snapshot_dir(snapshot_dir: Path | None = None) -> Path:
    if snapshot_dir is not None:
        return snapshot_dir
    cwd = Path.cwd() / "data" / "snapshots"
    if (Path.cwd() / "data").is_dir():
        return cwd
    return DEFAULT_SNAPSHOT_DIR


def snapshot_filename(run_id: str) -> str:
    safe = _SAFE_RUN_ID.sub("-", run_id).strip("-") or "pulse"
    return f"{safe}.md"


def render_snapshot(pulse: PulseNote) -> str:
    """Sanitized pulse body only — no raw reviews, authors, or source ids."""
    return (pulse.body or "").strip() + "\n"


def write_snapshot(
    pulse: PulseNote,
    *,
    run_id: str,
    directory: Path,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    root = directory.resolve()
    path = (root / snapshot_filename(run_id)).resolve()
    if path.parent != root:
        raise ValueError("snapshot path escapes snapshot directory")
    path.write_text(render_snapshot(pulse), encoding="utf-8")
    return path
