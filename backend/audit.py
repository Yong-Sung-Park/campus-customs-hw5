"""Audit trail: every agent-loop step is appended to output/audit_trail.json.

The file is one JSON array that only ever grows: new events are spliced in
before the closing bracket, so earlier runs are never rewritten or wiped.
A copy of recent events stays in memory for the board's /api/events route.
"""

import json
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from models import AuditEvent

REPO_DIR = Path(__file__).resolve().parent.parent
AUDIT_PATH = REPO_DIR / "output" / "audit_trail.json"
MAX_FIELD = 4000  # truncate huge tool payloads so the trail stays readable
MEMORY_LIMIT = 5000

_lock = threading.Lock()
_events: list[dict] = []
_seq = 0


def truncate(value: Any, limit: int = MAX_FIELD) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"… [+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [truncate(v, limit) for v in value]
    return value


def _append_to_file(event: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, default=str)
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
        AUDIT_PATH.write_text(f"[\n{line}\n]\n", encoding="utf-8")
        return
    with open(AUDIT_PATH, "r+b") as f:
        f.seek(0, 2)
        end = f.tell()
        start = max(0, end - 4096)
        f.seek(start)
        tail = f.read()
        close = tail.rfind(b"]")
        if close == -1:
            raise ValueError(f"{AUDIT_PATH} is not a JSON array")
        cut = close
        while cut > 0 and tail[cut - 1 : cut] in (b" ", b"\n", b"\r", b"\t"):
            cut -= 1
        empty = tail[cut - 1 : cut] == b"["
        f.seek(start + cut)
        f.truncate()
        f.write((b"\n" if empty else b",\n") + line.encode("utf-8") + b"\n]\n")


def _load_existing() -> None:
    global _seq
    if not AUDIT_PATH.exists():
        return
    try:
        data = json.loads(AUDIT_PATH.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return
    _events.extend(data[-MEMORY_LIMIT:])
    _seq = max((e.get("seq", 0) for e in data), default=0)


def record(run_id: str, ticket_id: int, agent: str, depth: int, step: str, detail: dict | None = None) -> dict:
    global _seq
    with _lock:
        _seq += 1
        ev = asdict(AuditEvent(
            run_id=run_id, ticket_id=ticket_id, agent=agent, depth=depth, step=step,
            detail=truncate(detail or {}),
            ts=datetime.now().astimezone().isoformat(timespec="milliseconds"),
            seq=_seq,
        ))
        _events.append(ev)
        if len(_events) > MEMORY_LIMIT:
            del _events[: len(_events) - MEMORY_LIMIT]
        _append_to_file(ev)
    return ev


def recent(ticket_id: int | None = None, run_id: str | None = None, since: int = 0, limit: int = 500) -> list[dict]:
    with _lock:
        out = [
            e for e in _events
            if e["seq"] > since
            and (ticket_id is None or e["ticket_id"] == ticket_id)
            and (run_id is None or e["run_id"] == run_id)
        ]
    return out[-limit:]


_load_existing()
