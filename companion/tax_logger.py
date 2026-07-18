"""Turn closed freqtrade trades into CoinLedger "Universal Manual Import" rows.

Each closed trade produces TWO rows (both Type=Trade):
  entry:  USD -> coin   (Amount Sent = stake cost, Amount Received = coin amount)
  exit:   coin -> USD   (Amount Sent = coin amount, Amount Received = proceeds)
Fees are reported in the separate fee columns (Kraken charges spot fees in the
quote currency, USD here).

Rows are ALWAYS appended to a local CSV (your permanent backup) and, when
Google Sheets credentials are configured, also appended to the spreadsheet.
Failed Sheets appends are queued and retried, so nothing is lost.
Dry-run (paper) trades go to a separate tab/file so they never pollute your
real tax report.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

HEADERS = [
    "Date (UTC)", "Platform (Optional)", "Asset Sent", "Amount Sent",
    "Asset Received", "Amount Received", "Fee Currency (Optional)",
    "Fee Amount (Optional)", "Type", "Description (Optional)",
    "TxHash (Optional)",
]


@dataclass
class LedgerRow:
    date_utc: str
    platform: str
    asset_sent: str
    amount_sent: str
    asset_received: str
    amount_received: str
    fee_currency: str
    fee_amount: str
    type: str
    description: str
    txhash: str

    def to_list(self) -> list[str]:
        return [
            self.date_utc, self.platform, self.asset_sent, self.amount_sent,
            self.asset_received, self.amount_received, self.fee_currency,
            self.fee_amount, self.type, self.description, self.txhash,
        ]


def _fmt(value: float, places: int = 10) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


def _fmt_date(raw) -> str:
    # freqtrade stores UTC naive datetimes like "2026-07-18 03:20:11.123456"
    text = str(raw)
    return text.split(".")[0]


def trade_to_rows(trade: dict, platform: str = "Kraken") -> list[LedgerRow]:
    """Convert one closed freqtrade trade (dict of DB columns) to ledger rows."""
    base, quote = trade["pair"].split("/")
    amount = float(trade["amount"])
    open_rate = float(trade["open_rate"])
    close_rate = float(trade["close_rate"])
    stake = float(trade.get("stake_amount") or amount * open_rate)
    proceeds = amount * close_rate

    fee_open = trade.get("fee_open_cost")
    if fee_open is None:
        fee_open = stake * float(trade.get("fee_open") or 0)
    fee_close = trade.get("fee_close_cost")
    if fee_close is None:
        fee_close = proceeds * float(trade.get("fee_close") or 0)

    trade_id = trade["id"]
    exit_reason = trade.get("exit_reason") or ""

    entry = LedgerRow(
        date_utc=_fmt_date(trade["open_date"]),
        platform=platform,
        asset_sent=quote,
        amount_sent=_fmt(stake, 2),
        asset_received=base,
        amount_received=_fmt(amount),
        fee_currency=quote if fee_open else "",
        fee_amount=_fmt(float(fee_open), 6) if fee_open else "",
        type="Trade",
        description=f"freqtrade #{trade_id} entry",
        txhash=f"ft-{trade_id}-entry",
    )
    exit_row = LedgerRow(
        date_utc=_fmt_date(trade["close_date"]),
        platform=platform,
        asset_sent=base,
        amount_sent=_fmt(amount),
        asset_received=quote,
        amount_received=_fmt(proceeds, 2),
        fee_currency=quote if fee_close else "",
        fee_amount=_fmt(float(fee_close), 6) if fee_close else "",
        type="Trade",
        description=f"freqtrade #{trade_id} exit ({exit_reason})",
        txhash=f"ft-{trade_id}-exit",
    )
    return [entry, exit_row]


# ── trade source (freqtrade sqlite DB, read-only) ───────────────────────────

def db_path_from_config(cfg: dict, user_data_dir: Path) -> Path:
    """Map the container db_url in the freqtrade config to our mounted path."""
    db_url = cfg.get("db_url", "")
    name = db_url.rsplit("/", 1)[-1] if db_url else ""
    if not name.endswith(".sqlite"):
        name = "tradesv3.dryrun.sqlite" if cfg.get("dry_run", True) else "tradesv3.sqlite"
    return user_data_dir / name


def fetch_closed_trades(db_path: Path, after_id: int) -> list[dict]:
    if not db_path.exists():
        return []
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(trades)")}
        wanted = ["id", "pair", "amount", "open_rate", "close_rate",
                  "stake_amount", "fee_open", "fee_close", "open_date",
                  "close_date", "exit_reason", "fee_open_cost", "fee_close_cost"]
        select = ", ".join(c for c in wanted if c in cols)
        rows = con.execute(
            f"SELECT {select} FROM trades "
            "WHERE is_open = 0 AND id > ? ORDER BY id", (after_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


# ── sinks ───────────────────────────────────────────────────────────────────

class CsvSink:
    def __init__(self, path: Path):
        self.path = path

    def append(self, rows: list[LedgerRow]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        with open(self.path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(HEADERS)
            for row in rows:
                writer.writerow(row.to_list())


class GoogleSheetsSink:
    """Appends rows to a worksheet; lazy-imports gspread so the companion
    runs fine without Google credentials configured."""

    def __init__(self, credentials_file: str, spreadsheet_id: str, worksheet: str):
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet

    @property
    def configured(self) -> bool:
        return bool(self.credentials_file and self.spreadsheet_id
                    and Path(self.credentials_file).exists())

    def _worksheet(self):
        import gspread
        client = gspread.service_account(filename=self.credentials_file)
        book = client.open_by_key(self.spreadsheet_id)
        try:
            sheet = book.worksheet(self.worksheet_name)
        except gspread.WorksheetNotFound:
            sheet = book.add_worksheet(self.worksheet_name, rows=2000, cols=len(HEADERS))
            sheet.append_row(HEADERS)
        if not sheet.row_values(1):
            sheet.append_row(HEADERS)
        return sheet

    def append(self, rows: list[LedgerRow]) -> None:
        sheet = self._worksheet()
        sheet.append_rows([row.to_list() for row in rows],
                          value_input_option="USER_ENTERED")


# ── orchestration ───────────────────────────────────────────────────────────

class TaxLogger:
    def __init__(self, config_dir: Path, user_data_dir: Path, data_dir: Path,
                 sheets_credentials: str = "", spreadsheet_id: str = "",
                 notify=None):
        self.config_dir = config_dir
        self.user_data_dir = user_data_dir
        self.data_dir = data_dir
        self.state_path = data_dir / "tax_state.json"
        self.pending_path = data_dir / "sheets_pending.jsonl"
        self.sheets_credentials = sheets_credentials
        self.spreadsheet_id = spreadsheet_id
        self.notify = notify or (lambda msg: None)

    def _load_state(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)

    def _queue_pending(self, worksheet: str, rows: list[LedgerRow]) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pending_path, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps({"ws": worksheet, "row": row.to_list()}) + "\n")

    def _retry_pending(self) -> None:
        if not self.pending_path.exists():
            return
        with open(self.pending_path, "r", encoding="utf-8") as fh:
            items = [json.loads(line) for line in fh if line.strip()]
        if not items:
            return
        by_ws: dict[str, list[list[str]]] = {}
        for item in items:
            by_ws.setdefault(item["ws"], []).append(item["row"])
        try:
            for ws, raw_rows in by_ws.items():
                sink = GoogleSheetsSink(self.sheets_credentials,
                                        self.spreadsheet_id, ws)
                sheet = sink._worksheet()
                sheet.append_rows(raw_rows, value_input_option="USER_ENTERED")
            self.pending_path.unlink()
        except Exception:
            pass  # still queued; retried next cycle

    def run_once(self) -> int:
        """Sync newly closed trades. Returns number of trades synced."""
        from . import config_io

        cfg = config_io.merged_config(self.config_dir)
        dry_run = bool(cfg.get("dry_run", True))
        db_path = db_path_from_config(cfg, self.user_data_dir)
        worksheet = "PaperTrades" if dry_run else "Transactions"
        csv_name = "tax_log_paper.csv" if dry_run else "tax_log.csv"

        state = self._load_state()
        last_id = int(state.get(db_path.name, 0))
        trades = fetch_closed_trades(db_path, last_id)
        if not trades:
            if self.sheets_credentials and self.spreadsheet_id:
                self._retry_pending()
            return 0

        rows: list[LedgerRow] = []
        for trade in trades:
            rows.extend(trade_to_rows(trade))

        # 1) local CSV backup — must never fail silently
        CsvSink(self.data_dir / csv_name).append(rows)

        # 2) Google Sheets (optional)
        sink = GoogleSheetsSink(self.sheets_credentials, self.spreadsheet_id,
                                worksheet)
        if sink.configured:
            try:
                self._retry_pending()
                sink.append(rows)
            except Exception as exc:
                self._queue_pending(worksheet, rows)
                self.notify(f"⚠️ Google Sheets sync failed ({exc}); rows queued "
                            f"for retry and saved to {csv_name}.")

        state[db_path.name] = trades[-1]["id"]
        self._save_state(state)
        return len(trades)

    def status(self) -> dict:
        from . import config_io
        cfg = config_io.merged_config(self.config_dir)
        db_path = db_path_from_config(cfg, self.user_data_dir)
        state = self._load_state()
        pending = 0
        if self.pending_path.exists():
            with open(self.pending_path, "r", encoding="utf-8") as fh:
                pending = sum(1 for line in fh if line.strip())
        return {
            "dry_run": bool(cfg.get("dry_run", True)),
            "db": db_path.name,
            "last_synced_trade_id": state.get(db_path.name, 0),
            "sheets_configured": GoogleSheetsSink(
                self.sheets_credentials, self.spreadsheet_id, "x").configured,
            "pending_sheet_rows": pending,
        }
