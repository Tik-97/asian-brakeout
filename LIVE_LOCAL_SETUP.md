# Dead Market Live Startup

This project can run fully from your own computer:

- live trading bot
- live dashboard data bridge
- production dashboard frontend
- Cloudflare Tunnel on `https://app.dead-market.com`

## One-click start

Double-click:

- [Start Dead Market.cmd](Start%20Dead%20Market.cmd)

That starts:

- the production dashboard on `127.0.0.1:3000`
- the live dashboard bridge
- the trading bot
- the named Cloudflare Tunnel

## One-click stop

Double-click:

- [Stop Dead Market.cmd](Stop%20Dead%20Market.cmd)

## Public and local addresses

- Local: `http://127.0.0.1:3000`
- Public: `https://app.dead-market.com`

## After a computer restart

1. Make sure internet is connected.
2. Double-click [Start Dead Market.cmd](Start%20Dead%20Market.cmd).
3. Wait about `10-30` seconds.
4. Open `https://app.dead-market.com` or Telegram Mini App.

## If you changed the frontend code

Run this once from PowerShell in the project root:

```powershell
.\scripts\start_dead_market_stack.ps1 -RebuildDashboard
```

That rebuilds the production frontend before starting everything.

## Logs

Runtime logs are saved in:

- `runtime/logs/dashboard.out.log`
- `runtime/logs/dashboard.err.log`
- `runtime/logs/bridge.out.log`
- `runtime/logs/bridge.err.log`
- `runtime/logs/bot.out.log`
- `runtime/logs/bot.err.log`
- `runtime/logs/cloudflared.out.log`
- `runtime/logs/cloudflared.err.log`

## Important notes

- If the computer is off, the site and bot are off.
- If Cloudflare Tunnel is stopped, `app.dead-market.com` will stop opening.
- Telegram Mini App points to `https://app.dead-market.com`.
- Email protection is configured in Cloudflare Access, not in the local scripts.

## If something does not open

1. Double-click [Stop Dead Market.cmd](Stop%20Dead%20Market.cmd)
2. Wait `3-5` seconds
3. Double-click [Start Dead Market.cmd](Start%20Dead%20Market.cmd)
4. If needed, read the logs in `runtime/logs`
