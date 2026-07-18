# kraken-freqtrade-dev

24/7 crypto auto-trading on **Kraken** (US-legal) built on the open-source
[freqtrade](https://github.com/freqtrade/freqtrade) bot — **freqtrade itself is
not modified**; everything custom lives in config files, `user_data/`, and a
companion service.

## What's inside

| Piece | What it does |
|---|---|
| `config/config.json` | freqtrade plumbing: Kraken spot, dry-run (paper trading), FreqUI, webhooks |
| `config/risk_settings.json` | **every tunable knob** — risk, capital, protections (single source of truth) |
| `user_data/strategies/KrakenSpotStrategy.py` | conservative 1h trend-pullback strategy |
| `companion/` | custom features (below), talks to freqtrade only via its REST API / webhooks / DB |
| `settings.json` + `scripts/start.sh` | one-command start; `deploy.mode: "vps"` or `"local"` toggle |
| `docs/GUIDE_KO.md` | **한국어 완전 가이드** (full Korean how-to) |
| `docs/SETUP_EN.md` | English setup guide |
| `docs/VM_OPTIONS.md` | 5 cheap VPS options compared |

### Companion features

- **💰 Capital management (bank & reset)** — when total balance reaches your
  `profit_target_usd`, the bot pauses, waits until flat, resets its trading
  capital to `restart_capital_usd`, and tells you (Telegram) to withdraw
  `set_aside_usd` manually. *The bot never withdraws funds itself.*
- **🧾 Tax log** — every closed trade becomes CoinLedger
  [Universal Manual Import](https://help.coinledger.io/en/articles/6028758-universal-manual-import-template-guide)
  rows, auto-appended to **Google Sheets** (paper and live trades kept in
  separate tabs) with a local CSV backup that never fails.
- **⚙️ Telegram settings bot** — a second Telegram bot with inline buttons to
  view/change stoploss, max open trades, capital targets, etc. Changes are
  bounds-checked, written atomically, applied live via `/reload_config`, and
  audit-logged.
- **📋 Failure back-log** — every bot event (and every cancelled/failed order)
  is stored in `companion_data/events.sqlite` for post-mortems, with instant
  Telegram alerts on failures.

## Quick start

```bash
cp .env.example .env        # fill in your values
# on a fresh VPS: sudo bash scripts/setup-vps.sh
bash scripts/start.sh       # reads settings.json (vps|local) and starts everything
bash scripts/status.sh
```

The bot starts in **dry-run (paper trading)** with a simulated $300 wallet and
live Kraken prices. FreqUI: `http://localhost:8080` (on a VPS, tunnel first:
`ssh -L 8080:127.0.0.1:8080 user@your-vps`).

## ⚠️ Read this before going live

1. **Small accounts fight fees.** Kraken charges ~0.25–0.40% per side at low
   volume. With $100–300, expect fees to consume a large share of gross profit.
2. **$300 → $10,000 is not a realistic short-term expectation.** The bank &
   reset feature works exactly as configured, but most retail strategies make
   (or lose) single-digit percent per month. Paper-trade 2–4 weeks minimum.
3. **Create your Kraken API key WITHOUT withdrawal permission.**
4. **Every trade is a US-taxable event** — that's what the tax log is for.
5. Backtesting against Kraken needs `--dl-trades` (only 720 candles via API).

## Development

```bash
pip install -r companion/requirements.txt pytest
python -m pytest tests/
```
