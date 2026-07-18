#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose ps
echo
if curl -fsS -m 5 http://127.0.0.1:8080/api/v1/ping >/dev/null 2>&1; then
    echo "freqtrade API: OK (http://127.0.0.1:8080)"
else
    echo "freqtrade API: NOT RESPONDING"
fi
echo
echo "Recent freqtrade log:"
docker compose logs --tail 15 freqtrade
