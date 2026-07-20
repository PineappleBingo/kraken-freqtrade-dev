"""Profit-target capital management: pause -> bank -> reset -> resume.

The bot NEVER withdraws funds. "Banking" means:
  1. total account value reaches profit_target_usd
  2. pause new entries (freqtrade /stopentry); optionally force-exit open trades
  3. once flat, set available_capital = restart_capital_usd and /reload_config
     -> the bot now only trades with the restart capital
  4. tell the user (Telegram) to withdraw set_aside_usd manually on Kraken
  5. wait until the balance actually drops (withdrawal done) before arming again

Phases (persisted in data/capital_state.json so restarts are safe):
  normal -> waiting_flat -> awaiting_withdrawal -> normal
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PHASE_NORMAL = "normal"
PHASE_WAITING_FLAT = "waiting_flat"
PHASE_AWAITING_WITHDRAWAL = "awaiting_withdrawal"

# Balance must fall to within this factor of restart capital before we re-arm.
REARM_FACTOR = 1.5


@dataclass
class Decision:
    action: str          # "none" | "bank_start" | "bank_reset" | "rearm"
    message: str = ""


def evaluate(phase: str, cm_cfg: dict, total_balance: float,
             open_trades: int) -> Decision:
    """Pure decision logic — unit-testable without any I/O."""
    if not cm_cfg.get("enabled", False):
        return Decision("none")
    target = float(cm_cfg.get("profit_target_usd", 0) or 0)
    restart = float(cm_cfg.get("restart_capital_usd", 0) or 0)
    aside = float(cm_cfg.get("set_aside_usd", 0) or 0)
    if target <= 0:
        return Decision("none")

    if phase == PHASE_NORMAL:
        if total_balance >= target:
            return Decision(
                "bank_start",
                f"🎯 Profit target hit! Total balance ${total_balance:,.2f} >= "
                f"${target:,.2f}. Pausing new entries."
            )
        return Decision("none")

    if phase == PHASE_WAITING_FLAT:
        if open_trades == 0:
            return Decision(
                "bank_reset",
                f"✅ All positions closed. Trading capital reset to "
                f"${restart:,.2f}. 👉 ACTION NEEDED: withdraw ${aside:,.2f} "
                f"from Kraken manually (the bot never touches withdrawals)."
            )
        return Decision("none")

    if phase == PHASE_AWAITING_WITHDRAWAL:
        if total_balance <= restart * REARM_FACTOR:
            return Decision(
                "rearm",
                f"💰 Withdrawal detected (balance ${total_balance:,.2f}). "
                f"Capital management re-armed for the next target."
            )
        return Decision("none")

    return Decision("none")


class CapitalManager:
    def __init__(self, api, config_dir: Path, data_dir: Path, notify=None):
        self.api = api
        self.config_dir = config_dir
        self.state_path = data_dir / "capital_state.json"
        self.notify = notify or (lambda msg: None)

    # ── state ───────────────────────────────────────────────────────────────
    def load_state(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {"phase": PHASE_NORMAL, "bank_history": []}

    def save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)

    # ── one poll cycle ──────────────────────────────────────────────────────
    def run_once(self) -> str:
        from . import config_io

        cfg = config_io.merged_config(self.config_dir)
        cm_cfg = config_io.get_path(cfg, ["companion", "capital_management"], {}) or {}
        state = self.load_state()
        phase = state.get("phase", PHASE_NORMAL)

        total = self.api.total_balance()
        open_trades = self.api.open_trade_count()
        decision = evaluate(phase, cm_cfg, total, open_trades)

        if decision.action == "none":
            return phase

        if decision.action == "bank_start":
            self.api.stop_entry()
            if cm_cfg.get("force_exit_open_trades", False):
                self.api.force_exit_all()
            state["phase"] = PHASE_WAITING_FLAT
            state["bank_trigger"] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "total_balance": total,
            }

        elif decision.action == "bank_reset":
            restart = float(cm_cfg.get("restart_capital_usd", 0) or 0)
            risk_path = self.config_dir / config_io.RISK_FILE
            risk = config_io.load_json(risk_path)
            config_io.set_path(risk, ["available_capital"], restart)
            config_io.save_json_atomic(risk_path, risk)
            self.api.reload_config()
            self.api.start()
            state["bank_history"].append({
                "at": datetime.now(timezone.utc).isoformat(),
                "total_balance": total,
                "set_aside_usd": cm_cfg.get("set_aside_usd"),
                "restart_capital_usd": restart,
            })
            state["phase"] = PHASE_AWAITING_WITHDRAWAL

        elif decision.action == "rearm":
            state["phase"] = PHASE_NORMAL

        self.save_state(state)
        self.notify(decision.message)
        return state["phase"]
