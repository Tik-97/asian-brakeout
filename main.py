from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict

from auth import CapitalSessionManager
from backtest import render_portfolio_summary, render_summary, run_backtests, run_portfolio_backtest
from capital_api import CapitalAPI
from config import load_config
from live_bot import AsianBreakoutBot
from performance_journal import export_performance_journal
from runtime_state import is_bot_enabled, set_bot_enabled
from telegram_bot import TelegramNotifier
from trade_history import compute_stats, format_stats_report, sync_closed_trades, sync_closed_trades_archive
from backtest import WEEKDAY_NAME_TO_INDEX


def build_runtime(env_file: str):
    config = load_config(env_file)
    session_manager = CapitalSessionManager(config.capital)
    api = CapitalAPI(session_manager)
    telegram = TelegramNotifier(config.telegram)
    telegram.ensure_menu_button()
    bot = AsianBreakoutBot(config, api, telegram)
    return config, api, telegram, bot


def run_live(env_file: str) -> None:
    _, _, _, bot = build_runtime(env_file)
    bot.run()


def run_sync(env_file: str) -> None:
    config, api, _, _ = build_runtime(env_file)
    recent = sync_closed_trades(api, config.strategy.symbols, last_period=86400)
    archive = sync_closed_trades_archive(api, config.strategy.symbols, days_back=7)
    print(f"Synced recent trades: {recent}")
    print(f"Synced archive trades: {archive}")


def run_stats(env_file: str) -> None:
    config, api, _, _ = build_runtime(env_file)
    sync_closed_trades(api, config.strategy.symbols, last_period=86400)
    sync_closed_trades_archive(api, config.strategy.symbols, days_back=7)
    stats = compute_stats()
    print(format_stats_report(stats))
    metrics_path = config.base_dir / "strategy_stats.json"
    metrics_path.write_text(json.dumps(asdict(stats), indent=2), encoding="utf-8")
    print(f"\nSaved stats JSON to {metrics_path}")


def parse_date_arg(raw_value: str | None) -> dt.date | None:
    if not raw_value:
        return None
    return dt.date.fromisoformat(raw_value)


def parse_weekday_list(raw_value: str | None) -> set[int] | None:
    if not raw_value:
        return None
    result: set[int] = set()
    for raw_part in raw_value.split(","):
        key = raw_part.strip().upper()
        if not key:
            continue
        if key not in WEEKDAY_NAME_TO_INDEX:
            raise ValueError(f"Unknown weekday: {raw_part}")
        result.add(WEEKDAY_NAME_TO_INDEX[key])
    return result or None


def run_backtest(
    env_file: str,
    symbols: list[str] | None = None,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    initial_equity: float = 10_000.0,
    target_margin: float | None = None,
    account_currency: str = "USD",
    currency_leverage: float | None = None,
    portfolio_margin_fraction: float | None = None,
    spread_multiplier: float = 0.0,
    slippage_multiplier: float = 0.0,
    entry_signal_cutoff_hour_utc: int | None = None,
    entry_signal_cutoff_weekdays_utc: set[int] | None = None,
    gbpjpy_h4_ema50_trend_filter: bool = False,
    usdjpy_sell_h4_ema50_trend_filter: bool = False,
    gbpjpy_breakout_buffer_atr_fraction: float = 0.0,
    gbpjpy_entry_signal_cutoff_hour_utc: int | None = None,
    max_signal_age_hours: float | None = None,
    vwap_direction_filter: bool = False,
    signal_relative_volume_threshold: float | None = None,
    signal_rsi_period: int = 0,
    signal_rsi_buy_max: float | None = None,
    signal_rsi_sell_min: float | None = None,
    breakout_close_buffer_atr_fraction: float = 0.0,
    partial_take_profit_fraction: float = 0.0,
    partial_take_profit_r_multiple: float = 1.0,
    gbpjpy_disable_sell: bool = False,
    disable_sell_symbols: list[str] | None = None,
    output_dir: str | None = None,
) -> None:
    config, api, _, _ = build_runtime(env_file)
    if output_dir:
        config.backtest.output_dir = config.base_dir / output_dir
    leverage_overrides = (
        {"CURRENCIES": currency_leverage}
        if currency_leverage is not None
        else None
    )
    resolved_signal_relative_volume_threshold = (
        config.strategy.signal_relative_volume_threshold
        if signal_relative_volume_threshold is None
        else signal_relative_volume_threshold
    )
    summaries = run_backtests(
        api,
        config,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_equity=initial_equity,
        target_margin_usd=target_margin,
        account_currency=account_currency,
        leverage_overrides=leverage_overrides,
        spread_multiplier=spread_multiplier,
        slippage_multiplier=slippage_multiplier,
        entry_signal_cutoff_hour_utc=entry_signal_cutoff_hour_utc,
        entry_signal_cutoff_weekdays_utc=entry_signal_cutoff_weekdays_utc,
        gbpjpy_h4_ema50_trend_filter=gbpjpy_h4_ema50_trend_filter,
        usdjpy_sell_h4_ema50_trend_filter=usdjpy_sell_h4_ema50_trend_filter,
        gbpjpy_breakout_buffer_atr_fraction=gbpjpy_breakout_buffer_atr_fraction,
        gbpjpy_entry_signal_cutoff_hour_utc=gbpjpy_entry_signal_cutoff_hour_utc,
        max_signal_age_hours=max_signal_age_hours,
        vwap_direction_filter=vwap_direction_filter,
        signal_relative_volume_threshold=resolved_signal_relative_volume_threshold,
        signal_rsi_period=signal_rsi_period,
        signal_rsi_buy_max=signal_rsi_buy_max,
        signal_rsi_sell_min=signal_rsi_sell_min,
        breakout_close_buffer_atr_fraction=breakout_close_buffer_atr_fraction,
        partial_take_profit_fraction=partial_take_profit_fraction,
        partial_take_profit_r_multiple=partial_take_profit_r_multiple,
        gbpjpy_disable_sell=gbpjpy_disable_sell,
        disable_sell_symbols=set(disable_sell_symbols or []),
    )
    for symbol, summary in summaries.items():
        print(render_summary(symbol, summary))
        print()

    selected_symbols = symbols or list(config.strategy.symbols.keys())
    if len(selected_symbols) > 1:
        portfolio_df, portfolio_summary = run_portfolio_backtest(
            api,
            config,
            symbols=selected_symbols,
            start_date=start_date,
            end_date=end_date,
            initial_equity=initial_equity,
            target_margin_usd=target_margin,
            account_currency=account_currency,
            leverage_overrides=leverage_overrides,
            portfolio_margin_fraction=portfolio_margin_fraction,
            spread_multiplier=spread_multiplier,
            slippage_multiplier=slippage_multiplier,
            entry_signal_cutoff_hour_utc=entry_signal_cutoff_hour_utc,
            entry_signal_cutoff_weekdays_utc=entry_signal_cutoff_weekdays_utc,
            gbpjpy_h4_ema50_trend_filter=gbpjpy_h4_ema50_trend_filter,
            usdjpy_sell_h4_ema50_trend_filter=usdjpy_sell_h4_ema50_trend_filter,
            gbpjpy_breakout_buffer_atr_fraction=gbpjpy_breakout_buffer_atr_fraction,
            gbpjpy_entry_signal_cutoff_hour_utc=gbpjpy_entry_signal_cutoff_hour_utc,
            max_signal_age_hours=max_signal_age_hours,
            vwap_direction_filter=vwap_direction_filter,
            signal_relative_volume_threshold=resolved_signal_relative_volume_threshold,
            signal_rsi_period=signal_rsi_period,
            signal_rsi_buy_max=signal_rsi_buy_max,
            signal_rsi_sell_min=signal_rsi_sell_min,
            breakout_close_buffer_atr_fraction=breakout_close_buffer_atr_fraction,
            partial_take_profit_fraction=partial_take_profit_fraction,
            partial_take_profit_r_multiple=partial_take_profit_r_multiple,
            gbpjpy_disable_sell=gbpjpy_disable_sell,
            disable_sell_symbols=set(disable_sell_symbols or []),
        )
        portfolio_dir = config.backtest.output_dir
        portfolio_csv = portfolio_dir / "portfolio_trades.csv"
        portfolio_metrics = portfolio_dir / "portfolio_metrics.json"
        portfolio_summary_path = portfolio_dir / "portfolio_summary.txt"
        portfolio_df.to_csv(portfolio_csv, index=False)
        portfolio_metrics.write_text(json.dumps(portfolio_summary, indent=2), encoding="utf-8")
        portfolio_summary_path.write_text(render_portfolio_summary(portfolio_summary) + "\n", encoding="utf-8")
        print(render_portfolio_summary(portfolio_summary))
        print()


def run_export_journal(env_file: str) -> None:
    config, api, _, _ = build_runtime(env_file)
    result = export_performance_journal(api, config)
    print(
        f"Exported {result['rows']} journal rows to "
        f"{result['json_path']} and {result['csv_path']}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Asian Breakout Capital.com backend bot")
    parser.add_argument("--env-file", default=".env", help="Path to .env file inside the Asian Breakout folder")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("live", help="Run the live backend bot loop")
    subparsers.add_parser("sync-history", help="Sync closed trades from Capital.com history")
    subparsers.add_parser("stats", help="Print current strategy stats from stored trade history")
    subparsers.add_parser("export-journal", help="Export performance journal JSON and CSV")
    subparsers.add_parser("enable", help="Enable live entries")
    subparsers.add_parser("disable", help="Disable live entries")
    subparsers.add_parser("status", help="Show whether live entries are enabled")

    backtest = subparsers.add_parser("backtest", help="Run historical backtest for the Asian Breakout strategy")
    backtest.add_argument("--symbols", nargs="*", help="Optional subset of symbols, for example EURUSD GBPUSD")
    backtest.add_argument("--from-date", help="Optional UTC start date in YYYY-MM-DD")
    backtest.add_argument("--to-date", help="Optional UTC end date in YYYY-MM-DD")
    backtest.add_argument("--initial-equity", type=float, default=10000.0, help="Initial account equity in account currency")
    backtest.add_argument("--target-margin", type=float, help="Per-trade margin budget in account currency")
    backtest.add_argument(
        "--portfolio-margin-fraction",
        type=float,
        help="Optional dynamic portfolio margin fraction per new trade, for example 0.25 for 25%% of balance",
    )
    backtest.add_argument(
        "--spread-multiplier",
        type=float,
        default=0.0,
        help="Multiply current live spread and charge that once per trade, for example 1.0",
    )
    backtest.add_argument(
        "--slippage-multiplier",
        type=float,
        default=0.0,
        help="Additional adverse slippage per side as a multiple of current live spread, for example 0.25",
    )
    backtest.add_argument("--account-currency", default="USD", help="Backtest account currency, default USD")
    backtest.add_argument("--currency-leverage", type=float, help="Override currency leverage for FX pairs")
    backtest.add_argument(
        "--entry-signal-cutoff-hour-utc",
        type=int,
        help="Optional exclusive UTC hour cutoff for new signal candles, for example 14 means ignore signals at 14:00 and later",
    )
    backtest.add_argument(
        "--entry-signal-cutoff-weekdays-utc",
        help="Optional comma-separated weekdays for the cutoff rule, for example Mon,Tue",
    )
    backtest.add_argument(
        "--gbpjpy-h4-ema50-trend-filter",
        action="store_true",
        help="Backtest-only filter: for GBPJPY require H4 close above EMA50 for BUY and below EMA50 for SELL",
    )
    backtest.add_argument(
        "--usdjpy-sell-h4-ema50-trend-filter",
        action="store_true",
        help="Backtest-only filter: for USDJPY SELL require H4 close below EMA50",
    )
    backtest.add_argument(
        "--gbpjpy-breakout-buffer-atr-fraction",
        type=float,
        default=0.0,
        help="Backtest-only filter: shift GBPJPY breakout entry by ATR fraction, for example 0.10 means 0.10 * ATR buffer",
    )
    backtest.add_argument(
        "--gbpjpy-entry-signal-cutoff-hour-utc",
        type=int,
        help="Backtest-only filter: for GBPJPY only, ignore new signal candles at this UTC hour and later",
    )
    backtest.add_argument(
        "--max-signal-age-hours",
        type=float,
        help="Backtest-only filter: cancel an unfilled order if it has waited longer than this many hours after the signal candle",
    )
    backtest.add_argument(
        "--vwap-direction-filter",
        action="store_true",
        help="Backtest-only filter: BUY only above intraday VWAP and SELL only below intraday VWAP",
    )
    backtest.add_argument(
        "--signal-relative-volume-threshold",
        type=float,
        default=None,
        help="Backtest-only filter: require signal candle volume divided by the average previous 20 H1 candle volume to be at least this threshold",
    )
    backtest.add_argument(
        "--signal-rsi-period",
        type=int,
        default=0,
        help="Backtest-only filter: compute RSI on H1 closes using this period; 0 disables the RSI filter",
    )
    backtest.add_argument(
        "--signal-rsi-buy-max",
        type=float,
        help="Backtest-only filter: for BUY signals require RSI to be at or below this level",
    )
    backtest.add_argument(
        "--signal-rsi-sell-min",
        type=float,
        help="Backtest-only filter: for SELL signals require RSI to be at or above this level",
    )
    backtest.add_argument(
        "--breakout-close-buffer-atr-fraction",
        type=float,
        default=0.0,
        help="Backtest-only filter: require the breakout candle close to finish beyond Asian High/Low by this ATR fraction",
    )
    backtest.add_argument(
        "--partial-take-profit-fraction",
        type=float,
        default=0.0,
        help="Backtest-only partial take profit fraction, for example 0.5 means close 50%% of the position early",
    )
    backtest.add_argument(
        "--partial-take-profit-r-multiple",
        type=float,
        default=1.0,
        help="Backtest-only early partial take profit trigger in R units, default 1.0",
    )
    backtest.add_argument(
        "--gbpjpy-disable-sell",
        action="store_true",
        help="Backtest-only filter: disable GBPJPY SELL trades entirely",
    )
    backtest.add_argument(
        "--disable-sell-symbols",
        nargs="*",
        help="Backtest-only filter: disable SELL trades for the listed symbols, for example USDJPY AUDJPY",
    )
    backtest.add_argument("--output-dir", help="Optional backtest output directory relative to project root")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.command == "live":
        run_live(args.env_file)
        return
    if args.command == "sync-history":
        run_sync(args.env_file)
        return
    if args.command == "stats":
        run_stats(args.env_file)
        return
    if args.command == "backtest":
        portfolio_margin_fraction = None
        if args.portfolio_margin_fraction is not None:
            portfolio_margin_fraction = float(args.portfolio_margin_fraction)
            if portfolio_margin_fraction > 1:
                portfolio_margin_fraction = portfolio_margin_fraction / 100.0
            if not 0 < portfolio_margin_fraction <= 1:
                raise ValueError("--portfolio-margin-fraction must be between 0 and 1, or between 0 and 100 as a percent")
        elif args.target_margin is None:
            config = load_config(args.env_file)
            portfolio_margin_fraction = float(config.strategy.portfolio_margin_fraction)
        run_backtest(
            args.env_file,
            symbols=args.symbols,
            start_date=parse_date_arg(args.from_date),
            end_date=parse_date_arg(args.to_date),
            initial_equity=args.initial_equity,
            target_margin=args.target_margin,
            account_currency=args.account_currency,
            currency_leverage=args.currency_leverage,
            portfolio_margin_fraction=portfolio_margin_fraction,
            spread_multiplier=args.spread_multiplier,
            slippage_multiplier=args.slippage_multiplier,
            entry_signal_cutoff_hour_utc=args.entry_signal_cutoff_hour_utc,
            entry_signal_cutoff_weekdays_utc=parse_weekday_list(args.entry_signal_cutoff_weekdays_utc),
            gbpjpy_h4_ema50_trend_filter=args.gbpjpy_h4_ema50_trend_filter,
            usdjpy_sell_h4_ema50_trend_filter=args.usdjpy_sell_h4_ema50_trend_filter,
            gbpjpy_breakout_buffer_atr_fraction=args.gbpjpy_breakout_buffer_atr_fraction,
            gbpjpy_entry_signal_cutoff_hour_utc=args.gbpjpy_entry_signal_cutoff_hour_utc,
            max_signal_age_hours=args.max_signal_age_hours,
            vwap_direction_filter=args.vwap_direction_filter,
            signal_relative_volume_threshold=args.signal_relative_volume_threshold,
            signal_rsi_period=args.signal_rsi_period,
            signal_rsi_buy_max=args.signal_rsi_buy_max,
            signal_rsi_sell_min=args.signal_rsi_sell_min,
            breakout_close_buffer_atr_fraction=args.breakout_close_buffer_atr_fraction,
            partial_take_profit_fraction=args.partial_take_profit_fraction,
            partial_take_profit_r_multiple=args.partial_take_profit_r_multiple,
            gbpjpy_disable_sell=args.gbpjpy_disable_sell,
            disable_sell_symbols=args.disable_sell_symbols,
            output_dir=args.output_dir,
        )
        return
    if args.command == "export-journal":
        run_export_journal(args.env_file)
        return
    if args.command == "enable":
        print(f"Bot enabled: {set_bot_enabled(True)}")
        return
    if args.command == "disable":
        print(f"Bot enabled: {set_bot_enabled(False)}")
        return
    if args.command == "status":
        print(f"Bot enabled: {is_bot_enabled()}")
        return


if __name__ == "__main__":
    main()
