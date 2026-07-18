#!/usr/bin/env bash
# Start the bot stack. Deployment mode comes from settings.json (vps|local).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill it in first."
    exit 1
fi

MODE=$(python3 -c "import json; print(json.load(open('settings.json'))['deploy']['mode'])")

case "$MODE" in
    vps)
        export BIND_ADDR="127.0.0.1"
        export RESTART_POLICY="unless-stopped"
        echo "Mode: vps  (FreqUI bound to 127.0.0.1 — reach it via SSH tunnel:"
        echo "  ssh -L 8080:127.0.0.1:8080 user@your-vps   then open http://localhost:8080)"
        ;;
    local)
        export BIND_ADDR="0.0.0.0"
        export RESTART_POLICY="unless-stopped"
        echo "Mode: local  (FreqUI reachable on your LAN at http://<this-machine>:8080)"
        ;;
    *)
        echo "ERROR: settings.json deploy.mode must be 'vps' or 'local' (got: $MODE)"
        exit 1
        ;;
esac

mkdir -p companion_data user_data
docker compose up -d --build
echo
docker compose ps
echo
echo "Started. Check logs with: docker compose logs -f freqtrade"
