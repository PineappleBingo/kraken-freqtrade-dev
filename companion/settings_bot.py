"""The ONE Telegram bot for the whole stack: alerts + trades + settings.

freqtrade's built-in Telegram stays disabled; this bot covers everything
through inline buttons with pagination and consistent Back/Home navigation:

  🏠 Home
  ├ 📊 Dashboard   balance · profit · open trades · strategy · mode   [🔄]
  ├ 📈 Trades      paginated list → detail → ❌ Force exit → ✅ confirm
  ├ 🛡 Risk        settings fields (paginated) → tap → send new value
  ├ 💰 Capital     bank & reset knobs (same pattern)
  ├ 🤖 Bot         ⏸ Pause / ▶️ Resume / 🔄 Reload config
  ├ 🔔 Alerts      per-event on/off toggles (entry, fills, exits, cancels…)
  ├ 📋 Failures    paginated back-log from events.sqlite
  └ 🧾 Tax         sync status

Trade alerts themselves are pushed by the webhook receiver (companion/api.py)
through the same bot token — see companion/botui.py for formatting/prefs.
Every settings change is bounds-validated, written atomically, applied live
via freqtrade /reload_config, and appended to data/audit_log.jsonl.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from . import botui, config_io
from .freqtrade_api import FreqtradeApi, FreqtradeApiError

logger = logging.getLogger(__name__)

RISK_KEYS = ["stoploss", "max_open_trades", "available_capital",
             "trailing_stop", "trailing_stop_positive",
             "trailing_stop_positive_offset"]
CAPITAL_KEYS = ["cm_enabled", "cm_profit_target", "cm_set_aside",
                "cm_restart_capital", "cm_force_exit"]

FIELDS_PER_PAGE = 4
TRADES_PER_PAGE = 3
FAILURES_PER_PAGE = 5


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def _btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)


def _home_row() -> list[InlineKeyboardButton]:
    return [_btn("🏠 Home", "home")]


class CompanionBot:
    def __init__(self, token: str, chat_ids: list[int], config_dir: Path,
                 data_dir: Path, api: FreqtradeApi, tax_logger=None,
                 failure_log=None):
        self.token = token
        self.chat_ids = set(chat_ids)
        self.config_dir = config_dir
        self.audit_path = data_dir / "audit_log.jsonl"
        self.api = api
        self.tax_logger = tax_logger
        self.failure_log = failure_log

    # ── shared helpers ──────────────────────────────────────────────────────
    def _authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        ok = chat is not None and chat.id in self.chat_ids
        if not ok and chat is not None:
            logger.warning("Rejected chat id %s", chat.id)
        return ok

    def _audit(self, chat_id: int, field: str, old, new) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "chat_id": chat_id, "field": field, "old": old, "new": new,
            }) + "\n")

    def _current(self, key: str):
        spec = config_io.FIELDS[key]
        data = config_io.load_json(self.config_dir / spec.file)
        return config_io.get_path(data, list(spec.path))

    @staticmethod
    async def _show(query_or_msg, text: str, keyboard: InlineKeyboardMarkup):
        """Edit in place for button taps; send new for command messages."""
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text(text, reply_markup=keyboard)
        else:
            await query_or_msg.reply_text(text, reply_markup=keyboard)

    # ── screens ─────────────────────────────────────────────────────────────
    def home_screen(self):
        text = "🏠 Kraken bot — pick a section:"
        keyboard = InlineKeyboardMarkup([
            [_btn("📊 Dashboard", "dash"), _btn("📈 Trades", "trades:0")],
            [_btn("🛡 Risk", "risk:0"), _btn("💰 Capital", "capital:0")],
            [_btn("🤖 Bot", "bot"), _btn("🔔 Alerts", "alerts")],
            [_btn("📋 Failures", "fail:0"), _btn("🧾 Tax", "tax")],
        ])
        return text, keyboard

    def dashboard_screen(self):
        try:
            total = self.api.total_balance()
            profit = self.api.profit()
            open_n = self.api.open_trade_count()
            cfg = self.api.show_config()
        except FreqtradeApiError as exc:
            return (f"⚠️ freqtrade API unreachable:\n{exc}",
                    InlineKeyboardMarkup([[_btn("🔄 Retry", "dash")],
                                          _home_row()]))
        mode = "🧪 PAPER (dry-run)" if cfg.get("dry_run", True) else "🔴 LIVE"
        text = (
            f"📊 Dashboard\n"
            f"{mode} · {cfg.get('state', '?')}\n"
            f"Strategy: {cfg.get('strategy', '?')}\n"
            f"\n"
            f"Balance: ${total:,.2f}\n"
            f"Open trades: {open_n}/{cfg.get('max_open_trades', '?')}\n"
            f"Closed trades: {profit.get('trade_count', 0)}\n"
            f"Total profit: ${profit.get('profit_closed_coin', 0):,.2f} "
            f"({profit.get('profit_closed_percent', 0)}%)\n"
            f"Win/Loss: {profit.get('winning_trades', 0)}/"
            f"{profit.get('losing_trades', 0)}"
        )
        keyboard = InlineKeyboardMarkup([
            [_btn("🔄 Refresh", "dash"), _btn("📈 Trades", "trades:0")],
            _home_row(),
        ])
        return text, keyboard

    def trades_screen(self, page: int):
        try:
            trades = self.api.status()
        except FreqtradeApiError as exc:
            return (f"⚠️ freqtrade API unreachable:\n{exc}",
                    InlineKeyboardMarkup([[_btn("🔄 Retry", f"trades:{page}")],
                                          _home_row()]))
        if not trades:
            return ("📈 No open trades right now.",
                    InlineKeyboardMarkup([[_btn("🔄 Refresh", "trades:0")],
                                          _home_row()]))
        page_items, page, total_pages = botui.paginate(
            trades, page, TRADES_PER_PAGE)
        rows = []
        for trade in page_items:
            profit = trade.get("profit_pct")
            if profit is None:
                profit = round(float(trade.get("profit_ratio") or 0) * 100, 2)
            rows.append([_btn(
                f"{trade.get('pair', '?')}  {profit:+.2f}%  "
                f"#{trade.get('trade_id')}",
                f"trade:{trade.get('trade_id')}")])
        pager = [_btn(label, data) for label, data in
                 botui.pager_row("trades", page, total_pages)]
        if pager:
            rows.append(pager)
        rows.append(_home_row())
        return (f"📈 Open trades ({len(trades)}) — tap one for details:",
                InlineKeyboardMarkup(rows))

    def _find_trade(self, trade_id: str) -> dict | None:
        for trade in self.api.status():
            if str(trade.get("trade_id")) == str(trade_id):
                return trade
        return None

    def trade_detail_screen(self, trade_id: str, confirm: bool = False):
        try:
            trade = self._find_trade(trade_id)
        except FreqtradeApiError as exc:
            return (f"⚠️ freqtrade API unreachable:\n{exc}",
                    InlineKeyboardMarkup([_home_row()]))
        if trade is None:
            return (f"Trade #{trade_id} is no longer open.",
                    InlineKeyboardMarkup([[_btn("📈 Trades", "trades:0")],
                                          _home_row()]))
        profit = trade.get("profit_pct")
        if profit is None:
            profit = round(float(trade.get("profit_ratio") or 0) * 100, 2)
        text = (
            f"📈 Trade #{trade.get('trade_id')} — {trade.get('pair')}\n"
            f"Opened: {str(trade.get('open_date', ''))[:16]}\n"
            f"Entry: {trade.get('open_rate')}\n"
            f"Now:   {trade.get('current_rate', '?')}\n"
            f"Amount: {trade.get('amount')}\n"
            f"Profit: {profit:+.2f}%"
        )
        if confirm:
            text += ("\n\n❗ Force-exit this trade at market price now?\n"
                     "This cannot be undone.")
            keyboard = InlineKeyboardMarkup([
                [_btn("✅ Confirm exit", f"trade:{trade_id}:exit_yes"),
                 _btn("⬅️ Cancel", f"trade:{trade_id}")],
                _home_row(),
            ])
        else:
            keyboard = InlineKeyboardMarkup([
                [_btn("❌ Force exit…", f"trade:{trade_id}:exit")],
                [_btn("⬅️ Back", "trades:0")],
                _home_row(),
            ])
        return text, keyboard

    def settings_screen(self, keys: list[str], title: str, prefix: str,
                        page: int):
        page_keys, page, total_pages = botui.paginate(
            keys, page, FIELDS_PER_PAGE)
        rows = [
            [_btn(f"{config_io.FIELDS[k].label}: "
                  f"{_fmt_value(self._current(k))}",
                  f"edit:{k}:{prefix}:{page}")]
            for k in page_keys
        ]
        pager = [_btn(label, data) for label, data in
                 botui.pager_row(prefix, page, total_pages)]
        if pager:
            rows.append(pager)
        rows.append(_home_row())
        return f"{title} — tap a field to change it:", InlineKeyboardMarkup(rows)

    def bot_screen(self, note: str = ""):
        try:
            cfg = self.api.show_config()
            state = cfg.get("state", "?")
            strategy = cfg.get("strategy", "?")
        except FreqtradeApiError:
            state, strategy = "unreachable", "?"
        text = (f"🤖 Bot control\nState: {state}\nStrategy: {strategy}")
        if note:
            text = f"{note}\n\n{text}"
        keyboard = InlineKeyboardMarkup([
            [_btn("⏸ Pause entries", "bot:pause"),
             _btn("▶️ Resume", "bot:resume")],
            [_btn("🔄 Reload config", "bot:reload")],
            _home_row(),
        ])
        return text, keyboard

    def alerts_screen(self):
        merged = config_io.merged_config(self.config_dir)
        prefs = botui.get_alert_prefs(merged)
        rows = [
            [_btn(f"{botui.ALERT_LABELS[event]}: "
                  f"{'on ✅' if prefs[event] else 'off ⬜'}",
                  f"alerts:toggle:{event}")]
            for event in botui.ALERT_EVENTS
        ]
        rows.append(_home_row())
        return ("🔔 Alerts — tap to toggle what this bot pushes to you:",
                InlineKeyboardMarkup(rows))

    def failures_screen(self, page: int):
        rows_data = (self.failure_log.recent_failures(50)
                     if self.failure_log else [])
        if not rows_data:
            return ("📋 No failures recorded. 🎉",
                    InlineKeyboardMarkup([_home_row()]))
        page_items, page, total_pages = botui.paginate(
            rows_data, page, FAILURES_PER_PAGE)
        lines = [f"📋 Failures ({len(rows_data)}) — newest first:"]
        for row in page_items:
            lines.append(f"• {row['ts']} {row['event']} {row['pair']}"
                         f" #{row['trade_id']} {row['detail']}")
        buttons = []
        pager = [_btn(label, data) for label, data in
                 botui.pager_row("fail", page, total_pages)]
        if pager:
            buttons.append(pager)
        buttons.append(_home_row())
        return "\n".join(lines), InlineKeyboardMarkup(buttons)

    def tax_screen(self):
        if self.tax_logger is None:
            text = "🧾 Tax logger not running."
        else:
            info = self.tax_logger.status()
            mode = "PAPER (dry-run)" if info["dry_run"] else "LIVE"
            sheets = ("connected" if info["sheets_configured"]
                      else "not configured (CSV only)")
            text = (f"🧾 Tax log status\n"
                    f"Mode: {mode}\n"
                    f"Last synced trade id: {info['last_synced_trade_id']}\n"
                    f"Google Sheets: {sheets}\n"
                    f"Rows waiting for Sheets retry: {info['pending_sheet_rows']}")
        return text, InlineKeyboardMarkup([_home_row()])

    # ── command handlers ────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        context.chat_data.pop("pending_field", None)
        text, keyboard = self.home_screen()
        await update.effective_message.reply_text(text, reply_markup=keyboard)

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        context.chat_data.pop("pending_field", None)
        text, keyboard = self.home_screen()
        await update.effective_message.reply_text(
            f"Cancelled.\n\n{text}", reply_markup=keyboard)

    # ── callback router ─────────────────────────────────────────────────────
    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        query = update.callback_query
        await query.answer()
        parts = botui.parse_callback(query.data)
        head = parts[0] if parts else ""

        if head == "noop":
            return
        if head == "home":
            context.chat_data.pop("pending_field", None)
            await self._show(query, *self.home_screen())
        elif head == "dash":
            await self._show(query, *self.dashboard_screen())
        elif head == "trades":
            page = int(parts[1]) if len(parts) > 1 else 0
            await self._show(query, *self.trades_screen(page))
        elif head == "trade":
            await self._on_trade(query, context, parts)
        elif head == "risk":
            page = int(parts[1]) if len(parts) > 1 else 0
            await self._show(query, *self.settings_screen(
                RISK_KEYS, "🛡 Risk settings", "risk", page))
        elif head == "capital":
            page = int(parts[1]) if len(parts) > 1 else 0
            await self._show(query, *self.settings_screen(
                CAPITAL_KEYS, "💰 Capital management", "capital", page))
        elif head == "edit":
            await self._begin_edit(query, context, parts)
        elif head == "bot":
            await self._on_bot(query, parts)
        elif head == "alerts":
            await self._on_alerts(query, parts)
        elif head == "fail":
            page = int(parts[1]) if len(parts) > 1 else 0
            await self._show(query, *self.failures_screen(page))
        elif head == "tax":
            await self._show(query, *self.tax_screen())

    async def _on_trade(self, query, context, parts: list[str]):
        trade_id = parts[1] if len(parts) > 1 else ""
        action = parts[2] if len(parts) > 2 else ""
        if action == "exit":
            await self._show(query, *self.trade_detail_screen(trade_id,
                                                              confirm=True))
        elif action == "exit_yes":
            try:
                self.api.force_exit(trade_id)
                self._audit(query.message.chat.id if query.message else 0,
                            "force_exit", trade_id, "requested")
                text = (f"❌ Force-exit requested for trade #{trade_id}.\n"
                        "You'll get an exit alert when it fills.")
            except FreqtradeApiError as exc:
                text = f"⚠️ Force-exit failed: {exc}"
            await self._show(query, text, InlineKeyboardMarkup(
                [[_btn("📈 Trades", "trades:0")], _home_row()]))
        else:
            await self._show(query, *self.trade_detail_screen(trade_id))

    async def _begin_edit(self, query, context, parts: list[str]):
        key = parts[1] if len(parts) > 1 else ""
        spec = config_io.FIELDS.get(key)
        if spec is None:
            return
        return_screen = ":".join(parts[2:4]) if len(parts) > 3 else "home"
        context.chat_data["pending_field"] = key
        context.chat_data["return_screen"] = return_screen
        bounds = ""
        if spec.type == "bool":
            bounds = "Send: on / off"
        elif spec.min is not None or spec.max is not None:
            bounds = f"Range: {spec.min} … {spec.max}"
        text = (f"✏️ {spec.label}\n"
                f"Current: {_fmt_value(self._current(key))}\n"
                f"{spec.help}\n{bounds}\n\n"
                "Send the new value as a message, or /cancel.")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
            [[_btn("⬅️ Back", return_screen)], _home_row()]))

    async def on_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        key = context.chat_data.get("pending_field")
        if not key:
            text, keyboard = self.home_screen()
            await update.effective_message.reply_text(text,
                                                      reply_markup=keyboard)
            return
        spec = config_io.FIELDS[key]
        raw = update.effective_message.text or ""
        try:
            value = config_io.validate_and_cast(spec, raw)
        except ValueError as exc:
            await update.effective_message.reply_text(
                f"❌ {exc}. Try again, or /cancel.")
            return

        old, warnings = config_io.update_field(self.config_dir, spec, value)
        self._audit(update.effective_chat.id, spec.key, old, value)
        context.chat_data.pop("pending_field", None)
        return_screen = context.chat_data.pop("return_screen", "home")

        try:
            self.api.reload_config()
            reload_note = "✅ Applied live (config reloaded)."
        except FreqtradeApiError as exc:
            reload_note = f"⚠️ Saved, but reload failed: {exc}"

        lines = [f"✅ {spec.label}: {_fmt_value(old)} → {_fmt_value(value)}",
                 reload_note]
        lines += [f"⚠️ {warning}" for warning in warnings]
        await update.effective_message.reply_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(
                [[_btn("⬅️ Back", return_screen)], _home_row()]))

    async def _on_bot(self, query, parts: list[str]):
        action = parts[1] if len(parts) > 1 else ""
        note = ""
        try:
            if action == "pause":
                res = self.api.stop_entry()
                note = f"⏸ {res.get('status', 'paused — no new entries')}"
            elif action == "resume":
                res = self.api.start()
                note = f"▶️ {res.get('status', 'running')}"
            elif action == "reload":
                res = self.api.reload_config()
                note = f"🔄 {res.get('status', 'config reloaded')}"
        except FreqtradeApiError as exc:
            note = f"⚠️ freqtrade API error: {exc}"
        await self._show(query, *self.bot_screen(note))

    async def _on_alerts(self, query, parts: list[str]):
        if len(parts) > 2 and parts[1] == "toggle":
            event = parts[2]
            if event in botui.ALERT_EVENTS:
                risk_path = self.config_dir / config_io.RISK_FILE
                risk = config_io.load_json(risk_path)
                merged = config_io.merged_config(self.config_dir)
                current = botui.get_alert_prefs(merged)[event]
                config_io.set_path(risk, ["companion", "alerts", event],
                                   not current)
                config_io.save_json_atomic(risk_path, risk)
                self._audit(query.message.chat.id if query.message else 0,
                            f"alerts.{event}", current, not current)
        await self._show(query, *self.alerts_screen())

    # ── wiring ──────────────────────────────────────────────────────────────
    def build_application(self) -> Application:
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler(["start", "menu", "settings", "home"],
                                       self.cmd_start))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                       self.on_value))
        return app


# Backwards-compatible alias (older imports/tests).
SettingsBot = CompanionBot
