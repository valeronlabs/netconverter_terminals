"""What the local MCP bridge did, as metadata the full-screen app can show.

One JSON line per bridge tool call in ``.netconverter/bridge.jsonl``: time,
AI client name, tool, workspace-relative path, sha256, byte count, job id,
job type, vendors and status. Configuration text, tool results and
credentials are never written: only the fields in ``FIELDS`` survive, and
each must be a short scalar.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

LOG_NAME = "bridge.jsonl"
FIELDS = ("ts", "client", "tool", "path", "sha256", "bytes", "files", "job_id",
          "job_type", "source_vendor", "target_vendor", "status", "error")
MAX_BYTES = 512 * 1024
KEEP_LINES = 500
_TEXT = re.compile(r"[\w .:/@+()-]{0,200}\Z")


def _clean(entry: dict) -> dict:
    out = {}
    for key in FIELDS:
        value = entry.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)) and abs(value) < 1e13:
            out[key] = value
        elif isinstance(value, str) and _TEXT.fullmatch(value):
            out[key] = value
    return out


def record(state_dir: Path, **entry) -> None:
    """Append one metadata line; never raises (the bridge must keep serving)."""
    try:
        state_dir.mkdir(mode=0o700, exist_ok=True)
        path = state_dir / LOG_NAME
        if path.is_symlink():
            return
        line = json.dumps(_clean({"ts": round(time.time(), 3), **entry}), sort_keys=True) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(line)
        if path.stat().st_size > MAX_BYTES:
            kept = path.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:]
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
            os.replace(tmp, path)
    except OSError:
        pass


def recent(state_dir: Path, limit: int = 20) -> list[dict]:
    """Newest-last entries; malformed lines are skipped."""
    path = state_dir / LOG_NAME
    try:
        if path.is_symlink() or not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-max(limit, 1):]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(_clean(item))
    return out


def mtime(state_dir: Path) -> float:
    try:
        return (state_dir / LOG_NAME).stat().st_mtime
    except OSError:
        return 0.0
