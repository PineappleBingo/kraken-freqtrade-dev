import csv
import json
import sqlite3
from pathlib import Path

import pytest

from companion import tax_logger
from companion.tax_logger import HEADERS, TaxLogger, trade_to_rows

SAMPLE_TRADE = {
    "id": 7,
    "pair": "BTC/USD",
    "amount": 0.001,
    "open_rate": 100000.0,
    "close_rate": 104000.0,
    "stake_amount": 100.0,
    "fee_open": 0.0025,
    "fee_close": 0.0025,
    "fee_open_cost": None,
    "fee_close_cost": None,
    "open_date": "2026-07-01 10:00:00.123456",
    "close_date": "2026-07-02 15:30:00.000000",
    "exit_reason": "roi",
}


def test_trade_to_rows_matches_coinledger_template():
    entry, exit_row = trade_to_rows(SAMPLE_TRADE)

    # entry: USD -> BTC
    assert entry.type == "Trade"
    assert entry.platform == "Kraken"
    assert (entry.asset_sent, entry.asset_received) == ("USD", "BTC")
    assert entry.amount_sent == "100"
    assert entry.amount_received == "0.001"
    assert entry.fee_currency == "USD"
    assert float(entry.fee_amount) == pytest.approx(0.25)   # 0.25% of $100
    assert entry.date_utc == "2026-07-01 10:00:00"

    # exit: BTC -> USD
    assert (exit_row.asset_sent, exit_row.asset_received) == ("BTC", "USD")
    assert exit_row.amount_sent == "0.001"
    assert float(exit_row.amount_received) == pytest.approx(104.0)
    assert float(exit_row.fee_amount) == pytest.approx(0.26)  # 0.25% of $104
    assert "roi" in exit_row.description
    assert exit_row.txhash == "ft-7-exit"

    # row shape matches the uploaded template's 11 columns
    assert len(entry.to_list()) == len(HEADERS) == 11


def test_fee_cost_columns_preferred_when_present():
    trade = dict(SAMPLE_TRADE, fee_open_cost=0.31, fee_close_cost=0.29)
    entry, exit_row = trade_to_rows(trade)
    assert float(entry.fee_amount) == pytest.approx(0.31)
    assert float(exit_row.fee_amount) == pytest.approx(0.29)


# ── end-to-end against a fake freqtrade DB ──────────────────────────────────

def make_trades_db(path: Path, trades: list[dict]) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, pair TEXT, amount REAL,"
        " open_rate REAL, close_rate REAL, stake_amount REAL, fee_open REAL,"
        " fee_close REAL, fee_open_cost REAL, fee_close_cost REAL,"
        " open_date TEXT, close_date TEXT, exit_reason TEXT, is_open INTEGER)")
    for trade in trades:
        con.execute(
            "INSERT INTO trades VALUES (:id, :pair, :amount, :open_rate,"
            " :close_rate, :stake_amount, :fee_open, :fee_close,"
            " :fee_open_cost, :fee_close_cost, :open_date, :close_date,"
            " :exit_reason, :is_open)", trade)
    con.commit()
    con.close()


@pytest.fixture
def env(tmp_path: Path):
    config_dir = tmp_path / "config"
    user_data = tmp_path / "user_data"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    user_data.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "dry_run": True,
        "db_url": "sqlite:////freqtrade/user_data/tradesv3.dryrun.sqlite",
    }))
    (config_dir / "risk_settings.json").write_text("{}")

    closed = dict(SAMPLE_TRADE, is_open=0)
    still_open = dict(SAMPLE_TRADE, id=8, is_open=1)
    make_trades_db(user_data / "tradesv3.dryrun.sqlite", [closed, still_open])

    logger = TaxLogger(config_dir, user_data, data_dir)
    return logger, data_dir, user_data


def test_run_once_writes_csv_and_state(env):
    logger, data_dir, user_data = env

    assert logger.run_once() == 1  # one closed trade
    csv_path = data_dir / "tax_log_paper.csv"  # dry_run -> paper file
    with open(csv_path) as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == HEADERS
    assert len(rows) == 3  # header + entry + exit
    assert rows[1][2] == "USD" and rows[1][4] == "BTC"

    # second run: nothing new, no duplicates
    assert logger.run_once() == 0
    with open(csv_path) as fh:
        assert len(list(csv.reader(fh))) == 3

    status = logger.status()
    assert status["last_synced_trade_id"] == 7
    assert status["dry_run"] is True
    assert status["sheets_configured"] is False


def test_new_trade_picked_up_incrementally(env):
    logger, data_dir, user_data = env
    logger.run_once()

    con = sqlite3.connect(user_data / "tradesv3.dryrun.sqlite")
    con.execute("UPDATE trades SET is_open = 0 WHERE id = 8")
    con.commit()
    con.close()

    assert logger.run_once() == 1
    with open(data_dir / "tax_log_paper.csv") as fh:
        assert len(list(csv.reader(fh))) == 5  # header + 2 trades x 2 rows


def test_db_path_mapping():
    cfg = {"db_url": "sqlite:////freqtrade/user_data/tradesv3.sqlite"}
    assert tax_logger.db_path_from_config(cfg, Path("/app/user_data")).name \
        == "tradesv3.sqlite"
    assert tax_logger.db_path_from_config({"dry_run": True}, Path("/x")).name \
        == "tradesv3.dryrun.sqlite"
