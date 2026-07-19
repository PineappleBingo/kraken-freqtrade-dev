import json
import re
import zipfile
from pathlib import Path

import pytest

from companion.backtest_lab.metrics import analyze, best_per_metric
from companion.backtest_lab.render import render_html, write_report
from companion.backtest_lab.results import load_results

REPO = Path(__file__).resolve().parent.parent


def _trade(profit_abs, profit_ratio, close_date, duration_min=120,
           pair="BTC/USD", reason="roi"):
    return {
        "pair": pair, "profit_abs": profit_abs, "profit_ratio": profit_ratio,
        "open_date": "2026-01-01 00:00:00", "close_date": close_date,
        "trade_duration": duration_min, "exit_reason": reason,
        "stake_amount": 100.0, "amount": 0.001, "close_rate": 100000.0,
        "fee_open": 0.0025, "fee_close": 0.0025,
    }


def _export(strategy_name, trades, **stats):
    base = {
        "starting_balance": 1000.0,
        "total_trades": len(trades),
        "wins": sum(1 for t in trades if t["profit_abs"] > 0),
        "backtest_start": "2026-01-01", "backtest_end": "2026-03-01",
        "trades": trades,
    }
    base.update(stats)
    return {"strategy": {strategy_name: base}}


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    trades_a = [
        _trade(50.0, 0.05, "2026-01-10 12:00:00"),
        _trade(-20.0, -0.02, "2026-01-20 12:00:00", reason="stop_loss"),
        _trade(30.0, 0.03, "2026-02-05 12:00:00"),
    ]
    trades_b = [
        _trade(10.0, 0.01, "2026-01-15 12:00:00", pair="ETH/USD"),
        _trade(15.0, 0.015, "2026-02-10 12:00:00", pair="ETH/USD"),
    ]
    (tmp_path / "StratA.json").write_text(json.dumps(_export("StratA", trades_a)))
    # StratB delivered as a zip, like newer freqtrade exports
    with zipfile.ZipFile(tmp_path / "StratB.zip", "w") as zf:
        zf.writestr("StratB.json", json.dumps(_export("StratB", trades_b)))
        zf.writestr("StratB_config.json", "{}")  # must be ignored
    return tmp_path


def test_load_results_reads_json_and_zip(run_dir):
    results = load_results(run_dir)
    names = sorted(r.name for r in results)
    assert names == ["StratA", "StratB"]
    strat_a = next(r for r in results if r.name == "StratA")
    assert len(strat_a.trades) == 3


def test_load_results_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_results(tmp_path)


def test_metrics_equity_and_drawdown_math(run_dir):
    strat_a = next(r for r in load_results(run_dir) if r.name == "StratA")
    analysis = analyze(strat_a)

    # equity: +50, +30(-20), +60 on a 1000 start -> 5%, 3%, 6%
    assert analysis["equity"]["y"] == [5.0, 3.0, 6.0]
    # drawdown: 0 at new peak, then (1030-1050)/1050, then back to 0
    assert analysis["drawdown"]["y"][0] == 0.0
    assert analysis["drawdown"]["y"][1] == pytest.approx(-1.905, abs=0.001)
    assert analysis["drawdown"]["y"][2] == 0.0

    metrics = analysis["metrics"]
    assert metrics["Net profit %"] == 6.0
    assert metrics["Trades"] == 3
    assert metrics["Win rate %"] == pytest.approx(66.7, abs=0.1)
    assert metrics["Max drawdown %"] == pytest.approx(1.9, abs=0.1)
    # monthly: Jan +30 (3%), Feb +30 (3%)
    assert analysis["monthly"] == {"2026-01": 3.0, "2026-02": 3.0}
    assert len(analysis["scatter"]) == 3


def test_best_per_metric_picks_directional_winners(run_dir):
    analyses = [analyze(r) for r in load_results(run_dir)]
    winners = best_per_metric(analyses)
    assert winners["Net profit %"] == "StratA"      # 6% > 2.5%
    assert winners["Max drawdown %"] == "StratB"    # lower is better
    assert "Trades" not in winners                  # informational row


def test_render_html_contains_everything(run_dir, tmp_path):
    analyses = [analyze(r) for r in load_results(run_dir)]
    winners = best_per_metric(analyses)
    html = render_html(analyses, winners, run_label="test-run",
                       include_plotly=False)

    for needed in ("StratA", "StratB", "Cumulative profit", "Drawdown",
                   "Monthly returns", "Individual trades", "Metrics",
                   "test-run", "themeToggle", "prefers-color-scheme"):
        assert needed in html
    assert html.count('class="win"') >= 2  # winner cells marked

    out = tmp_path / "reports"
    path = write_report(analyses, winners, out, include_plotly=False)
    assert path.exists()
    assert (out / "latest.html").read_text(encoding="utf-8") == \
        path.read_text(encoding="utf-8")


def test_e0v1e_kraken_roi_floor_is_fee_aware():
    """The 1%+ net promise: gross ROI floor must be >= 1.7%."""
    text = (REPO / "user_data/strategies/E0V1EKraken.py").read_text()
    match = re.search(r"MIN_GROSS_PROFIT\s*=\s*([0-9.]+)", text)
    assert match, "MIN_GROSS_PROFIT constant missing"
    assert float(match.group(1)) >= 0.017
    assert "MIN_GROSS_PROFIT" in text.split("minimal_roi")[1].split("}")[0]
    assert "current_profit < MIN_GROSS_PROFIT" in text


def test_lab_reports_served_by_companion_api(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from companion.api import build_app
    from companion.failure_log import FailureLog

    reports = tmp_path / "lab_reports"
    reports.mkdir()
    (reports / "latest.html").write_text("<html>report</html>")
    app = build_app(FailureLog(tmp_path), lab_reports_dir=reports)
    client = TestClient(app)
    resp = client.get("/lab/latest.html")
    assert resp.status_code == 200
    assert "report" in resp.text
