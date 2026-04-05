from __future__ import annotations

from dataclasses import dataclass

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
