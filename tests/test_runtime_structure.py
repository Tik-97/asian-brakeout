from __future__ import annotations

import datetime as dt
import importlib

import pandas as pd

import backtest
from config import StrategyConfig
import market_hours
from regime_guard import RegimeGuardTracker, regime_guard_settings_from_strategy
import runtime_state as runtime_state_module
import session_utils
import state as state_module


def test_current_session_date_respects_env_override(monkeypatch):
    monkeypatch.setenv("AB_SESSION_START_HOUR_UTC", "12")

    before_session_start = dt.datetime(2026, 4, 3, 11, 0, tzinfo=dt.timezone.utc)
    after_session_start = dt.datetime(2026, 4, 3, 12, 0, tzinfo=dt.timezone.utc)

    assert session_utils.current_session_date(before_session_start) == dt.date(2026, 4, 2)
    assert session_utils.current_session_date(after_session_start) == dt.date(2026, 4, 3)


def test_friday_trade_day_uses_pre_weekend_deadlines():
    friday = dt.date(2025, 4, 4)

    cancel_deadline = market_hours.cancel_deadline_for_trade_day(friday)
    close_deadline = market_hours.close_deadline_for_trade_day(
        friday,
        next_day_close_hour_utc=8,
        next_day_close_minute_utc=59,
    )

    assert cancel_deadline == dt.datetime(2025, 4, 4, 20, 57, tzinfo=dt.timezone.utc)
    assert close_deadline == dt.datetime(2025, 4, 4, 20, 57, tzinfo=dt.timezone.utc)


def test_state_file_respects_env_override(monkeypatch, tmp_path):
    custom_state_path = tmp_path / "nested" / "custom_state.json"
    monkeypatch.setenv("AB_STATE_FILE", str(custom_state_path))

    reloaded_state = importlib.reload(state_module)
    try:
        reloaded_state.state.clear()
        reloaded_state.state["EURUSD"] = reloaded_state.default_symbol_state()
        reloaded_state.save_state()

        assert custom_state_path.exists()
        loaded = reloaded_state.load_state()
        assert "EURUSD" in loaded
    finally:
        monkeypatch.delenv("AB_STATE_FILE", raising=False)
        importlib.reload(state_module)


def test_runtime_state_file_respects_env_override(monkeypatch, tmp_path):
    custom_runtime_state_path = tmp_path / "nested" / "custom_runtime_state.json"
    monkeypatch.setenv("AB_RUNTIME_STATE_FILE", str(custom_runtime_state_path))

    reloaded_runtime_state = importlib.reload(runtime_state_module)
    try:
        reloaded_runtime_state.save_runtime_state({"bot_enabled": False})

        assert custom_runtime_state_path.exists()
        assert reloaded_runtime_state.is_bot_enabled() is False
    finally:
        monkeypatch.delenv("AB_RUNTIME_STATE_FILE", raising=False)
        importlib.reload(runtime_state_module)


def test_portfolio_backtest_uses_account_currency_values(monkeypatch):
    trades_frame = pd.DataFrame(
        [
            {
                "symbol": "EURUSD",
                "fill_time_utc": "2026-04-01T10:00:00Z",
                "exit_time_utc": "2026-04-01T12:00:00Z",
                "estimated_margin": 50.0,
                "estimated_margin_usd": None,
                "pnl_account_currency": 25.0,
                "pnl_usd": None,
                "holding_hours": 2.0,
            }
        ]
    )

    def fake_run_symbol_backtest_in_range(*args, **kwargs):
        symbol = args[2]
        if symbol == "EURUSD":
            return trades_frame.copy(), {}
        return pd.DataFrame(), {}

    monkeypatch.setattr(backtest, "run_symbol_backtest_in_range", fake_run_symbol_backtest_in_range)

    class DummyBacktestConfig:
        candles = 1000

    class DummyStrategyConfig:
        target_margin_usd = 20.0

    class DummyConfig:
        backtest = DummyBacktestConfig()
        strategy = DummyStrategyConfig()

    portfolio_df, summary = backtest.run_portfolio_backtest(
        api=None,
        config=DummyConfig(),
        symbols=["EURUSD"],
        initial_equity=1_000.0,
        account_currency="EUR",
    )

    assert portfolio_df["accepted"].tolist() == [True]
    assert summary["AccountCurrency"] == "EUR"
    assert summary["NetPnLAccount"] == 25.0
    assert summary["FinalEquityAccount"] == 1025.0
    assert "AccountCurrency: EUR" in backtest.render_portfolio_summary(summary)


def test_portfolio_backtest_applies_dynamic_margin_fraction(monkeypatch):
    day_two_loss_per_unit = -10.0 / 110.0

    symbol_frames = {
        "NZDUSD": pd.DataFrame(
            [
                {
                    "symbol": "NZDUSD",
                    "fill_time_utc": "2026-04-01T10:00:00Z",
                    "exit_time_utc": "2026-04-01T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": 0.10,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "NZDUSD",
                    "fill_time_utc": "2026-04-02T10:00:00Z",
                    "exit_time_utc": "2026-04-02T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": day_two_loss_per_unit,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
            ]
        ),
        "GBPJPY": pd.DataFrame(
            [
                {
                    "symbol": "GBPJPY",
                    "fill_time_utc": "2026-04-01T10:00:00Z",
                    "exit_time_utc": "2026-04-01T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": 0.15,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "GBPJPY",
                    "fill_time_utc": "2026-04-02T10:00:00Z",
                    "exit_time_utc": "2026-04-02T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": day_two_loss_per_unit,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
            ]
        ),
        "EURJPY": pd.DataFrame(
            [
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-01T10:00:00Z",
                    "exit_time_utc": "2026-04-01T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": 0.15,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-02T10:00:00Z",
                    "exit_time_utc": "2026-04-02T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": day_two_loss_per_unit,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
            ]
        ),
    }

    def fake_run_symbol_backtest_in_range(*args, **kwargs):
        symbol = args[2]
        return symbol_frames[symbol].copy(), {}

    monkeypatch.setattr(backtest, "run_symbol_backtest_in_range", fake_run_symbol_backtest_in_range)

    class DummyBacktestConfig:
        candles = 1000

    class DummyStrategyConfig:
        target_margin_usd = 20.0
        symbols = {"NZDUSD": "NZDUSD", "GBPJPY": "GBPJPY", "EURJPY": "EURJPY"}

    class DummyConfig:
        backtest = DummyBacktestConfig()
        strategy = DummyStrategyConfig()

    portfolio_df, summary = backtest.run_portfolio_backtest(
        api=None,
        config=DummyConfig(),
        symbols=["NZDUSD", "GBPJPY", "EURJPY"],
        initial_equity=400.0,
        account_currency="USD",
        portfolio_margin_fraction=0.25,
    )

    first_day_margins = portfolio_df.loc[
        portfolio_df["fill_time_utc"] == pd.Timestamp("2026-04-01T10:00:00Z"),
        "estimated_margin_account",
    ].tolist()
    second_day_margins = portfolio_df.loc[
        portfolio_df["fill_time_utc"] == pd.Timestamp("2026-04-02T10:00:00Z"),
        "estimated_margin_account",
    ].tolist()

    assert first_day_margins == [100.0, 100.0, 100.0]
    assert second_day_margins == [110.0, 110.0, 110.0]
    assert round(summary["FinalEquityAccount"], 2) == 410.0
    assert "DynamicMarginFraction: 0.2500" in backtest.render_portfolio_summary(summary)


def test_trade_friction_points_uses_current_spread_proxy():
    market_info = {
        "snapshot": {
            "bid": 1.2345,
            "offer": 1.2350,
        }
    }

    spread_points, slippage_per_side, total_friction = backtest.trade_friction_points(
        market_info,
        spread_multiplier=1.0,
        slippage_multiplier=0.25,
    )

    assert round(spread_points, 6) == 0.0005
    assert round(slippage_per_side, 6) == 0.000125
    assert round(total_friction, 6) == 0.00075


def test_resolve_time_exit_uses_last_pre_deadline_close():
    history = pd.DataFrame(
        [
            {"time": pd.Timestamp("2025-04-04T17:00:00Z"), "open": 189.90, "close": 189.70},
            {"time": pd.Timestamp("2025-04-04T18:00:00Z"), "open": 189.70, "close": 189.10},
            {"time": pd.Timestamp("2025-04-04T19:00:00Z"), "open": 189.10, "close": 188.80},
            {"time": pd.Timestamp("2025-04-04T20:00:00Z"), "open": 188.80, "close": 188.55},
            {"time": pd.Timestamp("2025-04-06T21:00:00Z"), "open": 187.25, "close": 187.00},
        ]
    )

    exit_price, exit_time = backtest.resolve_time_exit(
        history,
        fill_time=dt.datetime(2025, 4, 4, 17, 0, tzinfo=dt.timezone.utc),
        deadline=dt.datetime(2025, 4, 4, 20, 57, tzinfo=dt.timezone.utc),
    )

    assert exit_price == 188.55
    assert exit_time == dt.datetime(2025, 4, 4, 20, 57, tzinfo=dt.timezone.utc)


def test_regime_guard_tracker_pauses_after_bad_window():
    strategy = StrategyConfig(
        symbols={"EURJPY": "EURJPY"},
        regime_guard_enabled=True,
        regime_guard_lookback_trades=6,
        regime_guard_min_closed_trades=5,
        regime_guard_min_win_rate_pct=34.0,
        regime_guard_min_net_pnl=0.0,
        regime_guard_max_consecutive_losses=3,
        regime_guard_cooldown_days=15,
    )
    settings = regime_guard_settings_from_strategy(strategy)
    tracker = RegimeGuardTracker(settings)
    start_time = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)

    outcomes = [20.0, 15.0, -5.0, -10.0, -15.0, -20.0]
    triggers = []
    for index, pnl in enumerate(outcomes):
        triggers.append(tracker.record_trade(start_time + dt.timedelta(days=index), pnl))

    assert triggers[-1] is True
    assert tracker.last_metrics.recent_trades == 6
    assert round(tracker.last_metrics.win_rate_pct, 2) == 33.33
    assert tracker.last_metrics.net_pnl == -15.0
    assert tracker.last_metrics.consecutive_losses == 4
    assert tracker.pause_until == start_time + dt.timedelta(days=20)
    assert tracker.is_blocked(start_time + dt.timedelta(days=10)) is True
    assert tracker.is_blocked(start_time + dt.timedelta(days=21)) is False


def test_portfolio_backtest_applies_regime_guard_cooldown(monkeypatch):
    symbol_frames = {
        "EURJPY": pd.DataFrame(
            [
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-01T10:00:00Z",
                    "exit_time_utc": "2026-04-01T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": 0.20,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-02T10:00:00Z",
                    "exit_time_utc": "2026-04-02T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": 0.20,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-03T10:00:00Z",
                    "exit_time_utc": "2026-04-03T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": -0.30,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-04T10:00:00Z",
                    "exit_time_utc": "2026-04-04T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": -0.30,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-05T10:00:00Z",
                    "exit_time_utc": "2026-04-05T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": -0.30,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-06T10:00:00Z",
                    "exit_time_utc": "2026-04-06T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": -0.30,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
                {
                    "symbol": "EURJPY",
                    "fill_time_utc": "2026-04-07T10:00:00Z",
                    "exit_time_utc": "2026-04-07T12:00:00Z",
                    "holding_hours": 2.0,
                    "margin_per_unit_account": 1.0,
                    "pnl_account_per_unit": 0.50,
                    "min_size": 0.01,
                    "size_step": 0.01,
                },
            ]
        )
    }

    def fake_run_symbol_backtest_in_range(*args, **kwargs):
        symbol = args[2]
        return symbol_frames[symbol].copy(), {}

    monkeypatch.setattr(backtest, "run_symbol_backtest_in_range", fake_run_symbol_backtest_in_range)

    class DummyBacktestConfig:
        candles = 1000

    class DummyStrategyConfig:
        target_margin_usd = 20.0
        symbols = {"EURJPY": "EURJPY"}
        regime_guard_enabled = True
        regime_guard_lookback_trades = 6
        regime_guard_min_closed_trades = 5
        regime_guard_min_win_rate_pct = 34.0
        regime_guard_min_net_pnl = 0.0
        regime_guard_max_consecutive_losses = 3
        regime_guard_cooldown_days = 15

    class DummyConfig:
        backtest = DummyBacktestConfig()
        strategy = DummyStrategyConfig()

    portfolio_df, summary = backtest.run_portfolio_backtest(
        api=None,
        config=DummyConfig(),
        symbols=["EURJPY"],
        initial_equity=400.0,
        account_currency="USD",
        portfolio_margin_fraction=0.25,
    )

    assert portfolio_df["accepted"].tolist() == [True, True, True, True, True, True, False]
    assert portfolio_df.iloc[-1]["skip_reason"] == "regime_guard_cooldown"
    assert summary["RegimeGuardEnabled"] is True
    assert summary["RegimeGuardSkippedTrades"] == 1.0
    assert summary["RegimeGuardTriggers"] == 1.0
    assert "RegimeGuardEnabled: on" in backtest.render_portfolio_summary(summary)
