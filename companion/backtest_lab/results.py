"""Load freqtrade backtest exports (.json, or .zip produced by newer versions).

A run directory contains one export per strategy (written by scripts/lab.sh
compare), but each file may also hold several strategies (--strategy-list).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StrategyResult:
    name: str
    stats: dict
    trades: list = field(default_factory=list)


def _is_report_member(name: str) -> bool:
    if not name.endswith(".json"):
        return False
    return not any(tag in name for tag in
                   ("_config", "market_change", ".meta", "_signals",
                    "_rejected", "_exited"))


def _load_payload(path: Path) -> dict | None:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.namelist() if _is_report_member(m)]
            if not members:
                return None
            with zf.open(members[0]) as fh:
                return json.load(fh)
    if path.suffix == ".json" and _is_report_member(path.name):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return None


def load_results(run_dir: Path) -> list[StrategyResult]:
    """Parse every export in run_dir; newest file wins on duplicate names."""
    results: dict[str, StrategyResult] = {}
    files = sorted(
        [p for p in Path(run_dir).iterdir()
         if p.suffix in (".json", ".zip")],
        key=lambda p: p.stat().st_mtime,
    )
    for path in files:
        try:
            payload = _load_payload(path)
        except (json.JSONDecodeError, zipfile.BadZipFile, OSError):
            continue
        if not payload or "strategy" not in payload:
            continue
        for name, stats in payload["strategy"].items():
            results[name] = StrategyResult(
                name=name,
                stats=stats,
                trades=list(stats.get("trades") or []),
            )
    if not results:
        raise FileNotFoundError(
            f"No freqtrade backtest exports found in {run_dir}")
    return list(results.values())
