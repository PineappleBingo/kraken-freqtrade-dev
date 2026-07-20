import json
from pathlib import Path

import pytest

from companion import capital_manager as cm
from companion import config_io

CM_CFG = {
    "enabled": True,
    "profit_target_usd": 10000,
    "set_aside_usd": 9000,
    "restart_capital_usd": 1000,
    "force_exit_open_trades": False,
}


# ── pure decision logic ─────────────────────────────────────────────────────

def test_disabled_never_triggers():
    decision = cm.evaluate(cm.PHASE_NORMAL, {"enabled": False}, 1e9, 0)
    assert decision.action == "none"


def test_below_target_no_action():
    assert cm.evaluate(cm.PHASE_NORMAL, CM_CFG, 9999.99, 2).action == "none"


def test_target_hit_starts_banking():
    decision = cm.evaluate(cm.PHASE_NORMAL, CM_CFG, 10000.0, 2)
    assert decision.action == "bank_start"


def test_waiting_flat_holds_until_no_open_trades():
    assert cm.evaluate(cm.PHASE_WAITING_FLAT, CM_CFG, 10500, 1).action == "none"
    assert cm.evaluate(cm.PHASE_WAITING_FLAT, CM_CFG, 10500, 0).action == "bank_reset"


def test_awaiting_withdrawal_rearms_after_balance_drops():
    # still ~10k in the account: user has not withdrawn yet
    assert cm.evaluate(cm.PHASE_AWAITING_WITHDRAWAL, CM_CFG, 10100, 0).action == "none"
    # balance near restart capital: withdrawal happened
    assert cm.evaluate(cm.PHASE_AWAITING_WITHDRAWAL, CM_CFG, 1100, 0).action == "rearm"


# ── full cycle against a fake freqtrade API ─────────────────────────────────

class FakeApi:
    def __init__(self):
        self.balance = 300.0
        self.open_trades = 0
        self.calls = []

    def total_balance(self):
        return self.balance

    def open_trade_count(self):
        return self.open_trades

    def stop_entry(self):
        self.calls.append("stop_entry")

    def start(self):
        self.calls.append("start")

    def reload_config(self):
        self.calls.append("reload_config")

    def force_exit_all(self):
        self.calls.append("force_exit_all")
        return self.open_trades


@pytest.fixture
def env(tmp_path: Path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    (config_dir / config_io.CONFIG_FILE).write_text(json.dumps({"dry_run": True}))
    (config_dir / config_io.RISK_FILE).write_text(json.dumps({
        "available_capital": 300,
        "companion": {"capital_management": dict(CM_CFG)},
    }))
    api = FakeApi()
    messages = []
    manager = cm.CapitalManager(api, config_dir, data_dir,
                                notify=messages.append)
    return api, manager, config_dir, messages


def test_full_bank_and_reset_cycle(env):
    api, manager, config_dir, messages = env

    # 1) below target: nothing happens
    assert manager.run_once() == cm.PHASE_NORMAL
    assert api.calls == []

    # 2) target hit while trades open: pause, wait for flat
    api.balance = 10500.0
    api.open_trades = 2
    assert manager.run_once() == cm.PHASE_WAITING_FLAT
    assert "stop_entry" in api.calls
    assert "force_exit_all" not in api.calls  # force_exit_open_trades=False

    # 3) still waiting while a trade is open
    assert manager.run_once() == cm.PHASE_WAITING_FLAT

    # 4) flat: capital reset written, config reloaded, bot resumed
    api.open_trades = 0
    assert manager.run_once() == cm.PHASE_AWAITING_WITHDRAWAL
    risk = json.loads((config_dir / config_io.RISK_FILE).read_text())
    assert risk["available_capital"] == 1000
    assert "reload_config" in api.calls and "start" in api.calls
    assert any("withdraw" in m.lower() for m in messages)

    # 5) does NOT re-trigger while the 10k sits in the account
    assert manager.run_once() == cm.PHASE_AWAITING_WITHDRAWAL

    # 6) after manual withdrawal the cycle re-arms
    api.balance = 1050.0
    assert manager.run_once() == cm.PHASE_NORMAL

    # state survives restart
    state = manager.load_state()
    assert state["phase"] == cm.PHASE_NORMAL
    assert len(state["bank_history"]) == 1


def test_force_exit_when_configured(env):
    api, manager, config_dir, _ = env
    risk_path = config_dir / config_io.RISK_FILE
    risk = json.loads(risk_path.read_text())
    risk["companion"]["capital_management"]["force_exit_open_trades"] = True
    risk_path.write_text(json.dumps(risk))

    api.balance = 12000.0
    api.open_trades = 3
    manager.run_once()
    assert "force_exit_all" in api.calls
