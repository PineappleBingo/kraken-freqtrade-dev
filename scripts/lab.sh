#!/usr/bin/env bash
# Backtest lab: download data, backtest, tune attributes, compare strategies.
#
#   bash scripts/lab.sh download   [--days 180] [--pairs "BTC/USD ETH/USD"]
#   bash scripts/lab.sh backtest   <Strategy> [--timerange 20260101-] [--fee 0.0026] [extra freqtrade args]
#   bash scripts/lab.sh hyperopt   <Strategy> [--epochs 60] [--spaces "buy sell"]
#   bash scripts/lab.sh webui      # FreqUI interactive backtesting on :8081
#   bash scripts/lab.sh compare    <StratA> <StratB> [...] [--pairs "BTC/USD"] [--timerange 20260101-] [--fee 0.004]
#
# All heavy lifting is freqtrade's own engine; `compare` additionally renders
# an interactive HTML report at companion_data/lab_reports/latest.html.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIGS=(--config /freqtrade/config/config.json
         --config /freqtrade/config/risk_settings.json
         --config /freqtrade/config/backtest.json)
FT=(docker compose run --rm freqtrade)

usage() { grep '^#   ' "$0" | sed 's/^#   //'; exit 1; }

cmd=${1:-}; [ -n "$cmd" ] || usage; shift

case "$cmd" in
  download)
    DAYS=180; PAIRS=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --days)  DAYS=$2; shift 2 ;;
        --pairs) PAIRS=$2; shift 2 ;;
        *) echo "unknown option: $1"; usage ;;
      esac
    done
    # shellcheck disable=SC2086
    "${FT[@]}" download-data "${CONFIGS[@]}" --dl-trades \
        --timeframes 15m 1h --days "$DAYS" ${PAIRS:+-p $PAIRS}
    ;;

  backtest)
    STRAT=${1:-}; [ -n "$STRAT" ] || usage; shift
    "${FT[@]}" backtesting "${CONFIGS[@]}" --strategy "$STRAT" \
        --breakdown month --export trades "$@"
    ;;

  hyperopt)
    STRAT=${1:-}; [ -n "$STRAT" ] || usage; shift
    EPOCHS=60; SPACES="buy sell"; EXTRA=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --epochs) EPOCHS=$2; shift 2 ;;
        --spaces) SPACES=$2; shift 2 ;;
        *) EXTRA+=("$1"); shift ;;
      esac
    done
    # shellcheck disable=SC2086
    "${FT[@]}" hyperopt "${CONFIGS[@]}" --strategy "$STRAT" \
        --hyperopt-loss SharpeHyperOptLoss --epochs "$EPOCHS" \
        --spaces $SPACES ${EXTRA[@]+"${EXTRA[@]}"}
    ;;

  webui)
    MODE=$(python3 -c "import json; print(json.load(open('settings.json'))['deploy']['mode'])")
    if [ "$MODE" = "local" ]; then export BIND_ADDR="0.0.0.0"; else export BIND_ADDR="127.0.0.1"; fi
    docker compose --profile lab up -d freqtrade-lab
    echo "FreqUI backtesting webserver started on port 8081."
    if [ "$MODE" = "vps" ]; then
      echo "Open a tunnel:  ssh -L 8081:127.0.0.1:8081 user@your-vps"
      echo "then browse:    http://localhost:8081  (menu: Backtest)"
    else
      echo "Browse: http://<this-machine>:8081  (menu: Backtest)"
    fi
    echo "Stop with: docker compose --profile lab stop freqtrade-lab"
    ;;

  compare)
    STRATS=()
    while [ $# -gt 0 ] && [[ "$1" != --* ]]; do STRATS+=("$1"); shift; done
    [ "${#STRATS[@]}" -ge 2 ] || { echo "compare needs at least 2 strategies"; usage; }
    PAIRS=""; EXTRA=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --pairs) PAIRS=$2; shift 2 ;;
        *) EXTRA+=("$1"); shift ;;
      esac
    done
    RUN_ID=$(date +%Y%m%d_%H%M%S)
    RUN_DIR="user_data/backtest_results/lab/$RUN_ID"
    mkdir -p "$RUN_DIR" companion_data/lab_reports
    for STRAT in "${STRATS[@]}"; do
      echo "── Backtesting $STRAT ─────────────────────────────────────────"
      # shellcheck disable=SC2086
      "${FT[@]}" backtesting "${CONFIGS[@]}" --strategy "$STRAT" \
          --export trades \
          --export-filename "/freqtrade/$RUN_DIR/$STRAT.json" \
          ${PAIRS:+-p $PAIRS} ${EXTRA[@]+"${EXTRA[@]}"}
    done
    echo "── Rendering comparison report ─────────────────────────────────"
    docker compose run --rm --no-deps companion \
        python -m companion.backtest_lab.cli \
        "/app/$RUN_DIR" -o /app/data/lab_reports
    echo
    echo "Report: companion_data/lab_reports/latest.html"
    echo "  - local mode : open the file directly, or http://<machine>:8090/lab/latest.html"
    echo "  - vps mode   : ssh -L 8090:127.0.0.1:8090 user@vps  ->  http://localhost:8090/lab/latest.html"
    ;;

  *) usage ;;
esac
