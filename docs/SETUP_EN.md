# Setup guide (English)

The Korean version of this guide (docs/GUIDE_KO.md) is the primary,
fully-detailed one — this is a condensed English mirror.

## 0. What you need

- A VPS (see `VM_OPTIONS.md`) or any always-on machine with Docker
- A Kraken account (US-supported), verified
- Two Telegram bots from [@BotFather](https://t.me/BotFather):
  - **Bot 1** — freqtrade's trade notifications & built-in commands
  - **Bot 2** — the companion settings bot (inline-button config editor)
  - Get your numeric chat id from [@userinfobot](https://t.me/userinfobot)
- (Recommended) A Google account for the tax-log spreadsheet

## 1. Server prep (VPS)

```bash
ssh root@YOUR_VPS_IP
apt-get update && apt-get install -y git
git clone https://github.com/PineappleBingo/kraken-freqtrade-dev.git
cd kraken-freqtrade-dev
sudo bash scripts/setup-vps.sh   # Docker + 2G swap + firewall (SSH only)
```

Running at home instead? Install Docker Desktop / docker engine, set
`"deploy": {"mode": "local"}` in `settings.json`, and skip `setup-vps.sh`.

## 2. Configure

```bash
cp .env.example .env
nano .env
```

Fill in:
- `FREQTRADE__API_SERVER__PASSWORD` / `JWT_SECRET_KEY` / `WS_TOKEN` — strong random strings
- `FREQTRADE__TELEGRAM__ENABLED=true`, token + chat id for **Bot 1**
- `SETTINGS_BOT_TOKEN` + `SETTINGS_BOT_CHAT_IDS` for **Bot 2**
- Leave `FREQTRADE__EXCHANGE__KEY/SECRET` **empty** for paper trading

### Google Sheets tax log (optional, ~10 min, free)

1. [console.cloud.google.com](https://console.cloud.google.com) → new project →
   enable **Google Sheets API** and **Google Drive API**.
2. IAM & Admin → Service Accounts → create one → Keys → **Add key (JSON)** →
   download → save as `config/google-service-account.json` (git-ignored).
3. Create a Google Sheet, share it with the service account's
   `...@...iam.gserviceaccount.com` email as **Editor**.
4. Put the sheet's ID (the long string in its URL) into
   `GOOGLE_SHEETS_SPREADSHEET_ID` in `.env`.

Paper trades land in a `PaperTrades` tab, live trades in `Transactions`
(CoinLedger Universal Manual Import format — importable at tax time). A local
CSV backup is always written to `companion_data/` regardless.

## 3. Start (paper trading)

```bash
bash scripts/start.sh
bash scripts/status.sh
docker compose logs -f freqtrade   # watch it work
```

- FreqUI dashboard: `ssh -L 8080:127.0.0.1:8080 user@vps` → http://localhost:8080
- Telegram Bot 1: `/status`, `/profit`, `/daily`, `/balance`
- Telegram Bot 2: `/start` → inline settings menu (Risk / Capital / Bot control
  / Failures / Tax log)

**Run paper trading for at least 2–4 weeks** and check: win rate, drawdown,
whether profits exceed the ~0.5–0.8% round-trip fees.

## 4. Going live (deliberate, manual step)

1. Kraken → Settings → API → create key with **Query Funds, Create & Modify
   Orders, Cancel Orders** only — **never Withdraw**.
2. In `.env`: set `FREQTRADE__EXCHANGE__KEY` / `SECRET`.
3. In `config/config.json`: set `"dry_run": false` and change `db_url` to
   `sqlite:////freqtrade/user_data/tradesv3.live.sqlite` (keeps live trades in
   a separate DB so your tax log stays clean).
4. In `config/risk_settings.json`: set `available_capital` to what you actually
   deposited (e.g. 300).
5. `bash scripts/start.sh` (compose restarts pick up `.env`).

## 5. Capital management (bank & reset)

All in `config/risk_settings.json → companion.capital_management`, editable
from the settings bot's 💰 Capital menu:

| Key | Meaning |
|---|---|
| `profit_target_usd` | total balance that triggers banking (e.g. 10000) |
| `set_aside_usd` | amount you'll withdraw manually (e.g. 9000) |
| `restart_capital_usd` | capital the bot restarts with (e.g. 1000) |
| `force_exit_open_trades` | close open positions immediately at target |

Cycle: target hit → entries paused → wait until flat → `available_capital`
reset + bot resumed → Telegram tells you to withdraw the set-aside → after the
withdrawal is detected, the cycle re-arms.

## 6. Backtest lab (strategy testing & comparison)

Everything runs through `scripts/lab.sh` (freqtrade's own engine under the
hood; Kraken worst-case taker fee 0.4% is applied by default via
`config/backtest.json`):

```bash
# 1) download history once (Kraken only serves 720 candles via API,
#    so this uses trade-data download — slow and RAM-heavy, be patient)
bash scripts/lab.sh download --days 180

# 2) single backtest with monthly breakdown
bash scripts/lab.sh backtest E0V1EKraken --timerange 20260101-

# 3) auto-tune a strategy's entry/exit attributes (hyperopt)
bash scripts/lab.sh hyperopt E0V1EKraken --epochs 60

# 4) interactive backtesting in the browser (FreqUI "Backtest" page):
#    change strategy/timerange, re-run, inspect trades on the chart
bash scripts/lab.sh webui        # port 8081, same SSH-tunnel pattern

# 5) compare strategies on IDENTICAL data -> interactive visual report
bash scripts/lab.sh compare KrakenSpotStrategy E0V1EKraken --pairs "BTC/USD" --timerange 20260101-
```

The compare report (equity curves, drawdown, monthly returns, trade scatter,
winner-highlighted metrics) lands at `companion_data/lab_reports/latest.html`
and is served at `http://localhost:8090/lab/latest.html`
(vps mode: `ssh -L 8090:127.0.0.1:8090 user@vps` first).

Notes:
- `NostalgiaForInfinityX6` is vendored for comparisons; it's a 70k-line
  community strategy tuned for Binance-scale pairlists — treat its results
  as reference only, and expect it to need `pandas_ta` (bundled in the
  freqtrade docker image).
- Strategies with different timeframes are compared fairly: `compare` runs
  each one separately on the same pairs/timerange/fee and merges the exports.

## 7. Day-2 operations

- **Change risk settings**: settings bot → 🛡 Risk (audit-logged, applied live)
- **Review failures**: settings bot → 📋 Failures, or
  `companion_data/events.sqlite`
- **Update the stack**: `git pull && bash scripts/start.sh`
- **Logs**: `docker compose logs -f freqtrade` / `docker compose logs -f companion`
