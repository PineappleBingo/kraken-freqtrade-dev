"""Companion entrypoint: webhook API + capital manager + tax logger + settings bot.

Everything runs in one asyncio loop; the blocking pollers run in threads via
asyncio.to_thread so a slow Google Sheets call can't stall the webhook server.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from .api import build_app
from .capital_manager import CapitalManager
from .env import Env
from .failure_log import FailureLog
from .freqtrade_api import FreqtradeApi
from .notifier import TelegramNotifier
from .settings_bot import SettingsBot
from .tax_logger import TaxLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("companion")


async def poll_loop(name: str, interval: int, fn, failure_log: FailureLog):
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception as exc:  # keep the loop alive, but leave a trace
            logger.exception("%s failed", name)
            try:
                failure_log.record_error(name, str(exc))
            except Exception:
                pass
        await asyncio.sleep(interval)


async def run() -> None:
    Env.DATA_DIR.mkdir(parents=True, exist_ok=True)

    api = FreqtradeApi(Env.FREQTRADE_API_URL, Env.FREQTRADE_API_USERNAME,
                       Env.FREQTRADE_API_PASSWORD)
    notifier = TelegramNotifier(Env.SETTINGS_BOT_TOKEN, Env.SETTINGS_BOT_CHAT_IDS)
    failure_log = FailureLog(Env.DATA_DIR)
    tax_logger = TaxLogger(
        Env.CONFIG_DIR, Env.USER_DATA_DIR, Env.DATA_DIR,
        sheets_credentials=Env.GOOGLE_SHEETS_CREDENTIALS_FILE,
        spreadsheet_id=Env.GOOGLE_SHEETS_SPREADSHEET_ID,
        notify=notifier.send)
    capital_manager = CapitalManager(api, Env.CONFIG_DIR, Env.DATA_DIR,
                                     notify=notifier.send)

    tasks = []

    web_app = build_app(failure_log, notify=notifier.send,
                        lab_reports_dir=Env.DATA_DIR / "lab_reports")
    server = uvicorn.Server(uvicorn.Config(
        web_app, host="0.0.0.0", port=Env.WEBHOOK_PORT, log_level="warning"))
    tasks.append(asyncio.create_task(server.serve(), name="webhook-api"))

    tasks.append(asyncio.create_task(
        poll_loop("capital_manager", Env.CAPITAL_POLL_SECONDS,
                  capital_manager.run_once, failure_log),
        name="capital-manager"))
    tasks.append(asyncio.create_task(
        poll_loop("tax_logger", Env.TAX_LOG_POLL_SECONDS,
                  tax_logger.run_once, failure_log),
        name="tax-logger"))

    tg_app = None
    if Env.SETTINGS_BOT_TOKEN and Env.SETTINGS_BOT_CHAT_IDS:
        bot = SettingsBot(Env.SETTINGS_BOT_TOKEN, Env.SETTINGS_BOT_CHAT_IDS,
                          Env.CONFIG_DIR, Env.DATA_DIR, api,
                          tax_logger=tax_logger, failure_log=failure_log)
        tg_app = bot.build_application()
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Settings bot polling started")
    else:
        logger.warning("SETTINGS_BOT_TOKEN / SETTINGS_BOT_CHAT_IDS not set — "
                       "settings bot disabled")

    logger.info("Companion running (webhook :%s)", Env.WEBHOOK_PORT)
    try:
        await asyncio.gather(*tasks)
    finally:
        if tg_app is not None:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
