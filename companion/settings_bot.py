"""Telegram settings bot (bot #2): edit risk & capital settings with buttons.

Menu tree:
  ⚙️ Settings
  ├── 🛡 Risk        → one button per field → tap → send new value
  ├── 💰 Capital     → profit target / set aside / restart capital / on-off
  ├── 🤖 Bot control → pause / resume / reload / status
  ├── 📋 Failures    → last failures from the back-log
  └── 🧾 Tax log     → sync status

Every change is bounds-validated (companion.config_io.FIELDS), written
atomically to config/risk_settings.json, applied live via freqtrade
/reload_config, and appended to data/audit_log.jsonl.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from . import config_io
from .freqtrade_api import FreqtradeApi, FreqtradeApiError

logger = logging.getLogger(__name__)

RISK_KEYS = ["stoploss", "max_open_trades", "available_capital",
             "trailing_stop", "trailing_stop_positive",
             "trailing_stop_positive_offset"]
CAPITAL_KEYS = ["cm_enabled", "cm_profit_target", "cm_set_aside",
                "cm_restart_capital", "cm_force_exit"]


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


class SettingsBot:
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

    # ── helpers ─────────────────────────────────────────────────────────────
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
                "chat_id": chat_id, "field": field,
                "old": old, "new": new,
            }) + "\n")

    def _current(self, key: str):
        spec = config_io.FIELDS[key]
        data = config_io.load_json(self.config_dir / spec.file)
        return config_io.get_path(data, list(spec.path))

    def _field_keyboard(self, keys: list[str], back: str) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(
                f"{config_io.FIELDS[key].label}: {_fmt_value(self._current(key))}",
                callback_data=f"edit:{key}")]
            for key in keys
        ]
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back)])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _main_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡 Risk", callback_data="menu:risk"),
             InlineKeyboardButton("💰 Capital", callback_data="menu:capital")],
            [InlineKeyboardButton("🤖 Bot control", callback_data="menu:bot")],
            [InlineKeyboardButton("📋 Failures", callback_data="menu:failures"),
             InlineKeyboardButton("🧾 Tax log", callback_data="menu:tax")],
        ])

    def _bot_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸ Pause entries", callback_data="bot:pause"),
             InlineKeyboardButton("▶️ Resume", callback_data="bot:resume")],
            [InlineKeyboardButton("🔄 Reload config", callback_data="bot:reload"),
             InlineKeyboardButton("📊 Status", callback_data="bot:status")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu:main")],
        ])

    # ── handlers ────────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        context.chat_data.pop("pending_field", None)
        await update.effective_message.reply_text(
            "⚙️ Kraken bot settings — pick a section:",
            reply_markup=self._main_keyboard())

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        query = update.callback_query
        await query.answer()
        data = query.data or ""

        if data == "menu:main":
            context.chat_data.pop("pending_field", None)
            await query.edit_message_text("⚙️ Kraken bot settings — pick a section:",
                                          reply_markup=self._main_keyboard())
        elif data == "menu:risk":
            await query.edit_message_text(
                "🛡 Risk settings (tap a field to change it):",
                reply_markup=self._field_keyboard(RISK_KEYS, "menu:main"))
        elif data == "menu:capital":
            await query.edit_message_text(
                "💰 Capital management (bank & reset):",
                reply_markup=self._field_keyboard(CAPITAL_KEYS, "menu:main"))
        elif data == "menu:bot":
            await query.edit_message_text("🤖 Bot control:",
                                          reply_markup=self._bot_keyboard())
        elif data == "menu:failures":
            await self._show_failures(query)
        elif data == "menu:tax":
            await self._show_tax(query)
        elif data.startswith("edit:"):
            await self._begin_edit(query, context, data.split(":", 1)[1])
        elif data.startswith("bot:"):
            await self._bot_action(query, data.split(":", 1)[1])

    async def _begin_edit(self, query, context, key: str):
        spec = config_io.FIELDS.get(key)
        if spec is None:
            return
        context.chat_data["pending_field"] = key
        bounds = ""
        if spec.type == "bool":
            bounds = "Send: on / off"
        elif spec.min is not None or spec.max is not None:
            bounds = f"Range: {spec.min} … {spec.max}"
        text = (f"✏️ {spec.label}\n"
                f"Current: {_fmt_value(self._current(key))}\n"
                f"{spec.help}\n{bounds}\n\n"
                "Send the new value as a message, or /cancel.")
        await query.edit_message_text(text)

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        context.chat_data.pop("pending_field", None)
        await update.effective_message.reply_text(
            "Cancelled.", reply_markup=self._main_keyboard())

    async def on_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        key = context.chat_data.get("pending_field")
        if not key:
            await update.effective_message.reply_text(
                "Use /start to open the settings menu.")
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

        reload_note = ""
        try:
            self.api.reload_config()
            reload_note = "✅ Applied live (config reloaded)."
        except FreqtradeApiError as exc:
            reload_note = f"⚠️ Saved, but reload failed: {exc}"

        lines = [f"✅ {spec.label}: {_fmt_value(old)} → {_fmt_value(value)}",
                 reload_note]
        lines += [f"⚠️ {warning}" for warning in warnings]
        await update.effective_message.reply_text(
            "\n".join(lines), reply_markup=self._main_keyboard())

    async def _bot_action(self, query, action: str):
        try:
            if action == "pause":
                res = self.api.stop_entry()
                text = f"⏸ {res.get('status', 'paused — no new entries')}"
            elif action == "resume":
                res = self.api.start()
                text = f"▶️ {res.get('status', 'running')}"
            elif action == "reload":
                res = self.api.reload_config()
                text = f"🔄 {res.get('status', 'config reloaded')}"
            elif action == "status":
                profit = self.api.profit()
                total = self.api.total_balance()
                open_n = self.api.open_trade_count()
                text = (
                    f"📊 Balance: ${total:,.2f}\n"
                    f"Open trades: {open_n}\n"
                    f"Closed trades: {profit.get('trade_count', 0)}\n"
                    f"Total profit: {profit.get('profit_closed_coin', 0):.2f} USD "
                    f"({profit.get('profit_closed_percent', 0)}%)\n"
                    f"Win/Loss: {profit.get('winning_trades', 0)}/"
                    f"{profit.get('losing_trades', 0)}"
                )
            else:
                return
        except FreqtradeApiError as exc:
            text = f"⚠️ freqtrade API error: {exc}"
        await query.edit_message_text(text, reply_markup=self._bot_keyboard())

    async def _show_failures(self, query):
        rows = self.failure_log.recent_failures(10) if self.failure_log else []
        if not rows:
            text = "📋 No failures recorded. 🎉"
        else:
            lines = ["📋 Recent failures (newest first):"]
            for row in rows:
                lines.append(f"• {row['ts']} {row['event']} {row['pair']}"
                             f" #{row['trade_id']} {row['detail']}")
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="menu:main")]]))

    async def _show_tax(self, query):
        if self.tax_logger is None:
            text = "🧾 Tax logger not running."
        else:
            info = self.tax_logger.status()
            mode = "PAPER (dry-run)" if info["dry_run"] else "LIVE"
            sheets = "connected" if info["sheets_configured"] else "not configured (CSV only)"
            text = (f"🧾 Tax log status\n"
                    f"Mode: {mode}\n"
                    f"Last synced trade id: {info['last_synced_trade_id']}\n"
                    f"Google Sheets: {sheets}\n"
                    f"Rows waiting for Sheets retry: {info['pending_sheet_rows']}")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="menu:main")]]))

    # ── wiring ──────────────────────────────────────────────────────────────
    def build_application(self) -> Application:
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler(["start", "menu", "settings"], self.cmd_start))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                       self.on_value))
        return app
