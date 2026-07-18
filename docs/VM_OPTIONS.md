# VPS options for running the bot 24/7

**Minimum spec:** 1 vCPU, **2 GB RAM** (+2 GB swap — `scripts/setup-vps.sh`
creates it; Kraken trade-data conversion is RAM-hungry), 20 GB disk,
Ubuntu 22.04/24.04. freqtrade publishes multi-arch Docker images (x86 **and**
ARM), so every option below is compatible.

| # | Provider | Price (2026) | Typical spec | Verdict |
|---|----------|--------------|--------------|---------|
| 1 | **Oracle Cloud "Always Free"** | **$0/month** | ARM Ampere A1, up to 4 CPU / 24 GB RAM | Best value by far. Caveats: sign-up/capacity can be flaky, and idle free-tier VMs can be reclaimed — keep the bot running and consider upgrading to Pay-As-You-Go (still $0 within free limits) for reliability. |
| 2 | **RackNerd** | ~$11–20/**year** during promos | 1–2.5 GB RAM, x86 | Cheapest paid option. Buy during New-Year/Black-Friday promos; price locks on renewal. Unmanaged. |
| 3 | **Vultr** | $2.50–6/month | 1 vCPU / 1–2 GB | Many US datacenters (low latency to Kraken US infra), hourly billing — good for trying things out. |
| 4 | **Hetzner** (US: Ashburn VA, Hillsboro OR) | ~$4.60/month (CPX11) | 2 vCPU / 2 GB NVMe | Best performance per dollar, 20 TB traffic. Excellent reliability record. |
| 5 | **Contabo** | ~€4.50/month | 4 vCPU / 6 GB | Most RAM per dollar (nice headroom for backtesting). Disk I/O is slower than Hetzner/Vultr — fine for this bot. |

## Recommendation

- **Budget $0:** try Oracle Always Free first (pick the ARM A1 shape, 2 CPU/4 GB
  is plenty). If sign-up fails or capacity is unavailable, fall back to RackNerd.
- **Budget ~$5/mo and want it boring & reliable:** Hetzner CPX11 (US region) or
  Vultr.

## After purchase

```bash
ssh root@YOUR_VPS_IP
git clone <this repo> && cd kraken-freqtrade-dev
sudo bash scripts/setup-vps.sh     # Docker + 2G swap + firewall (SSH only)
cp .env.example .env && nano .env  # fill in tokens/passwords
bash scripts/start.sh              # deploy.mode "vps" is the default
```

Security defaults in `vps` mode: FreqUI/API bound to `127.0.0.1` only — open it
via an SSH tunnel (`ssh -L 8080:127.0.0.1:8080 user@vps`), firewall allows SSH
only, and the bot's Kraken API key should have **no withdrawal permission**.
