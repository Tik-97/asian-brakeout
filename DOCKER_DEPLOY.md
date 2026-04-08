# Docker Deploy On Ubuntu

This stack runs three containers:

- `bot`: live trading bot
- `bridge`: writes fresh live dashboard JSON from broker/state data
- `dashboard`: Next.js website

All runtime data is persisted in the local `runtime/` folder, so migrating to another server is simple:

- copy the repo
- copy `.env`
- copy `runtime/`
- run `docker compose up -d --build`

## Before You Start

Make sure the Ubuntu server already has:

- Docker Engine
- Docker Compose plugin
- your repo files on the server
- a valid `.env`

Docker official install docs:

- https://docs.docker.com/engine/install/ubuntu/
- https://docs.docker.com/compose/install/linux/

## First Deploy

From the project root on the server:

```bash
mkdir -p runtime/dashboard
docker compose up -d --build
```

Then check:

```bash
docker compose ps
docker compose logs -f bot
docker compose logs -f bridge
docker compose logs -f dashboard
```

Website address:

```bash
http://SERVER_IP:3000
```

If you want another public port:

```bash
DASHBOARD_PORT=8080 docker compose up -d
```

Or place `DASHBOARD_PORT=8080` into your server environment before launch.

## What Persists

These files move into `runtime/` inside Docker:

- `state.json`
- `runtime_state.json`
- `order_audit.jsonl`
- `performance_journal.json`
- `performance_journal.csv`
- `runtime/backtests/`
- `runtime/dashboard/live_dashboard.json`
- `runtime/dashboard/manual_withdrawals.json`

That means container rebuilds do not wipe your bot state.

## Update On Server

When you change code:

```bash
git pull
docker compose up -d --build
```

If only the Python code changed, this is still fine.

## Stop / Start

```bash
docker compose stop
docker compose start
```

Full shutdown:

```bash
docker compose down
```

Shutdown without deleting runtime data is safe because persistence is in the bind-mounted `runtime/` folder.

## Backup Before Migration

From the project root:

```bash
tar czf asian-breakout-backup.tar.gz .env runtime
```

On the new server:

```bash
tar xzf asian-breakout-backup.tar.gz
docker compose up -d --build
```

## Notes

- This compose file does not include Cloudflare Tunnel yet.
- If you want a domain later, add Nginx, Caddy, or Cloudflare Tunnel in front of the `dashboard` container.
- If your Telegram Mini App should point to the server, update `AB_TELEGRAM_MINI_APP_URL` in `.env`.

## Optional: Cloudflare Tunnel On Ubuntu

If `app.dead-market.com` is already mapped to a named tunnel, move the tunnel to the server:

1. Copy the credentials JSON from your Windows machine to the server:

```powershell
scp -P 23019 $HOME\.cloudflared\2e986217-27c7-443c-8b25-e5fcbdde9a86.json root@178.160.194.52:/root/.cloudflared/
```

2. On the server, install and configure `cloudflared`:

```bash
cd /opt/asian-breakout
chmod +x scripts/server_install_cloudflared_ubuntu.sh scripts/server_setup_cloudflared.sh
./scripts/server_install_cloudflared_ubuntu.sh
mkdir -p /root/.cloudflared
./scripts/server_setup_cloudflared.sh
```

3. Check the service:

```bash
systemctl status cloudflared
journalctl -u cloudflared -f
```

The Linux tunnel config template is:

`cloudflare/dead-market-tunnel.linux.yml`
