#!/usr/bin/env bash
# One-time VPS preparation for Ubuntu 22.04/24.04.
# Installs Docker, creates a 2G swap file, enables a basic firewall.
# Run as root (or with sudo):  sudo bash scripts/setup-vps.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo bash scripts/setup-vps.sh"
    exit 1
fi

echo "== Installing Docker =="
if ! command -v docker >/dev/null 2>&1; then
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
    echo "Docker already installed."
fi

echo "== Creating 2G swap (Kraken data conversion is RAM-heavy) =="
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
    echo "Swap file already exists."
fi

echo "== Firewall: allow SSH only (FreqUI stays on 127.0.0.1, use an SSH tunnel) =="
apt-get install -y ufw
ufw allow OpenSSH
ufw --force enable

echo
echo "Done. Next steps:"
echo "  1. cp .env.example .env   and fill in your values"
echo "  2. bash scripts/start.sh"
