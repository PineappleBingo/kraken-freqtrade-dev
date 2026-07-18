"""Send alerts to the user through the settings bot's Telegram token."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_ids: list[int]):
        self.token = token
        self.chat_ids = chat_ids

    def send(self, message: str) -> None:
        if not self.token or not self.chat_ids:
            logger.info("Notify (telegram not configured): %s", message)
            return
        for chat_id in self.chat_ids:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": chat_id, "text": message},
                    timeout=10,
                )
            except requests.RequestException as exc:
                logger.warning("Telegram notify failed: %s", exc)
