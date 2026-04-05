from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from capital_api import CapitalAPI
from config import AppConfig
from data_utils import get_asian_range, parse_candles, parse_candles_bid_ask
from market_hours import close_deadline_for_trade_day, overnight_funding_charge_times
from regime_guard import RegimeGuardTracker, regime_guard_settings_from_strategy
from session_utils import current_session_date
from sizing_live import (
    choose_size_for_target_margin_live,
    extract_market_rules,
    resolve_margin_context_live,
    size_for_target_margin,
)
from strategy import StrategyParameters, atr_filter, calculate_levels


WEEKDAY_NAME_TO_INDEX = {
    "MON": 0,
    "MONDAY": 0,
    "TUE": 1,
    "TUESDAY": 1,
    "WED": 2,
    "WEDNESDAY": 2,
    "THU": 3,
    "THURSDAY": 3,
    "FRI": 4,
    "FRIDAY": 4,
    "SAT": 5,
    "SATURDAY": 5,
    "SUN": 6,
    "SUNDAY": 6,
}


@dataclass(slots=True)
class BacktestTrade:
    symbol: str
    session_date: str
    side: str
    order_type: str
    signal_time_utc: str
    fill_time_utc: str
    exit_time_utc: str
    entry: float
    stop_loss: float
    take_profit: float
    exit_price: float
    exit_reason: str
    size: float | None
    estimated_margin: float | None
    estimated_margin_usd: float | None
    account_currency: str
    pnl_points: float
    pnl_quote_currency: float | None
    pnl_account_currency: float | None
    pnl_usd: float | None
    r_multiple: float
    holding_hours: float
    equity_before: float
    equity_after: float
    equity_before_usd: float | None
    equity_after_usd: float | None
    margin_per_unit_account: float | None = None
    pnl_account_per_unit: float | None = None
    overnight_funding_account: float | None = None
    overnight_funding_events: int | None = None
    min_size: float | None = None
    size_step: float | None = None
    spread_points: float | None = None
    slippage_points_per_side: float | None = None
    total_friction_points: float | None = None


def choose_working_order_type(direction: str, entry_price: float, current_price: float) -> str:
    if direction == "BUY":
        return "STOP" if current_price < entry_price else "LIMIT"
    return "STOP" if current_price > entry_price else "LIMIT"


def build_h4_ema50_trend_frame(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    frame = history[["time", "close"]].copy()
    frame = frame.dropna(subset=["time", "close"]).sort_values("time")
    if frame.empty:
        return pd.DataFrame()
    h4 = (
        frame.set_index("time")
        .resample("4h", label="right", closed="right")
        .agg({"close": "last"})
        .dropna()
        .reset_index()
    )
    if h4.empty:
        return pd.DataFrame()
    h4["ema50"] = h4["close"].ewm(span=50, adjust=False).mean()
    return h4


def build_intraday_vwap_frame(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty or "volume" not in history.columns:
        return pd.DataFrame()
    frame = history[["time", "high", "low", "close", "volume"]].copy()
    frame = frame.dropna(subset=["time", "high", "low", "close", "volume"]).sort_values("time")
    if frame.empty:
        return pd.DataFrame()
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame[frame["volume"] > 0].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["trade_date"] = frame["time"].dt.date
    frame["typical_price"] = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    frame["tpv"] = frame["typical_price"] * frame["volume"]
    frame["cum_tpv"] = frame.groupby("trade_date")["tpv"].cumsum()
    frame["cum_volume"] = frame.groupby("trade_date")["volume"].cumsum()
    frame["vwap"] = frame["cum_tpv"] / frame["cum_volume"]
    return frame[["time", "vwap"]].copy()


def build_relative_signal_volume_frame(history: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    if history.empty or "volume" not in history.columns:
        return pd.DataFrame()
    frame = history[["time", "volume"]].copy()
    frame = frame.dropna(subset=["time", "volume"]).sort_values("time")
    if frame.empty:
        return pd.DataFrame()
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame[frame["volume"] > 0].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["avg_prev_volume"] = frame["volume"].shift(1).rolling(lookback, min_periods=lookback).mean()
    frame["rel_volume"] = frame["volume"] / frame["avg_prev_volume"]
    return frame[["time", "rel_volume"]].copy()


def passes_intraday_vwap_filter(
    *,
    direction: str,
    signal_time: dt.datetime,
    signal_close_price: float,
    intraday_vwap: pd.DataFrame,
) -> bool:
    if intraday_vwap.empty:
        return False
    subset = intraday_vwap[intraday_vwap["time"] <= pd.Timestamp(signal_time)]
    if subset.empty:
        return False
    vwap_value = float(subset.iloc[-1]["vwap"])
    if direction == "BUY":
        return signal_close_price > vwap_value
    return signal_close_price < vwap_value


def passes_relative_signal_volume_filter(
    *,
    signal_time: dt.datetime,
    min_relative_volume: float,
    relative_volume_frame: pd.DataFrame,
) -> bool:
    if min_relative_volume <= 0:
        return True
    if relative_volume_frame.empty:
        return False
    subset = relative_volume_frame[relative_volume_frame["time"] == pd.Timestamp(signal_time)]
    if subset.empty:
        return False
    rel_volume = subset.iloc[-1]["rel_volume"]
    if pd.isna(rel_volume):
        return False
    return float(rel_volume) >= min_relative_volume


def passes_gbpjpy_h4_ema50_filter(
    *,
    symbol: str,
    direction: str,
    signal_time: dt.datetime,
    h4_trend: pd.DataFrame,
) -> bool:
    if symbol.upper() != "GBPJPY":
        return True
    if h4_trend.empty:
        return False
    subset = h4_trend[h4_trend["time"] <= pd.Timestamp(signal_time)]
    if subset.empty:
        return False
    row = subset.iloc[-1]
    close_value = float(row["close"])
    ema50_value = float(row["ema50"])
    if direction == "BUY":
        return close_value > ema50_value
    return close_value < ema50_value


def gbpjpy_buffered_entry(
    *,
    symbol: str,
    direction: str,
    asian_high: float,
    asian_low: float,
    atr_value: float | None,
    gbpjpy_breakout_buffer_atr_fraction: float,
) -> float:
    if symbol.upper() != "GBPJPY" or gbpjpy_breakout_buffer_atr_fraction <= 0 or atr_value is None:
        return asian_high if direction == "BUY" else asian_low
    buffer_points = atr_value * gbpjpy_breakout_buffer_atr_fraction
    if direction == "BUY":
        return asian_high + buffer_points
    return asian_low - buffer_points


def passes_breakout_close_confirmation(
    *,
    direction: str,
    close_price: float,
    asian_high: float,
    asian_low: float,
    atr_value: float | None,
    breakout_close_buffer_atr_fraction: float,
) -> bool:
    if breakout_close_buffer_atr_fraction <= 0 or atr_value is None:
        return True
    close_buffer = atr_value * breakout_close_buffer_atr_fraction
    if direction == "BUY":
        return close_price >= (asian_high + close_buffer)
    return close_price <= (asian_low - close_buffer)


def fill_triggered(order_type: str, side: str, bar: pd.Series, entry: float) -> bool:
    if side == "BUY":
        low = float(bar["low_ask"]) if "low_ask" in bar and pd.notna(bar["low_ask"]) else float(bar["low"])
        high = float(bar["high_ask"]) if "high_ask" in bar and pd.notna(bar["high_ask"]) else float(bar["high"])
        if order_type == "LIMIT":
            return low <= entry
        return high >= entry
    low = float(bar["low_bid"]) if "low_bid" in bar and pd.notna(bar["low_bid"]) else float(bar["low"])
    high = float(bar["high_bid"]) if "high_bid" in bar and pd.notna(bar["high_bid"]) else float(bar["high"])
    if order_type == "LIMIT":
        return high >= entry
    return low <= entry


def resolve_exit(side: str, bar: pd.Series, stop_loss: float, take_profit: float) -> tuple[float, str] | None:
    if side == "BUY":
        low = float(bar["low_bid"]) if "low_bid" in bar and pd.notna(bar["low_bid"]) else float(bar["low"])
        high = float(bar["high_bid"]) if "high_bid" in bar and pd.notna(bar["high_bid"]) else float(bar["high"])
        if low <= stop_loss:
            return stop_loss, "stop_loss"
        if high >= take_profit:
            return take_profit, "take_profit"
        return None
    low = float(bar["low_ask"]) if "low_ask" in bar and pd.notna(bar["low_ask"]) else float(bar["low"])
    high = float(bar["high_ask"]) if "high_ask" in bar and pd.notna(bar["high_ask"]) else float(bar["high"])
    if high >= stop_loss:
        return stop_loss, "stop_loss"
    if low <= take_profit:
        return take_profit, "take_profit"
    return None


def partial_take_profit_price(entry: float, risk_unit: float, direction: str, partial_r_multiple: float) -> float:
    if direction == "BUY":
        return entry + (risk_unit * partial_r_multiple)
    return entry - (risk_unit * partial_r_multiple)


def resolve_time_exit(
    history: pd.DataFrame,
    *,
    fill_time: dt.datetime,
    deadline: dt.datetime,
    side: str | None = None,
) -> tuple[float, dt.datetime]:
    deadline_ts = pd.Timestamp(deadline)
    eligible_rows = history[
        (history["time"] >= pd.Timestamp(fill_time))
        & (history["time"] <= deadline_ts)
    ]
    if not eligible_rows.empty:
        forced_row = eligible_rows.iloc[-1]
        if side == "BUY":
            exit_price = float(forced_row["close_bid"]) if "close_bid" in forced_row and pd.notna(forced_row["close_bid"]) else float(forced_row["close"])
        elif side == "SELL":
            exit_price = float(forced_row["close_ask"]) if "close_ask" in forced_row and pd.notna(forced_row["close_ask"]) else float(forced_row["close"])
        else:
            exit_price = float(forced_row["close"])
        return exit_price, deadline

    future_rows = history[history["time"] > deadline_ts]
    if not future_rows.empty:
        forced_row = future_rows.iloc[0]
        exit_time = forced_row["time"].to_pydatetime().astimezone(dt.timezone.utc)
        if side == "BUY":
            exit_price = float(forced_row["open_bid"]) if "open_bid" in forced_row and pd.notna(forced_row["open_bid"]) else float(forced_row["open"])
        elif side == "SELL":
            exit_price = float(forced_row["open_ask"]) if "open_ask" in forced_row and pd.notna(forced_row["open_ask"]) else float(forced_row["open"])
        else:
            exit_price = float(forced_row["open"])
        return exit_price, exit_time

    last_row = history.iloc[-1]
    exit_time = last_row["time"].to_pydatetime().astimezone(dt.timezone.utc)
    if side == "BUY":
        exit_price = float(last_row["close_bid"]) if "close_bid" in last_row and pd.notna(last_row["close_bid"]) else float(last_row["close"])
    elif side == "SELL":
        exit_price = float(last_row["close_ask"]) if "close_ask" in last_row and pd.notna(last_row["close_ask"]) else float(last_row["close"])
    else:
        exit_price = float(last_row["close"])
    return exit_price, exit_time


def build_trade_frame(trades: list[BacktestTrade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(trade) for trade in trades])


def _numeric_series_or_default(
    trades_df: pd.DataFrame,
    column: str,
    *,
    default: float = 0.0,
) -> pd.Series:
    if column not in trades_df:
        return pd.Series([default] * len(trades_df), index=trades_df.index, dtype=float)
    return pd.to_numeric(trades_df[column], errors="coerce").fillna(default)


def _coerce_optional_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _size_portfolio_trade_for_target_margin(
    trade: pd.Series,
    *,
    target_margin: float,
) -> dict[str, Any]:
    margin_per_unit = _coerce_optional_float(trade.get("margin_per_unit_account"))
    pnl_account_per_unit = _coerce_optional_float(trade.get("pnl_account_per_unit"))
    min_size = _coerce_optional_float(trade.get("min_size")) or 0.0
    size_step = _coerce_optional_float(trade.get("size_step"))

    if margin_per_unit is None or margin_per_unit <= 0:
        return {"ok": False, "reason": "missing margin_per_unit_account"}
    if pnl_account_per_unit is None:
        return {"ok": False, "reason": "missing pnl_account_per_unit"}

    sizing_result = size_for_target_margin(
        target_margin=target_margin,
        margin_per_unit=margin_per_unit,
        min_size=min_size,
        size_step=size_step,
    )
    if not sizing_result.get("ok"):
        return sizing_result

    size = float(sizing_result["size"])
    estimated_margin = float(sizing_result["estimated_margin"])
    return {
        **sizing_result,
        "size": size,
        "estimated_margin": estimated_margin,
        "pnl_account": float(size * pnl_account_per_unit),
    }


def market_spread_points(market_info: dict[str, Any]) -> float:
    snapshot = market_info.get("snapshot", {}) if isinstance(market_info, dict) else {}
    bid = snapshot.get("bid")
    offer = snapshot.get("offer")
    try:
        if bid is None or offer is None:
            return 0.0
        spread = float(offer) - float(bid)
    except (TypeError, ValueError):
        return 0.0
    return spread if spread > 0 else 0.0


def trade_friction_points(
    market_info: dict[str, Any],
    *,
    spread_multiplier: float = 0.0,
    slippage_multiplier: float = 0.0,
) -> tuple[float, float, float]:
    live_spread = market_spread_points(market_info)
    applied_spread = live_spread * max(float(spread_multiplier), 0.0)
    slippage_per_side = live_spread * max(float(slippage_multiplier), 0.0)
    total_friction = applied_spread + (2.0 * slippage_per_side)
    return applied_spread, slippage_per_side, total_friction


def _overnight_fee_details(market_info: dict[str, Any]) -> dict[str, Any]:
    instrument = market_info.get("instrument", {}) if isinstance(market_info, dict) else {}
    overnight_fee = instrument.get("overnightFee", {})
    return overnight_fee if isinstance(overnight_fee, dict) else {}


def _overnight_funding_account_per_unit(
    *,
    api: CapitalAPI,
    symbol: str,
    market_info: dict[str, Any],
    side: str,
    fill_time: dt.datetime,
    exit_time: dt.datetime,
    account_currency: str,
    price_history: pd.DataFrame,
    quote_currency: str,
    start_time: dt.datetime,
    end_time: dt.datetime,
    conversion_cache: dict[tuple[str, str, dt.datetime, dt.datetime], tuple[pd.DataFrame, bool] | None],
) -> tuple[float, int]:
    overnight_fee = _overnight_fee_details(market_info)
    charge_times = overnight_funding_charge_times(
        fill_time_utc=fill_time,
        exit_time_utc=exit_time,
        swap_charge_timestamp_ms=overnight_fee.get("swapChargeTimestamp"),
        swap_charge_interval_minutes=overnight_fee.get("swapChargeInterval"),
    )
    if not charge_times:
        return 0.0, 0

    rate_key = "longRate" if side == "BUY" else "shortRate"
    try:
        daily_rate_pct = float(overnight_fee.get(rate_key))
    except (TypeError, ValueError):
        return 0.0, 0

    total_account = 0.0
    for charge_time in charge_times:
        subset = price_history[price_history["time"] <= pd.Timestamp(charge_time)]
        if subset.empty:
            subset = price_history
        if subset.empty:
            continue
        price_value = float(subset.iloc[-1]["close"])
        if price_value <= 0:
            continue
        conversion_rate = conversion_rate_at(
            api,
            from_currency=quote_currency,
            to_currency=account_currency.upper(),
            timestamp=charge_time,
            start_time=start_time,
            end_time=end_time,
            cache=conversion_cache,
        )
        notional_account_per_unit = price_value * float(conversion_rate)
        total_account += notional_account_per_unit * (daily_rate_pct / 100.0)
    return float(total_account), len(charge_times)


def summarize_trade_frame(
    trades_df: pd.DataFrame,
    *,
    start_time: dt.datetime,
    end_time: dt.datetime,
) -> dict[str, float]:
    if trades_df.empty:
        return {
            "Trades": 0.0,
            "WinRate": 0.0,
            "NetR": 0.0,
            "AvgR": 0.0,
            "ProfitFactorR": 0.0,
            "NetPnLAccount": 0.0,
            "AvgPnLAccount": 0.0,
            "FinalEquityAccount": 0.0,
            "ReturnPct": 0.0,
            "AvgHoldingHours": 0.0,
            "TradesPerWeek": 0.0,
        }

    gross_positive_r = trades_df.loc[trades_df["r_multiple"] > 0, "r_multiple"].sum()
    gross_negative_r = abs(trades_df.loc[trades_df["r_multiple"] < 0, "r_multiple"].sum())
    span_days = max((end_time - start_time).total_seconds() / 86_400.0, 1e-9)
    r_series = _numeric_series_or_default(trades_df, "r_multiple")
    holding_series = _numeric_series_or_default(trades_df, "holding_hours")
    pnl_series = _numeric_series_or_default(trades_df, "pnl_account_currency")
    initial_equity = (
        float(_numeric_series_or_default(trades_df, "equity_before").iloc[0])
        if "equity_before" in trades_df
        else 0.0
    )
    final_equity = (
        float(_numeric_series_or_default(trades_df, "equity_after").iloc[-1])
        if "equity_after" in trades_df
        else 0.0
    )
    win_mask = pnl_series > 0 if "pnl_account_currency" in trades_df else r_series > 0
    return {
        "Trades": float(len(trades_df)),
        "WinRate": float(win_mask.mean() * 100.0),
        "NetR": float(r_series.sum()),
        "AvgR": float(r_series.mean()),
        "ProfitFactorR": float(gross_positive_r / gross_negative_r) if gross_negative_r else 0.0,
        "NetPnLAccount": float(pnl_series.sum()),
        "AvgPnLAccount": float(pnl_series.mean()),
        "FinalEquityAccount": final_equity,
        "ReturnPct": float(((final_equity / initial_equity) - 1.0) * 100.0) if initial_equity > 0 else 0.0,
        "AvgHoldingHours": float(holding_series.mean()),
        "TradesPerWeek": float((len(trades_df) / span_days) * 7.0),
    }


def render_summary(symbol: str, summary: dict[str, float]) -> str:
    signal_relative_volume_threshold = summary.get("SignalRelativeVolumeThreshold")
    breakout_close_buffer_atr_fraction = summary.get("BreakoutCloseBufferAtrFraction")
    partial_take_profit_fraction = summary.get("PartialTakeProfitFraction")
    partial_take_profit_r_multiple = summary.get("PartialTakeProfitRMultiple")
    return "\n".join(
        [
            f"Backtest Summary: {symbol}",
            f"Trades: {summary['Trades']:.0f}",
            f"WinRate: {summary['WinRate']:.2f}%",
            f"NetPnLAccount: {summary['NetPnLAccount']:.2f}",
            f"FinalEquityAccount: {summary['FinalEquityAccount']:.2f}",
            f"ReturnPct: {summary['ReturnPct']:.2f}%",
            f"NetR: {summary['NetR']:.2f}",
            f"AvgR: {summary['AvgR']:.2f}",
            f"ProfitFactorR: {summary['ProfitFactorR']:.2f}",
            f"AvgPnLAccount: {summary['AvgPnLAccount']:.2f}",
            f"AvgHoldingHours: {summary['AvgHoldingHours']:.2f}",
            f"TradesPerWeek: {summary['TradesPerWeek']:.2f}",
            f"AppliedSpreadMultiplier: {summary.get('AppliedSpreadMultiplier', 0.0):.2f}",
            f"AppliedSlippageMultiplier: {summary.get('AppliedSlippageMultiplier', 0.0):.2f}",
            f"AppliedTotalFrictionPoints: {summary.get('AppliedTotalFrictionPoints', 0.0):.6f}",
            (
                f"EntrySignalCutoffHourUTC: {summary.get('EntrySignalCutoffHourUTC', 0.0):.0f}"
                if summary.get("EntrySignalCutoffHourUTC") is not None
                else "EntrySignalCutoffHourUTC: off"
            ),
            (
                f"EntrySignalCutoffWeekdaysUTC: {summary.get('EntrySignalCutoffWeekdaysUTC')}"
                if summary.get("EntrySignalCutoffWeekdaysUTC") is not None
                else "EntrySignalCutoffWeekdaysUTC: all"
            ),
            f"GBPJPYH4EMA50TrendFilter: {'on' if summary.get('GBPJPYH4EMA50TrendFilter') else 'off'}",
            f"GBPJPYBreakoutBufferAtrFraction: {summary.get('GBPJPYBreakoutBufferAtrFraction', 0.0):.3f}",
            (
                f"GBPJPYEntrySignalCutoffHourUTC: {summary.get('GBPJPYEntrySignalCutoffHourUTC', 0.0):.0f}"
                if summary.get("GBPJPYEntrySignalCutoffHourUTC") is not None
                else "GBPJPYEntrySignalCutoffHourUTC: off"
            ),
            (
                f"MaxSignalAgeHours: {summary.get('MaxSignalAgeHours', 0.0):.2f}"
                if summary.get("MaxSignalAgeHours") is not None
                else "MaxSignalAgeHours: off"
            ),
            (
                f"SignalRelativeVolumeThreshold: {float(signal_relative_volume_threshold):.2f}"
                if signal_relative_volume_threshold not in (None, 0, 0.0)
                else "SignalRelativeVolumeThreshold: off"
            ),
            (
                f"BreakoutCloseBufferAtrFraction: {float(breakout_close_buffer_atr_fraction):.3f}"
                if breakout_close_buffer_atr_fraction not in (None, 0, 0.0)
                else "BreakoutCloseBufferAtrFraction: off"
            ),
            f"VWAPDirectionFilter: {'on' if summary.get('VWAPDirectionFilter') else 'off'}",
            (
                f"PartialTakeProfit: {float(partial_take_profit_fraction):.2f} at {float(partial_take_profit_r_multiple):.2f}R"
                if partial_take_profit_fraction is not None and partial_take_profit_r_multiple is not None
                else "PartialTakeProfit: off"
            ),
            f"GBPJPYDisableSell: {'on' if summary.get('GBPJPYDisableSell') else 'off'}",
        ]
    )


def _timestamped_path(path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def _safe_write_csv(frame: pd.DataFrame, path: Path) -> Path:
    try:
        frame.to_csv(path, index=False)
        return path
    except PermissionError:
        alt_path = _timestamped_path(path)
        frame.to_csv(alt_path, index=False)
        return alt_path


def _safe_write_text(content: str, path: Path) -> Path:
    try:
        path.write_text(content, encoding="utf-8")
        return path
    except PermissionError:
        alt_path = _timestamped_path(path)
        alt_path.write_text(content, encoding="utf-8")
        return alt_path


def _format_api_datetime(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def fetch_hour_history(
    api: CapitalAPI,
    epic: str,
    *,
    candles: int,
    start_time: dt.datetime | None = None,
    end_time: dt.datetime | None = None,
) -> pd.DataFrame:
    if start_time is None and end_time is None:
        return parse_candles_bid_ask(api.get_candles(epic, resolution="HOUR", max_candles=candles))

    end_utc = min(end_time or dt.datetime.now(dt.timezone.utc), dt.datetime.now(dt.timezone.utc))
    if start_time is None:
        start_time = end_utc - dt.timedelta(hours=candles)
    start_utc = start_time.astimezone(dt.timezone.utc)

    rows: list[dict[str, Any]] = []
    cursor = start_utc
    while cursor <= end_utc:
        chunk_end = min(cursor + dt.timedelta(days=30) - dt.timedelta(seconds=1), end_utc)
        response = api.request(
            "GET",
            f"/prices/{epic}",
            params={
                "resolution": "HOUR",
                "from": _format_api_datetime(cursor),
                "to": _format_api_datetime(chunk_end),
                "max": 1000,
            },
        ).json()
        rows.extend(response.get("prices", []) if isinstance(response, dict) else [])
        cursor = chunk_end + dt.timedelta(seconds=1)

    if not rows:
        return pd.DataFrame()
    frame = parse_candles_bid_ask({"prices": rows})
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)


def conversion_epic_candidates(from_currency: str, to_currency: str) -> list[tuple[str, bool]]:
    if from_currency == to_currency:
        return []
    return [
        (f"{from_currency}{to_currency}", False),
        (f"{to_currency}{from_currency}", True),
    ]


def load_conversion_history(
    api: CapitalAPI,
    *,
    from_currency: str,
    to_currency: str,
    start_time: dt.datetime,
    end_time: dt.datetime,
    cache: dict[tuple[str, str, dt.datetime, dt.datetime], tuple[pd.DataFrame, bool] | None],
) -> tuple[pd.DataFrame, bool] | None:
    key = (from_currency, to_currency, start_time, end_time)
    if key in cache:
        return cache[key]

    if from_currency == to_currency:
        cache[key] = (pd.DataFrame(), False)
        return cache[key]

    for epic, inverted in conversion_epic_candidates(from_currency, to_currency):
        try:
            frame = fetch_hour_history(api, epic, candles=1000, start_time=start_time, end_time=end_time)
        except Exception:  # noqa: BLE001
            continue
        if frame.empty:
            continue
        cache[key] = (frame, inverted)
        return cache[key]

    cache[key] = None
    return None


def conversion_rate_at(
    api: CapitalAPI,
    *,
    from_currency: str,
    to_currency: str,
    timestamp: dt.datetime,
    start_time: dt.datetime,
    end_time: dt.datetime,
    cache: dict[tuple[str, str, dt.datetime, dt.datetime], tuple[pd.DataFrame, bool] | None],
) -> float:
    if from_currency == to_currency:
        return 1.0

    resolved = load_conversion_history(
        api,
        from_currency=from_currency,
        to_currency=to_currency,
        start_time=start_time,
        end_time=end_time,
        cache=cache,
    )
    if resolved is None:
        return 1.0
    frame, inverted = resolved
    if frame.empty:
        return 1.0
    subset = frame[frame["time"] <= pd.Timestamp(timestamp)]
    if subset.empty:
        subset = frame
    close_value = float(subset.iloc[-1]["close"])
    if close_value <= 0:
        return 1.0
    return 1.0 / close_value if inverted else close_value


def run_symbol_backtest(api: CapitalAPI, config: AppConfig, symbol: str, candles: int) -> tuple[pd.DataFrame, dict[str, float]]:
    return run_symbol_backtest_in_range(api, config, symbol, candles=candles)


def run_symbol_backtest_in_range(
    api: CapitalAPI,
    config: AppConfig,
    symbol: str,
    *,
    candles: int,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    initial_equity: float = 10_000.0,
    target_margin_usd: float | None = None,
    account_currency: str = "USD",
    leverage_overrides: dict[str, float] | None = None,
    allow_size_failures: bool = False,
    spread_multiplier: float = 0.0,
    slippage_multiplier: float = 0.0,
    entry_signal_cutoff_hour_utc: int | None = None,
    entry_signal_cutoff_weekdays_utc: set[int] | None = None,
    gbpjpy_h4_ema50_trend_filter: bool = False,
    gbpjpy_breakout_buffer_atr_fraction: float = 0.0,
    gbpjpy_entry_signal_cutoff_hour_utc: int | None = None,
    max_signal_age_hours: float | None = None,
    vwap_direction_filter: bool = False,
    signal_relative_volume_threshold: float = 0.0,
    breakout_close_buffer_atr_fraction: float = 0.0,
    partial_take_profit_fraction: float = 0.0,
    partial_take_profit_r_multiple: float = 1.0,
    gbpjpy_disable_sell: bool = False,
) -> tuple[pd.DataFrame, dict[str, float]]:
    epic = config.strategy.symbols[symbol]
    requested_start = (
        dt.datetime.combine(start_date, dt.time(0, 0, tzinfo=dt.timezone.utc))
        if start_date is not None
        else None
    )
    requested_end = (
        dt.datetime.combine(end_date, dt.time(23, 59, 59, tzinfo=dt.timezone.utc))
        if end_date is not None
        else None
    )
    history = fetch_hour_history(
        api,
        epic,
        candles=candles,
        start_time=requested_start,
        end_time=requested_end,
    )
    if history.empty or len(history) < 100:
        return pd.DataFrame(), summarize_trade_frame(pd.DataFrame(), start_time=dt.datetime.now(dt.timezone.utc), end_time=dt.datetime.now(dt.timezone.utc))
    h4_trend = build_h4_ema50_trend_frame(history) if gbpjpy_h4_ema50_trend_filter else pd.DataFrame()
    intraday_vwap = build_intraday_vwap_frame(history) if vwap_direction_filter else pd.DataFrame()
    relative_signal_volume = build_relative_signal_volume_frame(history) if signal_relative_volume_threshold > 0 else pd.DataFrame()

    params = StrategyParameters(
        atr_period=config.strategy.atr_period,
        atr_filter_pct=config.strategy.atr_filter_pct,
        tp_multiplier=config.strategy.tp_multiplier,
    )
    account_preferences = api.get_account_preferences()
    market_info = api.get_market_details(epic)
    rules = extract_market_rules(market_info)
    applied_spread_points, slippage_points_per_side, total_friction_points = trade_friction_points(
        market_info,
        spread_multiplier=spread_multiplier,
        slippage_multiplier=slippage_multiplier,
    )
    quote_currency = str(market_info.get("instrument", {}).get("currency") or account_currency).upper()
    target_margin_value = float(target_margin_usd or config.strategy.target_margin_usd)
    leverage_map = dict(config.strategy.target_leverage_by_type)
    if leverage_overrides:
        leverage_map.update(leverage_overrides)
    conversion_cache: dict[tuple[str, str, dt.datetime, dt.datetime], tuple[pd.DataFrame, bool] | None] = {}
    equity = float(initial_equity)

    session_dates = sorted(
        {
            current_session_date(ts.to_pydatetime().astimezone(dt.timezone.utc), config.strategy.session_start_hour_utc)
            for ts in history["time"]
        }
    )
    if start_date is not None:
        session_dates = [session_date for session_date in session_dates if session_date >= start_date]
    if end_date is not None:
        session_dates = [session_date for session_date in session_dates if session_date <= end_date]
    trades: list[BacktestTrade] = []

    for session_date in session_dates:
        asian_high, asian_low = get_asian_range(history, session_date)
        if asian_high is None or asian_low is None:
            continue

        session_rows = history[
            (history["time"].dt.date == session_date)
            & (history["time"].dt.hour >= config.strategy.entry_start_hour_utc)
            & (history["time"].dt.hour <= config.strategy.entry_end_hour_utc)
        ].copy()
        if entry_signal_cutoff_hour_utc is not None:
            if entry_signal_cutoff_weekdays_utc is None:
                session_rows = session_rows[session_rows["time"].dt.hour < entry_signal_cutoff_hour_utc].copy()
            else:
                session_rows = session_rows[
                    ~(
                        session_rows["time"].dt.weekday.isin(entry_signal_cutoff_weekdays_utc)
                        & (session_rows["time"].dt.hour >= entry_signal_cutoff_hour_utc)
                    )
                ].copy()
        if gbpjpy_entry_signal_cutoff_hour_utc is not None and symbol.upper() == "GBPJPY":
            session_rows = session_rows[session_rows["time"].dt.hour < gbpjpy_entry_signal_cutoff_hour_utc].copy()
        if session_rows.empty:
            continue

        signal_row = None
        direction = None
        signal_entry = None
        for _, candle in session_rows.iterrows():
            subset_to_candle = history[history["time"] <= candle["time"]].copy()
            atr_value_for_signal = atr_filter(subset_to_candle, float(candle["close"]), params)
            if atr_value_for_signal is None:
                continue

            close_price = float(candle["close"])
            buy_entry = gbpjpy_buffered_entry(
                symbol=symbol,
                direction="BUY",
                asian_high=asian_high,
                asian_low=asian_low,
                atr_value=atr_value_for_signal,
                gbpjpy_breakout_buffer_atr_fraction=gbpjpy_breakout_buffer_atr_fraction,
            )
            sell_entry = gbpjpy_buffered_entry(
                symbol=symbol,
                direction="SELL",
                asian_high=asian_high,
                asian_low=asian_low,
                atr_value=atr_value_for_signal,
                gbpjpy_breakout_buffer_atr_fraction=gbpjpy_breakout_buffer_atr_fraction,
            )
            if close_price >= buy_entry:
                if not passes_breakout_close_confirmation(
                    direction="BUY",
                    close_price=close_price,
                    asian_high=asian_high,
                    asian_low=asian_low,
                    atr_value=atr_value_for_signal,
                    breakout_close_buffer_atr_fraction=breakout_close_buffer_atr_fraction,
                ):
                    continue
                signal_row = candle
                direction = "BUY"
                signal_entry = buy_entry
                break
            if close_price <= sell_entry:
                if not passes_breakout_close_confirmation(
                    direction="SELL",
                    close_price=close_price,
                    asian_high=asian_high,
                    asian_low=asian_low,
                    atr_value=atr_value_for_signal,
                    breakout_close_buffer_atr_fraction=breakout_close_buffer_atr_fraction,
                ):
                    continue
                signal_row = candle
                direction = "SELL"
                signal_entry = sell_entry
                break

        if signal_row is None or direction is None or signal_entry is None:
            continue
        if gbpjpy_disable_sell and symbol.upper() == "GBPJPY" and direction == "SELL":
            continue

        signal_time = signal_row["time"].to_pydatetime().astimezone(dt.timezone.utc)
        signal_close_price = float(signal_row["close"])
        if vwap_direction_filter and not passes_intraday_vwap_filter(
            direction=direction,
            signal_time=signal_time,
            signal_close_price=signal_close_price,
            intraday_vwap=intraday_vwap,
        ):
            continue
        if signal_relative_volume_threshold > 0 and not passes_relative_signal_volume_filter(
            signal_time=signal_time,
            min_relative_volume=signal_relative_volume_threshold,
            relative_volume_frame=relative_signal_volume,
        ):
            continue
        if gbpjpy_h4_ema50_trend_filter and not passes_gbpjpy_h4_ema50_filter(
            symbol=symbol,
            direction=direction,
            signal_time=signal_time,
            h4_trend=h4_trend,
        ):
            continue
        if not allow_size_failures and equity < target_margin_value:
            continue

        entry = float(signal_entry)
        subset_to_signal = history[history["time"] <= signal_row["time"]].copy()
        atr_value = atr_filter(subset_to_signal, entry, params)
        if atr_value is None:
            continue

        stop_loss, take_profit = calculate_levels(entry, atr_value, direction, params)
        margin_conversion_rate = conversion_rate_at(
            api,
            from_currency=quote_currency,
            to_currency=account_currency.upper(),
            timestamp=signal_time,
            start_time=history["time"].iloc[0].to_pydatetime().astimezone(dt.timezone.utc),
            end_time=history["time"].iloc[-1].to_pydatetime().astimezone(dt.timezone.utc),
            cache=conversion_cache,
        )
        margin_context = resolve_margin_context_live(
            entry_price=entry,
            market_info=market_info,
            account_preferences=account_preferences,
            leverage_overrides=leverage_map,
            margin_to_account_rate=margin_conversion_rate,
        )
        if not margin_context.get("ok"):
            continue
        size_info = choose_size_for_target_margin_live(
            entry_price=entry,
            market_info=market_info,
            account_preferences=account_preferences,
            target_margin=target_margin_value,
            leverage_overrides=leverage_map,
            margin_to_account_rate=margin_conversion_rate,
        )
        if not size_info.get("ok") and not allow_size_failures:
            continue

        current_price = float(signal_row["close"])
        order_type = choose_working_order_type(direction, entry, current_price)
        candidate_rows = history[history["time"] > signal_row["time"]].copy()
        fill_row = None
        for _, candle in candidate_rows.iterrows():
            candle_time = candle["time"].to_pydatetime().astimezone(dt.timezone.utc)
            if candle_time.date() != session_date:
                break
            if max_signal_age_hours is not None:
                signal_age_hours = (candle_time - signal_time).total_seconds() / 3600.0
                if signal_age_hours > max_signal_age_hours:
                    break
            if fill_triggered(order_type, direction, candle, entry):
                fill_row = candle
                break

        if fill_row is None:
            continue

        fill_time = fill_row["time"].to_pydatetime().astimezone(dt.timezone.utc)
        deadline = close_deadline_for_trade_day(
            session_date,
            next_day_close_hour_utc=config.strategy.position_force_close_hour_utc,
            next_day_close_minute_utc=config.strategy.position_force_close_minute_utc,
            weekend_close_hour_utc=config.strategy.weekend_close_hour_utc,
            weekend_close_minute_utc=config.strategy.weekend_close_minute_utc,
        )

        exit_price = None
        exit_reason = None
        exit_time = None
        future_rows = history[history["time"] > fill_row["time"]].copy()
        for _, candle in future_rows.iterrows():
            candle_time = candle["time"].to_pydatetime().astimezone(dt.timezone.utc)
            if candle_time > deadline:
                break
            resolved = resolve_exit(direction, candle, stop_loss, take_profit)
            if resolved is None:
                continue
            exit_price, exit_reason = resolved
            exit_time = candle_time
            break

        if exit_price is None or exit_reason is None or exit_time is None:
            exit_price, exit_time = resolve_time_exit(
                history,
                fill_time=fill_time,
                deadline=deadline,
                side=direction,
            )
            exit_reason = "time_exit"

        risk_unit = abs(entry - stop_loss)
        if risk_unit <= 0:
            continue
        use_partial_take_profit = 0.0 < partial_take_profit_fraction < 1.0 and partial_take_profit_r_multiple > 0.0
        raw_pnl_points = 0.0
        if use_partial_take_profit:
            partial_target = partial_take_profit_price(
                entry,
                risk_unit,
                direction,
                partial_take_profit_r_multiple,
            )
            partial_taken = False
            partial_fill_time = None
            remaining_exit_price = None
            remaining_exit_reason = None
            remaining_exit_time = None
            for _, candle in future_rows.iterrows():
                candle_time = candle["time"].to_pydatetime().astimezone(dt.timezone.utc)
                if candle_time > deadline:
                    break
                if not partial_taken:
                    partial_resolved = resolve_exit(direction, candle, stop_loss, partial_target)
                    if partial_resolved is None:
                        continue
                    partial_price, partial_reason = partial_resolved
                    if partial_reason == "stop_loss":
                        remaining_exit_price = partial_price
                        remaining_exit_reason = partial_reason
                        remaining_exit_time = candle_time
                        break
                    partial_taken = True
                    partial_fill_time = candle_time
                    continue
                remaining_resolved = resolve_exit(direction, candle, stop_loss, take_profit)
                if remaining_resolved is None:
                    continue
                remaining_exit_price, remaining_exit_reason = remaining_resolved
                remaining_exit_time = candle_time
                break

            if partial_taken and (
                remaining_exit_price is None or remaining_exit_reason is None or remaining_exit_time is None
            ):
                remaining_exit_price, remaining_exit_time = resolve_time_exit(
                    history,
                    fill_time=partial_fill_time or fill_time,
                    deadline=deadline,
                    side=direction,
                )
                remaining_exit_reason = "time_exit"

            if partial_taken and remaining_exit_price is not None and remaining_exit_reason is not None and remaining_exit_time is not None:
                if direction == "BUY":
                    partial_leg_points = partial_target - entry
                    remaining_leg_points = remaining_exit_price - entry
                else:
                    partial_leg_points = entry - partial_target
                    remaining_leg_points = entry - remaining_exit_price
                raw_pnl_points = (
                    partial_take_profit_fraction * partial_leg_points
                    + (1.0 - partial_take_profit_fraction) * remaining_leg_points
                )
                exit_price = float(remaining_exit_price)
                exit_reason = f"partial_tp_then_{remaining_exit_reason}"
                exit_time = remaining_exit_time
            else:
                if remaining_exit_price is None or remaining_exit_reason is None or remaining_exit_time is None:
                    continue
                if direction == "BUY":
                    raw_pnl_points = remaining_exit_price - entry
                else:
                    raw_pnl_points = entry - remaining_exit_price
                exit_price = float(remaining_exit_price)
                exit_reason = remaining_exit_reason
                exit_time = remaining_exit_time
        else:
            if direction == "BUY":
                raw_pnl_points = exit_price - entry
            else:
                raw_pnl_points = entry - exit_price
        contract_size = float(rules.get("contract_size") or 1.0)
        pnl_points = raw_pnl_points - total_friction_points
        pnl_quote_per_unit = pnl_points * contract_size
        pnl_conversion_rate = conversion_rate_at(
            api,
            from_currency=quote_currency,
            to_currency=account_currency.upper(),
            timestamp=exit_time,
            start_time=history["time"].iloc[0].to_pydatetime().astimezone(dt.timezone.utc),
            end_time=history["time"].iloc[-1].to_pydatetime().astimezone(dt.timezone.utc),
            cache=conversion_cache,
        )
        pnl_account_per_unit = pnl_quote_per_unit * pnl_conversion_rate
        overnight_funding_account_per_unit, overnight_funding_events = _overnight_funding_account_per_unit(
            api=api,
            symbol=symbol,
            market_info=market_info,
            side=direction,
            fill_time=fill_time,
            exit_time=exit_time,
            account_currency=account_currency,
            price_history=history,
            quote_currency=quote_currency,
            start_time=history["time"].iloc[0].to_pydatetime().astimezone(dt.timezone.utc),
            end_time=history["time"].iloc[-1].to_pydatetime().astimezone(dt.timezone.utc),
            conversion_cache=conversion_cache,
        )
        pnl_account_per_unit += overnight_funding_account_per_unit
        r_multiple = pnl_points / risk_unit
        equity_before = equity
        size = float(size_info["size"]) if size_info.get("ok") else None
        estimated_margin = (
            float(size_info["estimated_margin"])
            if size_info.get("ok") and size_info.get("estimated_margin") is not None
            else None
        )
        pnl_quote_currency = float(pnl_quote_per_unit * size) if size is not None else None
        pnl_account_currency = float(pnl_account_per_unit * size) if size is not None else None
        if pnl_account_currency is not None:
            equity_after = equity_before + pnl_account_currency
            equity = equity_after
        else:
            equity_after = equity_before
        is_usd_account = account_currency.upper() == "USD"

        trades.append(
            BacktestTrade(
                symbol=symbol,
                session_date=session_date.isoformat(),
                side=direction,
                order_type=order_type,
                signal_time_utc=signal_time.isoformat(),
                fill_time_utc=fill_time.isoformat(),
                exit_time_utc=exit_time.isoformat(),
                entry=float(entry),
                stop_loss=float(stop_loss),
                take_profit=float(take_profit),
                exit_price=float(exit_price),
                exit_reason=exit_reason,
                size=size,
                estimated_margin=estimated_margin,
                estimated_margin_usd=float(estimated_margin) if is_usd_account and estimated_margin is not None else None,
                account_currency=account_currency.upper(),
                pnl_points=float(pnl_points),
                pnl_quote_currency=pnl_quote_currency,
                pnl_account_currency=pnl_account_currency,
                pnl_usd=float(pnl_account_currency) if is_usd_account else None,
                r_multiple=float(r_multiple),
                holding_hours=(exit_time - fill_time).total_seconds() / 3600.0,
                equity_before=float(equity_before),
                equity_after=float(equity_after),
                equity_before_usd=float(equity_before) if is_usd_account else None,
                equity_after_usd=float(equity_after) if is_usd_account else None,
                margin_per_unit_account=float(margin_context["margin_per_unit"]),
                pnl_account_per_unit=float(pnl_account_per_unit),
                overnight_funding_account=float(overnight_funding_account_per_unit * size) if size is not None else None,
                overnight_funding_events=int(overnight_funding_events),
                min_size=float(margin_context["rules"]["min_size"]),
                size_step=(
                    float(margin_context["rules"]["size_step"])
                    if margin_context["rules"]["size_step"] is not None
                    else None
                ),
                spread_points=float(applied_spread_points),
                slippage_points_per_side=float(slippage_points_per_side),
                total_friction_points=float(total_friction_points),
            )
        )

    trades_df = build_trade_frame(trades)
    analysis_start = (
        dt.datetime.combine(start_date, dt.time(0, 0, tzinfo=dt.timezone.utc))
        if start_date is not None
        else history["time"].iloc[0].to_pydatetime().astimezone(dt.timezone.utc)
    )
    analysis_end = (
        dt.datetime.combine(end_date, dt.time(23, 59, 59, tzinfo=dt.timezone.utc))
        if end_date is not None
        else history["time"].iloc[-1].to_pydatetime().astimezone(dt.timezone.utc)
    )
    summary = summarize_trade_frame(
        trades_df,
        start_time=analysis_start,
        end_time=analysis_end,
    )
    if "contract_size" in rules:
        summary["ContractSize"] = float(rules["contract_size"])
    summary["AppliedSpreadPoints"] = float(applied_spread_points)
    summary["AppliedSpreadMultiplier"] = float(spread_multiplier)
    summary["AppliedSlippagePointsPerSide"] = float(slippage_points_per_side)
    summary["AppliedSlippageMultiplier"] = float(slippage_multiplier)
    summary["AppliedTotalFrictionPoints"] = float(total_friction_points)
    summary["InitialEquityAccount"] = float(initial_equity)
    summary["TargetMarginAccount"] = float(target_margin_value)
    if entry_signal_cutoff_hour_utc is not None:
        summary["EntrySignalCutoffHourUTC"] = float(entry_signal_cutoff_hour_utc)
    if entry_signal_cutoff_weekdays_utc is not None:
        summary["EntrySignalCutoffWeekdaysUTC"] = ",".join(str(day) for day in sorted(entry_signal_cutoff_weekdays_utc))
    summary["GBPJPYH4EMA50TrendFilter"] = bool(gbpjpy_h4_ema50_trend_filter)
    summary["GBPJPYBreakoutBufferAtrFraction"] = float(gbpjpy_breakout_buffer_atr_fraction)
    if gbpjpy_entry_signal_cutoff_hour_utc is not None:
        summary["GBPJPYEntrySignalCutoffHourUTC"] = float(gbpjpy_entry_signal_cutoff_hour_utc)
    if max_signal_age_hours is not None:
        summary["MaxSignalAgeHours"] = float(max_signal_age_hours)
    summary["VWAPDirectionFilter"] = bool(vwap_direction_filter)
    summary["SignalRelativeVolumeThreshold"] = float(signal_relative_volume_threshold)
    summary["BreakoutCloseBufferAtrFraction"] = float(breakout_close_buffer_atr_fraction)
    if 0.0 < partial_take_profit_fraction < 1.0 and partial_take_profit_r_multiple > 0.0:
        summary["PartialTakeProfitFraction"] = float(partial_take_profit_fraction)
        summary["PartialTakeProfitRMultiple"] = float(partial_take_profit_r_multiple)
    summary["GBPJPYDisableSell"] = bool(gbpjpy_disable_sell)
    if account_currency.upper() == "USD":
        summary["NetPnLUSD"] = summary["NetPnLAccount"]
        summary["FinalEquityUSD"] = summary["FinalEquityAccount"]
    return trades_df, summary


def run_backtests(
    api: CapitalAPI,
    config: AppConfig,
    symbols: list[str] | None = None,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    initial_equity: float = 10_000.0,
    target_margin_usd: float | None = None,
    account_currency: str = "USD",
    leverage_overrides: dict[str, float] | None = None,
    spread_multiplier: float = 0.0,
    slippage_multiplier: float = 0.0,
    entry_signal_cutoff_hour_utc: int | None = None,
    entry_signal_cutoff_weekdays_utc: set[int] | None = None,
    gbpjpy_h4_ema50_trend_filter: bool = False,
    gbpjpy_breakout_buffer_atr_fraction: float = 0.0,
    gbpjpy_entry_signal_cutoff_hour_utc: int | None = None,
    max_signal_age_hours: float | None = None,
    vwap_direction_filter: bool = False,
    signal_relative_volume_threshold: float = 0.0,
    breakout_close_buffer_atr_fraction: float = 0.0,
    partial_take_profit_fraction: float = 0.0,
    partial_take_profit_r_multiple: float = 1.0,
    gbpjpy_disable_sell: bool = False,
) -> dict[str, dict[str, float]]:
    selected_symbols = symbols or list(config.strategy.symbols.keys())
    config.backtest.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, float]] = {}

    for symbol in selected_symbols:
        trades_df, summary = run_symbol_backtest_in_range(
            api,
            config,
            symbol,
            candles=config.backtest.candles,
            start_date=start_date,
            end_date=end_date,
            initial_equity=initial_equity,
            target_margin_usd=target_margin_usd,
            account_currency=account_currency,
            leverage_overrides=leverage_overrides,
            spread_multiplier=spread_multiplier,
            slippage_multiplier=slippage_multiplier,
            entry_signal_cutoff_hour_utc=entry_signal_cutoff_hour_utc,
            entry_signal_cutoff_weekdays_utc=entry_signal_cutoff_weekdays_utc,
            gbpjpy_h4_ema50_trend_filter=gbpjpy_h4_ema50_trend_filter,
            gbpjpy_breakout_buffer_atr_fraction=gbpjpy_breakout_buffer_atr_fraction,
            gbpjpy_entry_signal_cutoff_hour_utc=gbpjpy_entry_signal_cutoff_hour_utc,
            max_signal_age_hours=max_signal_age_hours,
            vwap_direction_filter=vwap_direction_filter,
            signal_relative_volume_threshold=signal_relative_volume_threshold,
            breakout_close_buffer_atr_fraction=breakout_close_buffer_atr_fraction,
            partial_take_profit_fraction=partial_take_profit_fraction,
            partial_take_profit_r_multiple=partial_take_profit_r_multiple,
            gbpjpy_disable_sell=gbpjpy_disable_sell,
        )
        summaries[symbol] = summary
        trades_path = config.backtest.output_dir / f"{symbol.lower()}_trades.csv"
        summary_path = config.backtest.output_dir / f"{symbol.lower()}_summary.txt"
        metrics_path = config.backtest.output_dir / f"{symbol.lower()}_metrics.json"
        _safe_write_csv(trades_df, trades_path)
        _safe_write_text(render_summary(symbol, summary) + "\n", summary_path)
        _safe_write_text(json.dumps(summary, indent=2), metrics_path)

    return summaries


def _coerce_datetime_column(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def run_portfolio_backtest(
    api: CapitalAPI,
    config: AppConfig,
    symbols: list[str] | None = None,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    initial_equity: float = 10_000.0,
    target_margin_usd: float | None = None,
    account_currency: str = "USD",
    leverage_overrides: dict[str, float] | None = None,
    portfolio_margin_fraction: float | None = None,
    spread_multiplier: float = 0.0,
    slippage_multiplier: float = 0.0,
    entry_signal_cutoff_hour_utc: int | None = None,
    entry_signal_cutoff_weekdays_utc: set[int] | None = None,
    gbpjpy_h4_ema50_trend_filter: bool = False,
    gbpjpy_breakout_buffer_atr_fraction: float = 0.0,
    gbpjpy_entry_signal_cutoff_hour_utc: int | None = None,
    max_signal_age_hours: float | None = None,
    vwap_direction_filter: bool = False,
    signal_relative_volume_threshold: float = 0.0,
    breakout_close_buffer_atr_fraction: float = 0.0,
    partial_take_profit_fraction: float = 0.0,
    partial_take_profit_r_multiple: float = 1.0,
    gbpjpy_disable_sell: bool = False,
) -> tuple[pd.DataFrame, dict[str, float]]:
    selected_symbols = symbols or list(config.strategy.symbols.keys())
    candidate_frames: list[pd.DataFrame] = []
    guard_settings = regime_guard_settings_from_strategy(config.strategy)
    guard_trackers = {
        symbol: RegimeGuardTracker(guard_settings)
        for symbol in selected_symbols
    }
    regime_trigger_count = 0.0

    for symbol in selected_symbols:
        trades_df, _ = run_symbol_backtest_in_range(
            api,
            config,
            symbol,
            candles=config.backtest.candles,
            start_date=start_date,
            end_date=end_date,
            initial_equity=initial_equity,
            target_margin_usd=target_margin_usd,
            account_currency=account_currency,
            leverage_overrides=leverage_overrides,
            allow_size_failures=portfolio_margin_fraction is not None,
            spread_multiplier=spread_multiplier,
            slippage_multiplier=slippage_multiplier,
            entry_signal_cutoff_hour_utc=entry_signal_cutoff_hour_utc,
            entry_signal_cutoff_weekdays_utc=entry_signal_cutoff_weekdays_utc,
            gbpjpy_h4_ema50_trend_filter=gbpjpy_h4_ema50_trend_filter,
            gbpjpy_breakout_buffer_atr_fraction=gbpjpy_breakout_buffer_atr_fraction,
            gbpjpy_entry_signal_cutoff_hour_utc=gbpjpy_entry_signal_cutoff_hour_utc,
            max_signal_age_hours=max_signal_age_hours,
            vwap_direction_filter=vwap_direction_filter,
            signal_relative_volume_threshold=signal_relative_volume_threshold,
            breakout_close_buffer_atr_fraction=breakout_close_buffer_atr_fraction,
            partial_take_profit_fraction=partial_take_profit_fraction,
            partial_take_profit_r_multiple=partial_take_profit_r_multiple,
            gbpjpy_disable_sell=gbpjpy_disable_sell,
        )
        if trades_df.empty:
            continue
        candidate_frames.append(trades_df.copy())

    if not candidate_frames:
        empty_summary = {
            "Trades": 0.0,
            "AcceptedTrades": 0.0,
            "SkippedTrades": 0.0,
            "WinRate": 0.0,
            "NetPnLAccount": 0.0,
            "FinalEquityAccount": float(initial_equity),
            "ReturnPct": 0.0,
            "ProfitFactorAccount": 0.0,
            "AvgPnLAccount": 0.0,
            "AvgHoldingHours": 0.0,
            "TradesPerWeek": 0.0,
            "InitialEquityAccount": float(initial_equity),
            "TargetMarginAccount": float(target_margin_usd or config.strategy.target_margin_usd),
            "AccountCurrency": account_currency.upper(),
            "DynamicMarginFraction": float(portfolio_margin_fraction) if portfolio_margin_fraction is not None else None,
            "AppliedSpreadMultiplier": float(spread_multiplier),
            "AppliedSlippageMultiplier": float(slippage_multiplier),
            "RegimeGuardEnabled": bool(guard_settings.enabled),
            "RegimeGuardLookbackTrades": float(guard_settings.lookback_trades),
            "RegimeGuardMinClosedTrades": float(guard_settings.min_closed_trades),
            "RegimeGuardMinWinRatePct": float(guard_settings.min_win_rate_pct),
            "RegimeGuardMinNetPnL": float(guard_settings.min_net_pnl),
            "RegimeGuardMaxConsecutiveLosses": float(guard_settings.max_consecutive_losses),
            "RegimeGuardCooldownDays": float(guard_settings.cooldown_days),
            "RegimeGuardSkippedTrades": 0.0,
            "RegimeGuardTriggers": 0.0,
        }
        if entry_signal_cutoff_hour_utc is not None:
            empty_summary["EntrySignalCutoffHourUTC"] = float(entry_signal_cutoff_hour_utc)
        if entry_signal_cutoff_weekdays_utc is not None:
            empty_summary["EntrySignalCutoffWeekdaysUTC"] = ",".join(str(day) for day in sorted(entry_signal_cutoff_weekdays_utc))
        empty_summary["GBPJPYH4EMA50TrendFilter"] = bool(gbpjpy_h4_ema50_trend_filter)
        empty_summary["GBPJPYBreakoutBufferAtrFraction"] = float(gbpjpy_breakout_buffer_atr_fraction)
        if gbpjpy_entry_signal_cutoff_hour_utc is not None:
            empty_summary["GBPJPYEntrySignalCutoffHourUTC"] = float(gbpjpy_entry_signal_cutoff_hour_utc)
        if max_signal_age_hours is not None:
            empty_summary["MaxSignalAgeHours"] = float(max_signal_age_hours)
        empty_summary["VWAPDirectionFilter"] = bool(vwap_direction_filter)
        empty_summary["SignalRelativeVolumeThreshold"] = float(signal_relative_volume_threshold)
        empty_summary["BreakoutCloseBufferAtrFraction"] = float(breakout_close_buffer_atr_fraction)
        if 0.0 < partial_take_profit_fraction < 1.0 and partial_take_profit_r_multiple > 0.0:
            empty_summary["PartialTakeProfitFraction"] = float(partial_take_profit_fraction)
            empty_summary["PartialTakeProfitRMultiple"] = float(partial_take_profit_r_multiple)
        empty_summary["GBPJPYDisableSell"] = bool(gbpjpy_disable_sell)
        if account_currency.upper() == "USD":
            empty_summary["NetPnLUSD"] = empty_summary["NetPnLAccount"]
            empty_summary["FinalEquityUSD"] = empty_summary["FinalEquityAccount"]
            empty_summary["AvgPnLUSD"] = empty_summary["AvgPnLAccount"]
            empty_summary["ProfitFactorUSD"] = empty_summary["ProfitFactorAccount"]
            empty_summary["InitialEquityUSD"] = empty_summary["InitialEquityAccount"]
            empty_summary["TargetMarginUSD"] = empty_summary["TargetMarginAccount"]
        return pd.DataFrame(), empty_summary

    all_trades = pd.concat(candidate_frames, ignore_index=True)
    all_trades["fill_time_utc"] = _coerce_datetime_column(all_trades["fill_time_utc"])
    all_trades["exit_time_utc"] = _coerce_datetime_column(all_trades["exit_time_utc"])
    all_trades["portfolio_pnl_account"] = _numeric_series_or_default(
        all_trades,
        "pnl_account_currency",
    )
    all_trades["portfolio_margin_account"] = _numeric_series_or_default(
        all_trades,
        "estimated_margin",
    )
    all_trades = all_trades.sort_values(["fill_time_utc", "symbol"]).reset_index(drop=True)

    cash_equity = float(initial_equity)
    used_margin = 0.0
    open_positions: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] = []

    def settle_until(cutoff: pd.Timestamp) -> None:
        nonlocal cash_equity, used_margin, open_positions, regime_trigger_count
        still_open: list[dict[str, Any]] = []
        for position in sorted(open_positions, key=lambda row: row["exit_time_utc"]):
            if position["exit_time_utc"] <= cutoff:
                cash_equity += float(position["pnl_account"])
                used_margin -= float(position["estimated_margin_account"])
                tracker = guard_trackers.get(str(position["symbol"]))
                if tracker is not None:
                    did_trigger = tracker.record_trade(
                        position["exit_time_utc"].to_pydatetime().astimezone(dt.timezone.utc),
                        float(position["pnl_account"]),
                    )
                    if did_trigger:
                        regime_trigger_count += 1.0
            else:
                still_open.append(position)
        open_positions = still_open

    for _, trade in all_trades.iterrows():
        fill_time = trade["fill_time_utc"]
        exit_time = trade["exit_time_utc"]
        if pd.isna(fill_time) or pd.isna(exit_time):
            continue

        settle_until(fill_time)
        dynamic_target_margin = None
        dynamic_sizing = None
        symbol = str(trade["symbol"])
        tracker = guard_trackers.get(symbol)
        fill_dt = fill_time.to_pydatetime().astimezone(dt.timezone.utc)
        guard_blocked = tracker.is_blocked(fill_dt) if tracker is not None else False
        if portfolio_margin_fraction is not None:
            dynamic_target_margin = float(cash_equity * portfolio_margin_fraction)
            dynamic_sizing = _size_portfolio_trade_for_target_margin(
                trade,
                target_margin=dynamic_target_margin,
            )
            if dynamic_sizing.get("ok"):
                estimated_margin_account = float(dynamic_sizing["estimated_margin"])
                pnl_account = float(dynamic_sizing["pnl_account"])
            else:
                estimated_margin_account = 0.0
                pnl_account = 0.0
        else:
            estimated_margin_account = float(trade["portfolio_margin_account"])
            pnl_account = float(trade["portfolio_pnl_account"])

        available_margin = cash_equity - used_margin
        accepted = cash_equity > 0
        skip_reason = None
        if guard_blocked:
            accepted = False
            skip_reason = "regime_guard_cooldown"
        elif dynamic_sizing is not None and not dynamic_sizing.get("ok"):
            accepted = False
            skip_reason = str(dynamic_sizing.get("reason") or "dynamic_sizing_failed")
        elif available_margin < estimated_margin_account:
            accepted = False
            skip_reason = "insufficient_available_margin"

        row = trade.to_dict()
        row["accepted"] = accepted
        row["skip_reason"] = skip_reason
        row["portfolio_pnl_account"] = pnl_account
        row["estimated_margin_account"] = estimated_margin_account
        row["portfolio_target_margin_account"] = dynamic_target_margin
        row["portfolio_equity_before_account"] = float(cash_equity)
        row["portfolio_used_margin_before_account"] = float(used_margin)
        row["regime_pause_until_utc"] = (
            tracker.pause_until.isoformat()
            if tracker is not None and tracker.pause_until is not None
            else None
        )
        row["regime_recent_trades"] = float(tracker.last_metrics.recent_trades) if tracker is not None else 0.0
        row["regime_recent_win_rate_pct"] = float(tracker.last_metrics.win_rate_pct) if tracker is not None else 0.0
        row["regime_recent_net_pnl"] = float(tracker.last_metrics.net_pnl) if tracker is not None else 0.0
        row["regime_recent_consecutive_losses"] = float(tracker.last_metrics.consecutive_losses) if tracker is not None else 0.0
        if dynamic_sizing is not None and dynamic_sizing.get("ok"):
            row["size"] = float(dynamic_sizing["size"])

        if accepted:
            used_margin += estimated_margin_account
            row["portfolio_used_margin_after_open_account"] = float(used_margin)
            open_positions.append(
                {
                    "symbol": symbol,
                    "exit_time_utc": exit_time,
                    "pnl_account": pnl_account,
                    "estimated_margin_account": estimated_margin_account,
                }
            )
        else:
            row["portfolio_used_margin_after_open_account"] = float(used_margin)

        portfolio_rows.append(row)

    settle_until(pd.Timestamp.max.tz_localize("UTC"))
    portfolio_df = pd.DataFrame(portfolio_rows)
    accepted_df = portfolio_df[portfolio_df["accepted"] == True].copy()  # noqa: E712

    if accepted_df.empty:
        summary = {
            "Trades": float(len(portfolio_df)),
            "AcceptedTrades": 0.0,
            "SkippedTrades": float(len(portfolio_df)),
            "WinRate": 0.0,
            "NetPnLAccount": 0.0,
            "FinalEquityAccount": float(initial_equity),
            "ReturnPct": 0.0,
            "ProfitFactorAccount": 0.0,
            "AvgPnLAccount": 0.0,
            "AvgHoldingHours": 0.0,
            "TradesPerWeek": 0.0,
            "InitialEquityAccount": float(initial_equity),
            "TargetMarginAccount": float(target_margin_usd or config.strategy.target_margin_usd),
            "AccountCurrency": account_currency.upper(),
            "DynamicMarginFraction": float(portfolio_margin_fraction) if portfolio_margin_fraction is not None else None,
            "AppliedSpreadMultiplier": float(spread_multiplier),
            "AppliedSlippageMultiplier": float(slippage_multiplier),
            "RegimeGuardEnabled": bool(guard_settings.enabled),
            "RegimeGuardLookbackTrades": float(guard_settings.lookback_trades),
            "RegimeGuardMinClosedTrades": float(guard_settings.min_closed_trades),
            "RegimeGuardMinWinRatePct": float(guard_settings.min_win_rate_pct),
            "RegimeGuardMinNetPnL": float(guard_settings.min_net_pnl),
            "RegimeGuardMaxConsecutiveLosses": float(guard_settings.max_consecutive_losses),
            "RegimeGuardCooldownDays": float(guard_settings.cooldown_days),
            "RegimeGuardSkippedTrades": float((portfolio_df["skip_reason"] == "regime_guard_cooldown").sum()),
            "RegimeGuardTriggers": float(regime_trigger_count),
        }
        if entry_signal_cutoff_hour_utc is not None:
            summary["EntrySignalCutoffHourUTC"] = float(entry_signal_cutoff_hour_utc)
        if entry_signal_cutoff_weekdays_utc is not None:
            summary["EntrySignalCutoffWeekdaysUTC"] = ",".join(str(day) for day in sorted(entry_signal_cutoff_weekdays_utc))
        summary["GBPJPYH4EMA50TrendFilter"] = bool(gbpjpy_h4_ema50_trend_filter)
        summary["GBPJPYBreakoutBufferAtrFraction"] = float(gbpjpy_breakout_buffer_atr_fraction)
        if gbpjpy_entry_signal_cutoff_hour_utc is not None:
            summary["GBPJPYEntrySignalCutoffHourUTC"] = float(gbpjpy_entry_signal_cutoff_hour_utc)
        summary["BreakoutCloseBufferAtrFraction"] = float(breakout_close_buffer_atr_fraction)
        if account_currency.upper() == "USD":
            summary["NetPnLUSD"] = summary["NetPnLAccount"]
            summary["FinalEquityUSD"] = summary["FinalEquityAccount"]
            summary["AvgPnLUSD"] = summary["AvgPnLAccount"]
            summary["ProfitFactorUSD"] = summary["ProfitFactorAccount"]
            summary["InitialEquityUSD"] = summary["InitialEquityAccount"]
            summary["TargetMarginUSD"] = summary["TargetMarginAccount"]
        return portfolio_df, summary

    gross_profit = accepted_df.loc[accepted_df["portfolio_pnl_account"] > 0, "portfolio_pnl_account"].sum()
    gross_loss = abs(accepted_df.loc[accepted_df["portfolio_pnl_account"] < 0, "portfolio_pnl_account"].sum())
    start_time = accepted_df["fill_time_utc"].min().to_pydatetime().astimezone(dt.timezone.utc)
    end_time = accepted_df["exit_time_utc"].max().to_pydatetime().astimezone(dt.timezone.utc)
    span_days = max((end_time - start_time).total_seconds() / 86_400.0, 1e-9)

    summary = {
        "Trades": float(len(portfolio_df)),
        "AcceptedTrades": float(len(accepted_df)),
        "SkippedTrades": float(len(portfolio_df) - len(accepted_df)),
        "WinRate": float((accepted_df["portfolio_pnl_account"] > 0).mean() * 100.0),
        "NetPnLAccount": float(accepted_df["portfolio_pnl_account"].sum()),
        "FinalEquityAccount": float(initial_equity + accepted_df["portfolio_pnl_account"].sum()),
        "ReturnPct": float((accepted_df["portfolio_pnl_account"].sum() / initial_equity) * 100.0) if initial_equity > 0 else 0.0,
        "AvgPnLAccount": float(accepted_df["portfolio_pnl_account"].mean()),
        "ProfitFactorAccount": float(gross_profit / gross_loss) if gross_loss else 0.0,
        "AvgHoldingHours": float(accepted_df["holding_hours"].mean()),
        "TradesPerWeek": float((len(accepted_df) / span_days) * 7.0),
        "InitialEquityAccount": float(initial_equity),
        "TargetMarginAccount": float(target_margin_usd or config.strategy.target_margin_usd),
        "AccountCurrency": account_currency.upper(),
        "DynamicMarginFraction": float(portfolio_margin_fraction) if portfolio_margin_fraction is not None else None,
        "AppliedSpreadMultiplier": float(spread_multiplier),
        "AppliedSlippageMultiplier": float(slippage_multiplier),
        "RegimeGuardEnabled": bool(guard_settings.enabled),
        "RegimeGuardLookbackTrades": float(guard_settings.lookback_trades),
        "RegimeGuardMinClosedTrades": float(guard_settings.min_closed_trades),
        "RegimeGuardMinWinRatePct": float(guard_settings.min_win_rate_pct),
        "RegimeGuardMinNetPnL": float(guard_settings.min_net_pnl),
        "RegimeGuardMaxConsecutiveLosses": float(guard_settings.max_consecutive_losses),
        "RegimeGuardCooldownDays": float(guard_settings.cooldown_days),
        "RegimeGuardSkippedTrades": float((portfolio_df["skip_reason"] == "regime_guard_cooldown").sum()),
        "RegimeGuardTriggers": float(regime_trigger_count),
    }
    if entry_signal_cutoff_hour_utc is not None:
        summary["EntrySignalCutoffHourUTC"] = float(entry_signal_cutoff_hour_utc)
    if entry_signal_cutoff_weekdays_utc is not None:
        summary["EntrySignalCutoffWeekdaysUTC"] = ",".join(str(day) for day in sorted(entry_signal_cutoff_weekdays_utc))
    summary["GBPJPYH4EMA50TrendFilter"] = bool(gbpjpy_h4_ema50_trend_filter)
    summary["GBPJPYBreakoutBufferAtrFraction"] = float(gbpjpy_breakout_buffer_atr_fraction)
    if gbpjpy_entry_signal_cutoff_hour_utc is not None:
        summary["GBPJPYEntrySignalCutoffHourUTC"] = float(gbpjpy_entry_signal_cutoff_hour_utc)
    if max_signal_age_hours is not None:
        summary["MaxSignalAgeHours"] = float(max_signal_age_hours)
    summary["VWAPDirectionFilter"] = bool(vwap_direction_filter)
    summary["SignalRelativeVolumeThreshold"] = float(signal_relative_volume_threshold)
    summary["BreakoutCloseBufferAtrFraction"] = float(breakout_close_buffer_atr_fraction)
    if 0.0 < partial_take_profit_fraction < 1.0 and partial_take_profit_r_multiple > 0.0:
        summary["PartialTakeProfitFraction"] = float(partial_take_profit_fraction)
        summary["PartialTakeProfitRMultiple"] = float(partial_take_profit_r_multiple)
    summary["GBPJPYDisableSell"] = bool(gbpjpy_disable_sell)
    if account_currency.upper() == "USD":
        summary["NetPnLUSD"] = summary["NetPnLAccount"]
        summary["FinalEquityUSD"] = summary["FinalEquityAccount"]
        summary["AvgPnLUSD"] = summary["AvgPnLAccount"]
        summary["ProfitFactorUSD"] = summary["ProfitFactorAccount"]
        summary["InitialEquityUSD"] = summary["InitialEquityAccount"]
        summary["TargetMarginUSD"] = summary["TargetMarginAccount"]
    return portfolio_df, summary


def render_portfolio_summary(summary: dict[str, float]) -> str:
    account_currency = str(summary.get("AccountCurrency") or "USD")
    dynamic_margin_fraction = summary.get("DynamicMarginFraction")
    regime_enabled = bool(summary.get("RegimeGuardEnabled"))
    entry_signal_cutoff = summary.get("EntrySignalCutoffHourUTC")
    entry_signal_cutoff_weekdays = summary.get("EntrySignalCutoffWeekdaysUTC")
    max_signal_age_hours = summary.get("MaxSignalAgeHours")
    signal_relative_volume_threshold = summary.get("SignalRelativeVolumeThreshold")
    breakout_close_buffer_atr_fraction = summary.get("BreakoutCloseBufferAtrFraction")
    partial_take_profit_fraction = summary.get("PartialTakeProfitFraction")
    partial_take_profit_r_multiple = summary.get("PartialTakeProfitRMultiple")
    return "\n".join(
        [
            "Portfolio Backtest Summary",
            f"AccountCurrency: {account_currency}",
            (
                f"DynamicMarginFraction: {float(dynamic_margin_fraction):.4f}"
                if dynamic_margin_fraction is not None
                else "DynamicMarginFraction: off"
            ),
            f"AppliedSpreadMultiplier: {summary.get('AppliedSpreadMultiplier', 0.0):.2f}",
            f"AppliedSlippageMultiplier: {summary.get('AppliedSlippageMultiplier', 0.0):.2f}",
            (
                f"EntrySignalCutoffHourUTC: {float(entry_signal_cutoff):.0f}"
                if entry_signal_cutoff is not None
                else "EntrySignalCutoffHourUTC: off"
            ),
            (
                f"EntrySignalCutoffWeekdaysUTC: {entry_signal_cutoff_weekdays}"
                if entry_signal_cutoff_weekdays is not None
                else "EntrySignalCutoffWeekdaysUTC: all"
            ),
            f"GBPJPYH4EMA50TrendFilter: {'on' if summary.get('GBPJPYH4EMA50TrendFilter') else 'off'}",
            f"GBPJPYBreakoutBufferAtrFraction: {summary.get('GBPJPYBreakoutBufferAtrFraction', 0.0):.3f}",
            (
                f"GBPJPYEntrySignalCutoffHourUTC: {summary.get('GBPJPYEntrySignalCutoffHourUTC', 0.0):.0f}"
                if summary.get("GBPJPYEntrySignalCutoffHourUTC") is not None
                else "GBPJPYEntrySignalCutoffHourUTC: off"
            ),
            (
                f"MaxSignalAgeHours: {float(max_signal_age_hours):.2f}"
                if max_signal_age_hours is not None
                else "MaxSignalAgeHours: off"
            ),
            (
                f"SignalRelativeVolumeThreshold: {float(signal_relative_volume_threshold):.2f}"
                if signal_relative_volume_threshold not in (None, 0, 0.0)
                else "SignalRelativeVolumeThreshold: off"
            ),
            (
                f"BreakoutCloseBufferAtrFraction: {float(breakout_close_buffer_atr_fraction):.3f}"
                if breakout_close_buffer_atr_fraction not in (None, 0, 0.0)
                else "BreakoutCloseBufferAtrFraction: off"
            ),
            f"VWAPDirectionFilter: {'on' if summary.get('VWAPDirectionFilter') else 'off'}",
            (
                f"PartialTakeProfit: {float(partial_take_profit_fraction):.2f} at {float(partial_take_profit_r_multiple):.2f}R"
                if partial_take_profit_fraction is not None and partial_take_profit_r_multiple is not None
                else "PartialTakeProfit: off"
            ),
            f"GBPJPYDisableSell: {'on' if summary.get('GBPJPYDisableSell') else 'off'}",
            f"RegimeGuardEnabled: {'on' if regime_enabled else 'off'}",
            f"RegimeGuardSkippedTrades: {summary.get('RegimeGuardSkippedTrades', 0.0):.0f}",
            f"RegimeGuardTriggers: {summary.get('RegimeGuardTriggers', 0.0):.0f}",
            f"RegimeGuardLookbackTrades: {summary.get('RegimeGuardLookbackTrades', 0.0):.0f}",
            f"RegimeGuardMinClosedTrades: {summary.get('RegimeGuardMinClosedTrades', 0.0):.0f}",
            f"RegimeGuardMinWinRatePct: {summary.get('RegimeGuardMinWinRatePct', 0.0):.2f}",
            f"RegimeGuardMinNetPnL: {summary.get('RegimeGuardMinNetPnL', 0.0):.2f}",
            f"RegimeGuardMaxConsecutiveLosses: {summary.get('RegimeGuardMaxConsecutiveLosses', 0.0):.0f}",
            f"RegimeGuardCooldownDays: {summary.get('RegimeGuardCooldownDays', 0.0):.0f}",
            f"Trades: {summary['Trades']:.0f}",
            f"AcceptedTrades: {summary['AcceptedTrades']:.0f}",
            f"SkippedTrades: {summary['SkippedTrades']:.0f}",
            f"WinRate: {summary['WinRate']:.2f}%",
            f"NetPnLAccount: {summary['NetPnLAccount']:.2f}",
            f"FinalEquityAccount: {summary['FinalEquityAccount']:.2f}",
            f"ReturnPct: {summary['ReturnPct']:.2f}%",
            f"ProfitFactorAccount: {summary.get('ProfitFactorAccount', 0.0):.2f}",
            f"AvgPnLAccount: {summary['AvgPnLAccount']:.2f}",
            f"AvgHoldingHours: {summary['AvgHoldingHours']:.2f}",
            f"TradesPerWeek: {summary['TradesPerWeek']:.2f}",
            f"InitialEquityAccount: {summary['InitialEquityAccount']:.2f}",
            f"TargetMarginAccount: {summary['TargetMarginAccount']:.2f}",
        ]
    )
