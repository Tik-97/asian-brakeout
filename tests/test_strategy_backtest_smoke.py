from __future__ import annotations

import datetime as dt

import pandas as pd

from backtest import summarize_trade_frame
from strategy import StrategyParameters, atr_filter, calculate_levels, check_breakout


def test_check_breakout_buy_signal_uses_previous_closed_candle():
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(
                [
                    "2026-04-01T08:00:00Z",
                    "2026-04-01T09:00:00Z",
                    "2026-04-01T10:00:00Z",
                ],
                utc=True,
            ),
            "open": [1.0, 1.01, 1.02],
            "high": [1.01, 1.03, 1.04],
            "low": [0.99, 1.0, 1.01],
            "close": [1.0, 1.06, 1.05],
        }
    )
    signal, candle_time = check_breakout(frame, asian_high=1.05, asian_low=0.95)
    assert signal == "BUY"
    assert candle_time == frame.iloc[-2]["time"]


def test_atr_filter_and_levels_return_expected_values():
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2026-04-01", periods=20, freq="h", tz="UTC"),
            "open": [1.0 + i * 0.001 for i in range(20)],
            "high": [1.01 + i * 0.001 for i in range(20)],
            "low": [0.99 + i * 0.001 for i in range(20)],
            "close": [1.005 + i * 0.001 for i in range(20)],
        }
    )
    params = StrategyParameters(atr_period=14, atr_filter_pct=0.1, tp_multiplier=2.0)
    atr_value = atr_filter(frame, entry=1.02, params=params)
    assert atr_value is not None
    stop_loss, take_profit = calculate_levels(1.02, atr_value, "BUY", params)
    assert stop_loss < 1.02 < take_profit


def test_summarize_trade_frame_uses_r_multiples():
    trades = pd.DataFrame(
        [
            {"r_multiple": 2.0, "holding_hours": 4.0},
            {"r_multiple": -1.0, "holding_hours": 6.0},
            {"r_multiple": 1.5, "holding_hours": 2.0},
        ]
    )
    summary = summarize_trade_frame(
        trades,
        start_time=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        end_time=dt.datetime(2026, 1, 15, tzinfo=dt.timezone.utc),
    )
    assert summary["Trades"] == 3.0
    assert round(summary["WinRate"], 2) == 66.67
    assert round(summary["NetR"], 2) == 2.5
