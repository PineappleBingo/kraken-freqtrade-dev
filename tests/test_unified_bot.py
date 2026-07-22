import asyncio
import json
import shutil
from pathlib import Path

import pytest

from companion import botui

REPO = Path(__file__).resolve().parent.parent


# ── pagination ──────────────────────────────────────────────────────────────

def test_paginate_slices_and_counts():
    items = list(range(10))
    page_items, page, total = botui.paginate(items, 0, 3)
    assert page_items == [0, 1, 2] and page == 0 and total == 4
    page_items, page, total = botui.paginate(items, 3, 3)
    assert page_items == [9]


def test_paginate_clamps_out_of_range():
    items = list(range(5))
    page_items, page, _ = botui.paginate(items, 99, 2)
    assert page == 2 and page_items == [4]
    page_items, page, _ = botui.paginate(items, -5, 2)
    assert page == 0 and page_items == [0, 1]


def test_paginate_empty_list():
    page_items, page, total = botui.paginate([], 0, 5)
    assert page_items == [] and page == 0 and total == 1


def test_pager_row_edges():
    assert botui.pager_row("x", 0, 1) == []                    # single page
    first = botui.pager_row("x", 0, 3)
    assert [b[0] for b in first] == ["1/3", "▶"]               # no back arrow
    middle = botui.pager_row("x", 1, 3)
    assert [b[0] for b in middle] == ["◀", "2/3", "▶"]
    assert middle[0][1] == "x:0" and middle[2][1] == "x:2"
    last = botui.pager_row("x", 2, 3)
    assert [b[0] for b in last] == ["◀", "3/3"]                # no fwd arrow


def test_parse_callback():
    assert botui.parse_callback("trade:12:exit") == ["trade", "12", "exit"]
    assert botui.parse_callback("") == [""]


# ── alert formatting & prefs ────────────────────────────────────────────────

@pytest.mark.parametrize("payload,needle", [
    ({"event": "entry", "pair": "BTC/USD", "open_rate": "50000",
      "stake_amount": "100"}, "🟢 Entry: BTC/USD @ 50,000"),
    ({"event": "entry_fill", "pair": "BTC/USD", "open_rate": "50000",
      "stake_amount": "100"}, "✅ Entry filled"),
    ({"event": "exit", "pair": "ETH/USD", "profit_ratio": "0.021",
      "exit_reason": "roi"}, "+2.10%"),
    ({"event": "exit_fill", "pair": "ETH/USD", "profit_ratio": "-0.03",
      "profit_amount": "-3.1", "exit_reason": "stop_loss"}, "-3.00%"),
    ({"event": "entry_cancel", "pair": "SOL/USD", "trade_id": "4"},
     "Order cancelled"),
    ({"event": "status", "status": "running"}, "running"),
])
def test_format_event(payload, needle):
    assert needle in botui.format_event(payload)


def test_format_event_unknown_is_silent():
    assert botui.format_event({"event": "mystery"}) is None


def test_alert_prefs_defaults_and_overrides():
    assert botui.get_alert_prefs({})["entry"] is True
    assert botui.get_alert_prefs({})["status"] is False
    merged = {"companion": {"alerts": {"entry": False, "status": True}}}
    prefs = botui.get_alert_prefs(merged)
    assert prefs["entry"] is False and prefs["status"] is True
    assert botui.alert_enabled(merged, "exit") is True


def test_shipped_risk_settings_has_alert_defaults():
    risk = json.loads((REPO / "config/risk_settings.json").read_text())
    assert risk["companion"]["alerts"]["entry"] is True
    assert risk["companion"]["alerts"]["status"] is False


# ── webhook -> alert routing ────────────────────────────────────────────────

@pytest.fixture
def webhook_env(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from companion.api import build_app
    from companion.failure_log import FailureLog

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(REPO / "config/config.json", config_dir / "config.json")
    shutil.copy(REPO / "config/risk_settings.json",
                config_dir / "risk_settings.json")

    log = FailureLog(tmp_path / "data")
    notes: list[str] = []
    app = build_app(log, notify=notes.append, config_dir=config_dir)
    return TestClient(app), notes, log, config_dir


def test_webhook_pushes_enabled_alerts(webhook_env):
    client, notes, log, _ = webhook_env
    client.post("/webhook", json={"event": "entry", "pair": "BTC/USD",
                                  "open_rate": "50000", "stake_amount": "100"})
    assert len(notes) == 1 and "BTC/USD" in notes[0]
    assert len(log.recent_events()) == 1


def test_webhook_respects_disabled_alerts(webhook_env):
    client, notes, log, _ = webhook_env
    client.post("/webhook", json={"event": "status", "status": "running"})
    assert notes == []                       # status alerts default off
    assert len(log.recent_events()) == 1     # ...but still logged


def test_webhook_toggle_off_silences_event(webhook_env):
    client, notes, log, config_dir = webhook_env
    risk_path = config_dir / "risk_settings.json"
    risk = json.loads(risk_path.read_text())
    risk["companion"]["alerts"]["exit_fill"] = False
    risk_path.write_text(json.dumps(risk))
    client.post("/webhook", json={"event": "exit_fill", "pair": "ETH/USD",
                                  "profit_ratio": "0.02"})
    assert notes == []
    assert len(log.recent_events()) == 1


# ── bot screens (real PTB keyboards, fake freqtrade API) ────────────────────

class FakeApi:
    def __init__(self, trades=None):
        self.trades = trades or []
        self.calls = []

    def total_balance(self):
        return 315.5

    def profit(self):
        return {"trade_count": 12, "profit_closed_coin": 15.5,
                "profit_closed_percent": 5.2, "winning_trades": 8,
                "losing_trades": 4}

    def open_trade_count(self):
        return len(self.trades)

    def show_config(self):
        return {"dry_run": True, "state": "running",
                "strategy": "E0V1EKraken", "max_open_trades": 3}

    def status(self):
        return self.trades

    def force_exit(self, trade_id):
        self.calls.append(("force_exit", str(trade_id)))

    def stop_entry(self):
        self.calls.append(("stop_entry",))
        return {"status": "paused"}

    def start(self):
        self.calls.append(("start",))
        return {"status": "running"}

    def reload_config(self):
        self.calls.append(("reload_config",))
        return {"status": "reloaded"}


def _trade(i):
    return {"trade_id": i, "pair": f"C{i}/USD", "profit_pct": i * 0.5,
            "open_date": "2026-07-01 10:00:00", "open_rate": 100 + i,
            "current_rate": 101 + i, "amount": 1.0}


@pytest.fixture
def bot(tmp_path):
    pytest.importorskip("telegram")
    from companion.settings_bot import CompanionBot

    config_dir = tmp_path / "config"
    shutil.copytree(REPO / "config", config_dir)
    api = FakeApi(trades=[_trade(i) for i in range(1, 8)])  # 7 open trades
    return CompanionBot("123:dummy", [111], config_dir, tmp_path / "data",
                        api, failure_log=None), api, config_dir


def _labels(keyboard):
    return [b.text for row in keyboard.inline_keyboard for b in row]


def test_home_screen_covers_all_sections(bot):
    companion_bot, _, _ = bot
    _, keyboard = companion_bot.home_screen()
    labels = " ".join(_labels(keyboard))
    for section in ("Dashboard", "Trades", "Risk", "Capital", "Bot",
                    "Alerts", "Failures", "Tax"):
        assert section in labels


def test_dashboard_screen_shows_mode_and_strategy(bot):
    companion_bot, _, _ = bot
    text, keyboard = companion_bot.dashboard_screen()
    assert "PAPER" in text and "E0V1EKraken" in text and "$315.50" in text
    assert "🏠 Home" in _labels(keyboard)


def test_trades_screen_paginates(bot):
    companion_bot, _, _ = bot
    text, keyboard = companion_bot.trades_screen(0)
    labels = _labels(keyboard)
    assert "1/3" in labels and "▶" in labels and "◀" not in labels
    # 3 trade buttons on page 0
    assert sum(1 for lbl in labels if lbl.startswith("C")) == 3
    _, keyboard2 = companion_bot.trades_screen(2)
    labels2 = _labels(keyboard2)
    assert "3/3" in labels2 and "◀" in labels2 and "▶" not in labels2


def test_trade_detail_and_confirm_screens(bot):
    companion_bot, _, _ = bot
    text, keyboard = companion_bot.trade_detail_screen("3")
    assert "C3/USD" in text and "❌ Force exit…" in _labels(keyboard)
    text2, keyboard2 = companion_bot.trade_detail_screen("3", confirm=True)
    assert "cannot be undone" in text2
    assert "✅ Confirm exit" in _labels(keyboard2)


def test_settings_screen_paginates_risk_fields(bot):
    companion_bot, _, _ = bot
    from companion.settings_bot import RISK_KEYS
    _, keyboard = companion_bot.settings_screen(RISK_KEYS, "🛡 Risk", "risk", 0)
    labels = _labels(keyboard)
    assert "1/2" in labels          # 6 fields at 4/page = 2 pages
    assert any(lbl.startswith("Stoploss") for lbl in labels)


def test_alerts_screen_and_toggle_write(bot):
    companion_bot, _, config_dir = bot
    _, keyboard = companion_bot.alerts_screen()
    labels = _labels(keyboard)
    assert any("Entry signals: on" in lbl for lbl in labels)
    assert any("Status messages: off" in lbl for lbl in labels)

    # simulate the toggle callback writing to disk
    class Query:
        data = "alerts:toggle:entry"
        message = None

        async def answer(self):
            pass

        async def edit_message_text(self, *a, **k):
            pass

    class Ctx:
        chat_data = {}

    asyncio.run(companion_bot._on_alerts(Query(), ["alerts", "toggle", "entry"]))
    risk = json.loads((config_dir / "risk_settings.json").read_text())
    assert risk["companion"]["alerts"]["entry"] is False


def test_force_exit_only_after_confirm(bot):
    companion_bot, api, _ = bot

    captured = {}

    class Query:
        data = ""
        message = None

        async def answer(self):
            pass

        async def edit_message_text(self, text, reply_markup=None):
            captured["text"] = text

    # tapping "❌ Force exit…" (confirm screen) must NOT exit yet
    asyncio.run(companion_bot._on_trade(Query(), None, ["trade", "3", "exit"]))
    assert api.calls == []
    # confirming does
    asyncio.run(companion_bot._on_trade(Query(), None,
                                        ["trade", "3", "exit_yes"]))
    assert ("force_exit", "3") in api.calls
    assert "Force-exit requested" in captured["text"]
