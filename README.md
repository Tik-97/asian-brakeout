# Asian Breakout Backend Bot

Backend-only Capital.com DEMO bot for the Asian breakout strategy.

## Setup

1. Install dependencies:
   `pip install -r requirements.txt`
2. Copy `.env.example` to `.env`
3. Fill in your Capital.com and Telegram credentials

## Main commands

- Live bot:
  `python main.py live`
- Sync closed trades from broker history:
  `python main.py sync-history`
- Print current stored strategy stats:
  `python main.py stats`
- Run backtest and save reports into `backtests/`:
  `python main.py backtest`
- Run backtest for selected symbols only:
  `python main.py backtest --symbols EURUSD GBPUSD`
- Export performance journal:
  `python main.py export-journal`
- Disable live entries without stopping the process:
  `python main.py disable`
- Re-enable live entries:
  `python main.py enable`
- Check entry status:
  `python main.py status`

## Recommended routine

- Before starting live:
  `python main.py sync-history`
- Check current stats:
  `python main.py stats`
- Run a fresh backtest when you change settings:
  `python main.py backtest`

## Backtest outputs

For each symbol the bot writes:

- `{symbol}_trades.csv`
- `{symbol}_metrics.json`
- `{symbol}_summary.txt`

The backtest is based on Capital.com H1 broker history and uses the live strategy rules:

- Asian range from `00:00-08:00 UTC`
- breakout confirmation from closed H1 candles
- ATR filter
- entry at Asian high/low
- TP/SL from ATR
- forced time exit at `08:59 UTC` next day
- H1 backtest history is capped to the latest `1000` broker candles per symbol

## Notes

- Telegram remains supported and can show a Mini App dashboard button when `AB_TELEGRAM_MINI_APP_URL` is set.
- For live hosting directly from your computer through Cloudflare Tunnel, run:
  `python host_telegram_miniapp.py`
  This reuses or starts the local dashboard, opens a Cloudflare quick tunnel, and updates the Telegram Mini App menu button to the public tunnel URL.
- For the permanent `dead-market.com` live setup from your computer, use:
  - [Start Dead Market.cmd](/C:/Users/Tigran/Desktop/Asian%20Brakeout/Start%20Dead%20Market.cmd)
  - [Stop Dead Market.cmd](/C:/Users/Tigran/Desktop/Asian%20Brakeout/Stop%20Dead%20Market.cmd)
  - full guide: [LIVE_LOCAL_SETUP.md](/C:/Users/Tigran/Desktop/Asian%20Brakeout/LIVE_LOCAL_SETUP.md)
- FastAPI/frontend code was removed from this folder.
- Stats are built from the local trade journal in `state.json`.
