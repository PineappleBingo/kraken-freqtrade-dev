"""FastAPI receiver for freqtrade webhook events -> event/failure back-log.

Also serves the backtest-lab comparison reports at /lab (read-only static)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .failure_log import FAILURE_EVENTS, FailureLog


def build_app(failure_log: FailureLog, notify=None,
              lab_reports_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="kraken-bot companion", docs_url=None, redoc_url=None)
    notify = notify or (lambda msg: None)

    if lab_reports_dir is not None:
        lab_reports_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/lab", StaticFiles(directory=str(lab_reports_dir),
                                      html=True), name="lab")

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
        failure_log.record(event, payload)
        if event in FAILURE_EVENTS:
            pair = payload.get("pair", "?")
            notify(f"⚠️ Order issue: {event} on {pair} "
                   f"(trade {payload.get('trade_id', '?')}). "
                   f"Logged for review — see 📋 Failures in the settings bot.")
        return {"ok": True}

    return app
