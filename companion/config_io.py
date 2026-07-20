"""Read/validate/write the bot's JSON config files.

Two files live in the config directory:
  - config.json         : exchange/orders/api plumbing (rarely edited)
  - risk_settings.json  : every user-tunable risk & capital knob

freqtrade loads risk_settings.json last, so values here override both
config.json and strategy defaults. The Telegram settings bot edits fields
through the FIELDS registry below so every change is type-checked and
bounds-checked before it hits disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILE = "config.json"
RISK_FILE = "risk_settings.json"


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json_atomic(path: Path, data: dict) -> None:
    """Write JSON via a temp file + rename so a crash can't corrupt the config."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def merged_config(config_dir: Path) -> dict:
    """The effective config as freqtrade sees it (risk file wins)."""
    return _deep_merge(
        load_json(config_dir / CONFIG_FILE),
        load_json(config_dir / RISK_FILE),
    )


def get_path(data: dict, path: list[str], default: Any = None) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def set_path(data: dict, path: list[str], value: Any) -> None:
    cur = data
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


@dataclass(frozen=True)
class FieldSpec:
    key: str                # short id used in Telegram callbacks
    label: str              # human name shown on buttons
    file: str               # RISK_FILE or CONFIG_FILE
    path: tuple             # path inside the json document
    type: str               # "float" | "int" | "bool"
    min: float | None = None
    max: float | None = None
    help: str = ""


FIELDS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in [
        # ── Risk ────────────────────────────────────────────────────────────
        FieldSpec("stoploss", "Stoploss", RISK_FILE, ("stoploss",), "float",
                  -0.50, -0.01, "Loss ratio that closes a trade, e.g. -0.08 = -8%"),
        FieldSpec("max_open_trades", "Max open trades", RISK_FILE,
                  ("max_open_trades",), "int", 1, 10,
                  "How many positions can be open at once"),
        FieldSpec("available_capital", "Available capital (USD)", RISK_FILE,
                  ("available_capital",), "float", 10, 1_000_000_000,
                  "Capital the bot is allowed to trade with"),
        FieldSpec("trailing_stop", "Trailing stop on/off", RISK_FILE,
                  ("trailing_stop",), "bool"),
        FieldSpec("trailing_stop_positive", "Trailing distance", RISK_FILE,
                  ("trailing_stop_positive",), "float", 0.005, 0.20,
                  "Trail distance once offset is reached, e.g. 0.02 = 2%"),
        FieldSpec("trailing_stop_positive_offset", "Trailing offset", RISK_FILE,
                  ("trailing_stop_positive_offset",), "float", 0.01, 0.30,
                  "Profit at which trailing activates, e.g. 0.04 = 4%"),
        # ── Capital management ─────────────────────────────────────────────
        FieldSpec("cm_enabled", "Capital mgmt on/off", RISK_FILE,
                  ("companion", "capital_management", "enabled"), "bool"),
        FieldSpec("cm_profit_target", "Profit target (USD)", RISK_FILE,
                  ("companion", "capital_management", "profit_target_usd"),
                  "float", 50, 1_000_000_000,
                  "Total balance that triggers bank & reset"),
        FieldSpec("cm_set_aside", "Set aside (USD)", RISK_FILE,
                  ("companion", "capital_management", "set_aside_usd"),
                  "float", 0, 1_000_000_000,
                  "Amount you will withdraw manually when target hits"),
        FieldSpec("cm_restart_capital", "Restart capital (USD)", RISK_FILE,
                  ("companion", "capital_management", "restart_capital_usd"),
                  "float", 10, 1_000_000_000,
                  "Capital the bot restarts with after banking"),
        FieldSpec("cm_force_exit", "Force-exit open trades on target", RISK_FILE,
                  ("companion", "capital_management", "force_exit_open_trades"),
                  "bool"),
    ]
}


def validate_and_cast(spec: FieldSpec, raw: str) -> Any:
    """Parse user text into a valid value for the field, or raise ValueError."""
    raw = raw.strip()
    if spec.type == "bool":
        low = raw.lower()
        if low in ("on", "true", "yes", "1", "켜기"):
            return True
        if low in ("off", "false", "no", "0", "끄기"):
            return False
        raise ValueError("Send 'on' or 'off'")
    if spec.type == "int":
        try:
            value: Any = int(raw)
        except ValueError:
            raise ValueError("Send a whole number, e.g. 3")
    else:
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("Send a number, e.g. -0.08")
    if spec.min is not None and value < spec.min:
        raise ValueError(f"Minimum is {spec.min}")
    if spec.max is not None and value > spec.max:
        raise ValueError(f"Maximum is {spec.max}")
    return value


def check_cross_field_rules(risk: dict) -> list[str]:
    """Sanity warnings across capital-management fields (non-blocking)."""
    warnings = []
    cm = get_path(risk, ["companion", "capital_management"], {}) or {}
    target = cm.get("profit_target_usd")
    aside = cm.get("set_aside_usd")
    restart = cm.get("restart_capital_usd")
    if target is not None and aside is not None and aside >= target:
        warnings.append(
            f"set_aside_usd ({aside}) should be LESS than profit_target_usd ({target})")
    if (target is not None and aside is not None and restart is not None
            and restart > target - aside):
        warnings.append(
            f"restart_capital_usd ({restart}) is more than what remains after "
            f"setting aside ({target - aside})")
    return warnings


def update_field(config_dir: Path, spec: FieldSpec, value: Any) -> tuple[Any, list[str]]:
    """Apply one validated value to disk. Returns (old_value, warnings)."""
    path = config_dir / spec.file
    data = load_json(path)
    old = get_path(data, list(spec.path))
    set_path(data, list(spec.path), value)
    warnings = check_cross_field_rules(data) if spec.file == RISK_FILE else []
    save_json_atomic(path, data)
    return old, warnings
