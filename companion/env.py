"""Environment configuration for the companion service."""

import os
from pathlib import Path


def _split_ids(raw: str) -> list[int]:
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


class Env:
    CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/app/config"))
    USER_DATA_DIR = Path(os.environ.get("USER_DATA_DIR", "/app/user_data"))
    DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))

    FREQTRADE_API_URL = os.environ.get("FREQTRADE_API_URL", "http://freqtrade:8080")
    FREQTRADE_API_USERNAME = os.environ.get("FREQTRADE__API_SERVER__USERNAME", "freqtrader")
    FREQTRADE_API_PASSWORD = os.environ.get("FREQTRADE__API_SERVER__PASSWORD", "")

    SETTINGS_BOT_TOKEN = os.environ.get("SETTINGS_BOT_TOKEN", "")
    SETTINGS_BOT_CHAT_IDS = _split_ids(os.environ.get("SETTINGS_BOT_CHAT_IDS", ""))

    GOOGLE_SHEETS_CREDENTIALS_FILE = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", "")
    GOOGLE_SHEETS_SPREADSHEET_ID = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")

    TAX_LOG_POLL_SECONDS = int(os.environ.get("TAX_LOG_POLL_SECONDS", "300"))
    CAPITAL_POLL_SECONDS = int(os.environ.get("CAPITAL_POLL_SECONDS", "300"))
    WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8090"))
