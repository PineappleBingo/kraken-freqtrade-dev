"""Back-log of every bot event, with a failures view for post-mortems.

All freqtrade webhook events land in an `events` table; cancelled orders and
errors also land in `failures` so you can review exactly what went wrong and
when (item: "if the trade failed then I could review and fix the issue").
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

FAILURE_EVENTS = {"entry_cancel", "exit_cancel", "error"}


class FailureLog:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "events.sqlite"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " ts TEXT NOT NULL,"
                " event TEXT NOT NULL,"
                " pair TEXT,"
                " trade_id TEXT,"
                " detail TEXT,"
                " payload TEXT)"
            )

    def record(self, event: str, payload: dict, detail: str = "") -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO events (ts, event, pair, trade_id, detail, payload)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    event,
                    str(payload.get("pair", "")),
                    str(payload.get("trade_id", "")),
                    detail or str(payload.get("exit_reason", "")
                                  or payload.get("status", "")),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def record_error(self, source: str, message: str) -> None:
        self.record("error", {"source": source}, detail=message)

    def recent_failures(self, limit: int = 10) -> list[dict]:
        marks = ",".join("?" for _ in FAILURE_EVENTS)
        with self._connect() as con:
            rows = con.execute(
                f"SELECT ts, event, pair, trade_id, detail FROM events"
                f" WHERE event IN ({marks}) ORDER BY id DESC LIMIT ?",
                (*FAILURE_EVENTS, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT ts, event, pair, trade_id, detail FROM events"
                " ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
