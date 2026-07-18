"""Companion service for the Kraken freqtrade bot.

Adds (without touching freqtrade itself):
  - capital management: profit-target -> pause -> bank -> reset -> resume
  - tax logging: closed trades -> CoinLedger rows -> Google Sheets (+ CSV backup)
  - Telegram settings bot: edit risk/capital settings with inline buttons
  - failure back-log: webhook events + errors stored for later review
"""
