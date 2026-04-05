# Dashboard

Separate local UI for the Asian Breakout project.

## Important

This app does not import or modify the trading bot logic. It only reads exported files copied into `public/data/`.

## Run

```bash
cd dashboard
npm install
npm run dev
```

## Stable Local Run

If `next dev` starts showing chunk, stylesheet, or hydration-related runtime glitches, use the stable local run instead:

```bash
cd dashboard
npm run build
npm run start
```

This uses the production server locally and is much more reliable for viewing the dashboard on `http://localhost:3000`.

## Recommended Workflow

- Use `npm run dev` only while actively editing UI.
- Use `npm run build && npm run start` when you want a stable local preview.
- If the dev server gets stuck, stop it and delete `dashboard/.next/` before starting again.

## Refresh Data

Copy the latest normal-strategy exports into `dashboard/public/data/`:

- `yearly_backtest_2025_2026_GBPJPY_EURJPY_summary.json`
- `yearly_backtest_2025_2026_GBPJPY_EURJPY_real_traded.csv`
- `yearly_backtest_2025_2026_GBPJPY_EURJPY_real_wins.csv`
- `yearly_backtest_2025_2026_GBPJPY_EURJPY_real_losses.csv`
- `yearly_backtest_2025_2026_GBPJPY_EURJPY_events.csv`
- `yearly_backtest_2025_2026_GBPJPY_EURJPY_withdrawals.csv`

## Live Fresh Start

For a clean live-account reset, the dashboard bridge now supports:

- `AB_DASHBOARD_INITIAL_DEPOSIT_USD`
- `AB_DASHBOARD_RESET_AT_UTC`

Manual withdrawals can be recorded in:

- [manual_withdrawals.json](C:/Users/Tigran/Desktop/Asian%20Brakeout/dashboard/manual_withdrawals.json)

Use an array like:

```json
[
  {
    "time_utc": "2026-05-01T10:00:00Z",
    "withdrawal_kind": "manual_2x_recovery",
    "withdrawal_amount": 400
  }
]
```

## Telegram Mini App From Your Computer

If you want Telegram to open the dashboard directly from your own computer, use the helper in the repo root:

```bash
python host_telegram_miniapp.py
```

It will:

- reuse or start the local dashboard on `http://127.0.0.1:3000`
- open a secure Cloudflare quick tunnel
- update the Telegram Mini App button to the public tunnel URL

Keep that helper process running while you want the Mini App link to stay alive.
