"""Pure helpers for the unified Telegram bot: pagination, callback data,
alert formatting and preferences. No Telegram imports — fully unit-testable.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

# ── pagination ──────────────────────────────────────────────────────────────

def paginate(items: Sequence, page: int, per_page: int):
    """Clamp page into range and slice. Returns (page_items, page, total_pages)."""
    total_pages = max(1, math.ceil(len(items) / per_page))
    page = max(0, min(int(page), total_pages - 1))
    start = page * per_page
    return list(items[start:start + per_page]), page, total_pages


def pager_row(prefix: str, page: int, total_pages: int) -> list[tuple[str, str]]:
    """(label, callback_data) buttons: ◀  2/4  ▶ — empty when single page."""
    if total_pages <= 1:
        return []
    row: list[tuple[str, str]] = []
    if page > 0:
        row.append(("◀", f"{prefix}:{page - 1}"))
    row.append((f"{page + 1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        row.append(("▶", f"{prefix}:{page + 1}"))
    return row


# ── callback data ───────────────────────────────────────────────────────────

def parse_callback(data: str) -> list[str]:
    """'trade:12:exit' -> ['trade', '12', 'exit'] (empty-safe)."""
    return (data or "").split(":")


# ── alert formatting & preferences ──────────────────────────────────────────

ALERT_EVENTS = ["entry", "entry_fill", "exit", "exit_fill",
                "entry_cancel", "exit_cancel", "status"]

DEFAULT_ALERTS = {event: (event != "status") for event in ALERT_EVENTS}

ALERT_LABELS = {
    "entry": "🟢 Entry signals",
    "entry_fill": "✅ Entry fills",
    "exit": "🔵 Exit signals",
    "exit_fill": "💰 Exit fills",
    "entry_cancel": "⚠️ Entry cancels",
    "exit_cancel": "⚠️ Exit cancels",
    "status": "ℹ️ Status messages",
}


def _num(value: Any, places: int = 4) -> str:
    try:
        return f"{float(value):,.{places}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.2f}%"
    except (TypeError, ValueError):
        return str(value)


def format_event(payload: dict) -> str | None:
    """Human alert text for a freqtrade webhook payload, or None to stay quiet."""
    event = str(payload.get("event", ""))
    pair = payload.get("pair", "?")
    if event == "entry":
        return (f"🟢 Entry: {pair} @ {_num(payload.get('open_rate'))} "
                f"(stake ${_num(payload.get('stake_amount'), 2)})")
    if event == "entry_fill":
        return (f"✅ Entry filled: {pair} @ {_num(payload.get('open_rate'))} "
                f"(stake ${_num(payload.get('stake_amount'), 2)})")
    if event == "exit":
        return (f"🔵 Exit: {pair} {_pct(payload.get('profit_ratio'))} "
                f"— {payload.get('exit_reason', '')}")
    if event == "exit_fill":
        return (f"💰 Exit filled: {pair} "
                f"{_pct(payload.get('profit_ratio'))} "
                f"(${_num(payload.get('profit_amount'), 2)}) "
                f"— {payload.get('exit_reason', '')}")
    if event in ("entry_cancel", "exit_cancel"):
        return (f"⚠️ Order cancelled ({event}): {pair} "
                f"trade #{payload.get('trade_id', '?')} — logged for review "
                f"(📋 Failures)")
    if event == "status":
        return f"ℹ️ Bot status: {payload.get('status', '')}"
    return None


def get_alert_prefs(merged_config: dict) -> dict[str, bool]:
    prefs = dict(DEFAULT_ALERTS)
    stored = (merged_config.get("companion") or {}).get("alerts") or {}
    for key, val in stored.items():
        if key in prefs:
            prefs[key] = bool(val)
    return prefs


def alert_enabled(merged_config: dict, event: str) -> bool:
    return get_alert_prefs(merged_config).get(event, False)
