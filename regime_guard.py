from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from session_utils import parse_utc_timestamp


@dataclass(slots=True)
class RegimeGuardSettings:
    enabled: bool = False
    lookback_trades: int = 6
    min_closed_trades: int = 5
    min_win_rate_pct: float = 34.0
    min_net_pnl: float = 0.0
    max_consecutive_losses: int = 3
    cooldown_days: int = 15


@dataclass(slots=True)
class RegimeGuardMetrics:
    recent_trades: int
    win_rate_pct: float
    net_pnl: float
    consecutive_losses: int


def compute_regime_guard_metrics(
    pnl_values: list[float],
    settings: RegimeGuardSettings,
) -> RegimeGuardMetrics:
    recent = pnl_values[-settings.lookback_trades:] if settings.lookback_trades > 0 else list(pnl_values)
    if not recent:
        return RegimeGuardMetrics(
            recent_trades=0,
            win_rate_pct=0.0,
            net_pnl=0.0,
            consecutive_losses=0,
        )

    wins = sum(1 for pnl in recent if pnl > 0)
    consecutive_losses = 0
    for pnl in reversed(recent):
        if pnl <= 0:
            consecutive_losses += 1
        else:
            break

    return RegimeGuardMetrics(
        recent_trades=len(recent),
        win_rate_pct=(wins / len(recent)) * 100.0,
        net_pnl=float(sum(recent)),
        consecutive_losses=consecutive_losses,
    )


def should_trigger_regime_pause(
    metrics: RegimeGuardMetrics,
    settings: RegimeGuardSettings,
) -> bool:
    if not settings.enabled:
        return False
    if metrics.recent_trades < settings.min_closed_trades:
        return False
    return (
        metrics.win_rate_pct < settings.min_win_rate_pct
        and metrics.net_pnl <= settings.min_net_pnl
        and metrics.consecutive_losses >= settings.max_consecutive_losses
    )


class RegimeGuardTracker:
    def __init__(self, settings: RegimeGuardSettings) -> None:
        self.settings = settings
        self.pnl_values: list[float] = []
        self.pause_until: dt.datetime | None = None
        self.last_metrics = RegimeGuardMetrics(0, 0.0, 0.0, 0)

    def is_blocked(self, at_time: dt.datetime) -> bool:
        return (
            self.settings.enabled
            and self.pause_until is not None
            and at_time < self.pause_until
        )

    def record_trade(self, exit_time: dt.datetime, pnl: float) -> bool:
        self.pnl_values.append(float(pnl))
        self.last_metrics = compute_regime_guard_metrics(self.pnl_values, self.settings)
        if should_trigger_regime_pause(self.last_metrics, self.settings):
            self.pause_until = exit_time + dt.timedelta(days=self.settings.cooldown_days)
            return True
        return False


def regime_guard_settings_from_strategy(strategy_config: Any) -> RegimeGuardSettings:
    return RegimeGuardSettings(
        enabled=bool(getattr(strategy_config, "regime_guard_enabled", False)),
        lookback_trades=int(getattr(strategy_config, "regime_guard_lookback_trades", 6)),
        min_closed_trades=int(getattr(strategy_config, "regime_guard_min_closed_trades", 5)),
        min_win_rate_pct=float(getattr(strategy_config, "regime_guard_min_win_rate_pct", 34.0)),
        min_net_pnl=float(getattr(strategy_config, "regime_guard_min_net_pnl", 0.0)),
        max_consecutive_losses=int(getattr(strategy_config, "regime_guard_max_consecutive_losses", 3)),
        cooldown_days=int(getattr(strategy_config, "regime_guard_cooldown_days", 15)),
    )


def _collect_closed_trade_rows(symbol_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in symbol_state.get("all_trades", []):
        if not isinstance(trade, dict):
            continue
        exit_time = parse_utc_timestamp(trade.get("closed_at"))
        pnl = trade.get("pnl")
        if exit_time is None:
            continue
        try:
            pnl_value = float(pnl)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "deal_id": trade.get("deal_id"),
                "closed_at": exit_time,
                "pnl": pnl_value,
            }
        )
    rows.sort(key=lambda row: row["closed_at"])
    return rows


def regime_guard_state_updates(
    symbol_state: dict[str, Any],
    settings: RegimeGuardSettings,
    *,
    now_utc: dt.datetime,
) -> tuple[dict[str, Any], bool]:
    if not settings.enabled:
        updates = {
            "regime_pause_until_utc": None,
            "regime_last_trigger_trade_id": None,
            "regime_last_trigger_closed_at": None,
            "regime_recent_trades": None,
            "regime_recent_win_rate_pct": None,
            "regime_recent_net_pnl": None,
            "regime_recent_consecutive_losses": None,
        }
        return updates, False

    closed_rows = _collect_closed_trade_rows(symbol_state)
    if not closed_rows:
        updates = {
            "regime_pause_until_utc": None,
            "regime_recent_trades": 0,
            "regime_recent_win_rate_pct": 0.0,
            "regime_recent_net_pnl": 0.0,
            "regime_recent_consecutive_losses": 0,
        }
        return updates, False

    latest_trade = closed_rows[-1]
    metrics = compute_regime_guard_metrics(
        [row["pnl"] for row in closed_rows],
        settings,
    )
    current_pause_until = parse_utc_timestamp(symbol_state.get("regime_pause_until_utc"))
    last_trigger_trade_id = symbol_state.get("regime_last_trigger_trade_id")
    triggered = False

    if (
        should_trigger_regime_pause(metrics, settings)
        and latest_trade.get("deal_id") != last_trigger_trade_id
    ):
        current_pause_until = latest_trade["closed_at"] + dt.timedelta(days=settings.cooldown_days)
        triggered = current_pause_until > now_utc

    if current_pause_until is not None and now_utc >= current_pause_until:
        current_pause_until = None

    updates = {
        "regime_pause_until_utc": current_pause_until.isoformat() if current_pause_until is not None else None,
        "regime_last_trigger_trade_id": (
            latest_trade.get("deal_id")
            if should_trigger_regime_pause(metrics, settings)
            else symbol_state.get("regime_last_trigger_trade_id")
        ),
        "regime_last_trigger_closed_at": (
            latest_trade["closed_at"].isoformat()
            if should_trigger_regime_pause(metrics, settings)
            else symbol_state.get("regime_last_trigger_closed_at")
        ),
        "regime_recent_trades": metrics.recent_trades,
        "regime_recent_win_rate_pct": round(metrics.win_rate_pct, 2),
        "regime_recent_net_pnl": round(metrics.net_pnl, 2),
        "regime_recent_consecutive_losses": metrics.consecutive_losses,
    }
    return updates, triggered
