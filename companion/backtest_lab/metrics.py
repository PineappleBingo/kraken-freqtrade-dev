"""Derive comparable metrics and chart series from a freqtrade backtest result.

Headline numbers are taken from freqtrade's stats block when present and
recomputed from the trade list otherwise, so the report works across freqtrade
versions. All chart series are computed from trades directly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .results import StrategyResult


def _parse_date(raw) -> datetime:
    text = str(raw).replace("+00:00", "").split(".")[0].replace("T", " ")
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def _round(value, places=2):
    return None if value is None else round(float(value), places)


def analyze(result: StrategyResult) -> dict:
    stats = result.stats
    trades = sorted(result.trades, key=lambda t: str(t.get("close_date", "")))
    starting = float(stats.get("starting_balance") or 1000.0)

    # ── equity & drawdown series ────────────────────────────────────────────
    equity_x: list[str] = []
    equity_y: list[float] = []      # cumulative profit, % of starting balance
    drawdown_y: list[float] = []    # % below running account peak
    cumulative = 0.0
    peak_value = starting
    for trade in trades:
        cumulative += float(trade.get("profit_abs") or 0.0)
        value = starting + cumulative
        peak_value = max(peak_value, value)
        when = _parse_date(trade.get("close_date"))
        equity_x.append(when.strftime("%Y-%m-%d %H:%M"))
        equity_y.append(round(cumulative / starting * 100, 3))
        drawdown_y.append(round((value - peak_value) / peak_value * 100, 3))

    # ── monthly returns (% of starting balance) ────────────────────────────
    monthly: dict[str, float] = defaultdict(float)
    for trade in trades:
        month = _parse_date(trade.get("close_date")).strftime("%Y-%m")
        monthly[month] += float(trade.get("profit_abs") or 0.0)
    monthly_pct = {m: round(v / starting * 100, 3)
                   for m, v in sorted(monthly.items())}

    # ── trade scatter (duration vs profit) ─────────────────────────────────
    scatter = [
        {
            "duration_h": round(float(t.get("trade_duration") or 0) / 60, 2),
            "profit_pct": round(float(t.get("profit_ratio") or 0) * 100, 3),
            "pair": t.get("pair", ""),
            "exit_reason": t.get("exit_reason", ""),
        }
        for t in trades
    ]

    # ── headline metrics ───────────────────────────────────────────────────
    wins = stats.get("wins")
    total = stats.get("total_trades", len(trades))
    if wins is None:
        wins = sum(1 for t in trades if float(t.get("profit_abs") or 0) > 0)
    win_rate = (wins / total * 100) if total else 0.0

    profit_total = stats.get("profit_total")
    if profit_total is None:
        profit_total = cumulative / starting

    max_dd = stats.get("max_drawdown_account")
    if max_dd is None:
        max_dd = -min(drawdown_y, default=0.0) / 100

    est_fees = sum(
        float(t.get("stake_amount") or 0) * float(t.get("fee_open") or 0)
        + float(t.get("amount") or 0) * float(t.get("close_rate") or 0)
        * float(t.get("fee_close") or 0)
        for t in trades
    )

    return {
        "name": result.name,
        "equity": {"x": equity_x, "y": equity_y},
        "drawdown": {"x": equity_x, "y": drawdown_y},
        "monthly": monthly_pct,
        "scatter": scatter,
        "metrics": {
            "Net profit %": _round(float(profit_total) * 100),
            "Net profit $": _round(stats.get("profit_total_abs", cumulative)),
            "Trades": total,
            "Win rate %": _round(win_rate, 1),
            "Profit factor": _round(stats.get("profit_factor"), 3),
            "Expectancy": _round(stats.get("expectancy"), 4),
            "Max drawdown %": _round(float(max_dd) * 100),
            "Sharpe": _round(stats.get("sharpe"), 2),
            "Sortino": _round(stats.get("sortino"), 2),
            "Calmar": _round(stats.get("calmar"), 2),
            "Avg hold": stats.get("holding_avg", ""),
            "Est. fees $": _round(est_fees),
        },
        "meta": {
            "timerange": f"{stats.get('backtest_start', '?')} → "
                         f"{stats.get('backtest_end', '?')}",
            "starting_balance": starting,
        },
    }


# Rows where a LOWER value wins (everything else: higher wins).
LOWER_IS_BETTER = {"Max drawdown %", "Est. fees $"}
# Rows that are informational only — no winner highlighting.
NO_WINNER = {"Trades", "Avg hold", "Net profit $"}


def best_per_metric(analyses: list[dict]) -> dict[str, str]:
    """metric name -> strategy name with the best value (ties: first)."""
    winners: dict[str, str] = {}
    if len(analyses) < 2:
        return winners
    metric_names = analyses[0]["metrics"].keys()
    for metric in metric_names:
        if metric in NO_WINNER:
            continue
        candidates = [(a["metrics"].get(metric), a["name"]) for a in analyses]
        candidates = [(v, n) for v, n in candidates
                      if isinstance(v, (int, float))]
        if len(candidates) < 2:
            continue
        pick = min(candidates) if metric in LOWER_IS_BETTER else max(candidates)
        winners[metric] = pick[1]
    return winners
