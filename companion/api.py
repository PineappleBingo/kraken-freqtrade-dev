"""FastAPI receiver for freqtrade webhook events.

Every event is recorded in the back-log (events.sqlite). Events the user has
enabled in 🔔 Alerts (config/risk_settings.json -> companion.alerts) are also
pushed to Telegram through the unified bot — this replaces freqtrade's
built-in Telegram notifications entirely.

Also serves the backtest-lab comparison reports at /lab (read-only static).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import botui
from .failure_log import FAILURE_EVENTS, FailureLog


def build_app(failure_log: FailureLog, notify=None,
              lab_reports_dir: Path | None = None,
              config_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="kraken-bot companion", docs_url=None, redoc_url=None)
    notify = notify or (lambda msg: None)

    if lab_reports_dir is not None:
        lab_reports_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/lab", StaticFiles(directory=str(lab_reports_dir),
                                      html=True), name="lab")

    def _alert_enabled(event: str) -> bool:
        if config_dir is None:
            # No config wired (tests): keep failure alerts, mute the rest.
            return event in FAILURE_EVENTS
        try:
            from . import config_io
            return botui.alert_enabled(config_io.merged_config(config_dir),
                                       event)
        except Exception:
            return event in FAILURE_EVENTS

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhook")
    async def webhook(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {"raw": (await request.body()).decode("utf-8", "replace")}
        event = str(payload.get("event", "unknown"))
        failure_log.record(event, payload)   # always logged, alerts or not
        if _alert_enabled(event):
            message = botui.format_event(payload)
            if message:
                notify(message)
        return {"ok": True}

    return app
