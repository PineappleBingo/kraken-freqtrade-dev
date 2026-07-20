"""Minimal REST client for the freqtrade API server (HTTP basic auth)."""

from __future__ import annotations

import requests


class FreqtradeApiError(Exception):
    pass


class FreqtradeApi:
    def __init__(self, base_url: str, username: str, password: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.timeout = timeout

    def _call(self, method: str, endpoint: str, payload: dict | None = None):
        url = f"{self.base_url}/api/v1/{endpoint}"
        try:
            resp = requests.request(
                method, url, json=payload, auth=self.auth, timeout=self.timeout)
        except requests.RequestException as exc:
            raise FreqtradeApiError(f"{method} {endpoint}: {exc}") from exc
        if resp.status_code >= 400:
            raise FreqtradeApiError(
                f"{method} {endpoint}: HTTP {resp.status_code} {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError:
            return {}

    # ── read ────────────────────────────────────────────────────────────────
    def ping(self) -> dict:
        return self._call("GET", "ping")

    def balance(self) -> dict:
        return self._call("GET", "balance")

    def total_balance(self) -> float:
        """Total account value in stake currency (USD)."""
        data = self.balance()
        return float(data.get("total", 0.0))

    def profit(self) -> dict:
        return self._call("GET", "profit")

    def status(self) -> list:
        return self._call("GET", "status")

    def open_trade_count(self) -> int:
        data = self._call("GET", "count")
        return int(data.get("current", 0))

    def show_config(self) -> dict:
        return self._call("GET", "show_config")

    # ── control ─────────────────────────────────────────────────────────────
    def start(self) -> dict:
        return self._call("POST", "start")

    def stop_entry(self) -> dict:
        """Pause new entries; open trades keep being managed."""
        return self._call("POST", "stopentry")

    def reload_config(self) -> dict:
        return self._call("POST", "reload_config")

    def force_exit(self, trade_id: int) -> dict:
        return self._call("POST", "forceexit", {"tradeid": str(trade_id)})

    def force_exit_all(self) -> int:
        exited = 0
        for trade in self.status():
            try:
                self.force_exit(trade["trade_id"])
                exited += 1
            except FreqtradeApiError:
                pass
        return exited
