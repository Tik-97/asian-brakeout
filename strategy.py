from __future__ import annotations

from dataclasses import dataclass

import datetime as dt

import pandas as pd

from data_utils import calculate_atr


@dataclass(slots=True)
class StrategyParameters:
    atr_period: int
    atr_filter_pct: float
    tp_multiplier: float


def check_breakout(df, asian_high: float, asian_low: float):
    """Use only the previous fully closed H1 candle for the breakout signal."""
    signal_candle = df.iloc[-2]
    close_price = float(signal_candle["close"])
    candle_time = signal_candle["time"]

    if close_price >= asian_high:
        return "BUY", candle_time
    if close_price <= asian_low:
        return "SELL", candle_time
    return None, candle_time


def atr_filter(df, entry: float, params: StrategyParameters) -> float | None:
    atr_value = calculate_atr(df, params.atr_period)
    atr_percent = atr_value / entry * 100.0
    if atr_percent >= params.atr_filter_pct:
        return atr_value
    return None


def calculate_levels(entry: float, atr_value: float, direction: str, params: StrategyParameters) -> tuple[float, float]:
    if direction == "BUY":
        return entry - atr_value, entry + atr_value * params.tp_multiplier
    return entry + atr_value, entry - atr_value * params.tp_multiplier


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
