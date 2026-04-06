from __future__ import annotations

import datetime as dt
import json
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any

from capital_api import CapitalAPI
from config import AppConfig
from data_utils import get_asian_range, parse_candles
from market_hours import cancel_deadline_for_trade_day, close_deadline_for_trade_day
from regime_guard import regime_guard_settings_from_strategy, regime_guard_state_updates
from runtime_state import is_bot_enabled
from session_utils import current_session_date, parse_utc_timestamp, trade_day_from_runtime_fields
from sizing_live import choose_size_for_target_margin_live
from state import init_symbols, load_state, record_closed_trade, state, update_symbol
from strategy import (
    StrategyParameters,
    atr_filter,
    build_relative_signal_volume_frame,
    calculate_levels,
    check_breakout,
    passes_relative_signal_volume_filter,
)
from telegram_bot import TelegramNotifier
from trade_history import sync_closed_trades, sync_closed_trades_archive


def normalize_currency_code(value: Any) -> str:
    letters = "".join(ch for ch in str(value or "").upper() if ch.isalpha())
    return letters[:3] if len(letters) >= 3 else letters


def trade_day_from_symbol_state(symbol_state: dict[str, Any], session_start_hour_utc: int) -> dt.date | None:
    return trade_day_from_runtime_fields(
        active_trade_day_utc=symbol_state.get("active_trade_day_utc"),
        position_opened_at=symbol_state.get("position_opened_at"),
        working_order_created_at=symbol_state.get("working_order_created_at"),
        session_start_hour_utc=session_start_hour_utc,
    )


def count_decimals_from_number(value: float) -> int:
    text = str(value)
    if "." not in text:
        return 0
    return len(text.split(".")[1].rstrip("0"))


def get_price_decimals(market_info: dict[str, Any], default: int = 5) -> int:
    for key in ("decimalPlacesFactor", "priceDecimals", "decimals"):
        value = market_info.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    snapshot = market_info.get("snapshot", {})
    if isinstance(snapshot, dict):
        for key in ("decimalPlacesFactor", "priceDecimals", "decimals"):
            value = snapshot.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        for key in ("bid", "offer", "high", "low"):
            value = snapshot.get(key)
            if isinstance(value, (int, float)):
                return count_decimals_from_number(float(value))
    return default


def quantize_price(value: float | None, decimals: int) -> float | None:
    if value is None:
        return None
    pattern = "1" if decimals == 0 else "1." + ("0" * decimals)
    return float(Decimal(str(value)).quantize(Decimal(pattern), rounding=ROUND_DOWN))


def normalize_price(value: float | None, market_info: dict[str, Any], default_decimals: int = 5) -> float | None:
    return quantize_price(value, get_price_decimals(market_info, default=default_decimals))


def mid_price(market_info: dict[str, Any]) -> float | None:
    snapshot = market_info.get("snapshot", {}) if isinstance(market_info, dict) else {}
    bid = snapshot.get("bid")
    offer = snapshot.get("offer")
    if isinstance(bid, (int, float)) and isinstance(offer, (int, float)):
        return (bid + offer) / 2
    if isinstance(offer, (int, float)):
        return float(offer)
    if isinstance(bid, (int, float)):
        return float(bid)
    return None


def choose_working_order_type(direction: str, entry_price: float, market_info: dict[str, Any]) -> str:
    snapshot = market_info.get("snapshot", {})
    bid = snapshot.get("bid")
    offer = snapshot.get("offer")
    if direction == "BUY":
        current_price = offer if isinstance(offer, (int, float)) else bid
        return "STOP" if isinstance(current_price, (int, float)) and current_price < entry_price else "LIMIT"
    current_price = bid if isinstance(bid, (int, float)) else offer
    return "STOP" if isinstance(current_price, (int, float)) and current_price > entry_price else "LIMIT"


def pick_account_payload(info: dict[str, Any]) -> dict[str, Any]:
    accounts = info.get("accounts", [])
    if isinstance(accounts, list) and accounts:
        preferred = next((acc for acc in accounts if acc.get("preferred")), None)
        return preferred or accounts[0]
    return info


def account_metrics(info: dict[str, Any]) -> dict[str, float | None]:
    account = pick_account_payload(info) if isinstance(info, dict) else {}
    balance_block = account.get("balance", {}) if isinstance(account, dict) else {}
    account_info = account.get("accountInfo", {}) if isinstance(account, dict) else {}

    def first_number(*values):
        for value in values:
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    balance = first_number(
        balance_block.get("balance"),
        account_info.get("balance"),
        account.get("balance"),
        account.get("funds"),
    )
    available = first_number(
        balance_block.get("available"),
        account_info.get("available"),
        account.get("available"),
    )
    margin = first_number(
        balance_block.get("margin"),
        balance_block.get("usedMargin"),
        account_info.get("margin"),
        account.get("margin"),
    )
    if margin is None and balance is not None and available is not None:
        margin = round(balance - available, 2)
    return {"balance": balance, "available": available, "margin": margin}


class AsianBreakoutBot:
    def __init__(self, config: AppConfig, api: CapitalAPI, telegram: TelegramNotifier) -> None:
        self.config = config
        self.api = api
        self.telegram = telegram
        self.notification_cooldowns: dict[str, float] = {}
        self.last_trade_sync_at = 0.0
        self.last_archive_sync_at = 0.0
        self.last_entry_check_key: tuple[dt.date, int, int] | None = None
        init_symbols(self.config.strategy.symbols.keys())
        load_state()

    @property
    def strategy_params(self) -> StrategyParameters:
        return StrategyParameters(
            atr_period=self.config.strategy.atr_period,
            atr_filter_pct=self.config.strategy.atr_filter_pct,
            tp_multiplier=self.config.strategy.tp_multiplier,
        )

    def send(self, message: str) -> None:
        self.telegram.send(message)

    def send_dedup(self, key: str, message: str, ttl_seconds: int = 3600) -> bool:
        now = time.time()
        if now - self.notification_cooldowns.get(key, 0) < ttl_seconds:
            return False
        self.notification_cooldowns[key] = now
        self.send(message)
        return True

    def append_order_audit(
        self,
        symbol: str,
        *,
        event: str,
        source: str = "live",
        signal: str | None = None,
        entry: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        size: float | None = None,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        payload = {
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "symbol": symbol,
            "event": event,
            "source": source,
            "signal": signal,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "size": size,
            "error": str(error) if error else None,
        }
        if isinstance(result, dict):
            payload.update(
                {
                    "deal_reference": result.get("dealReference"),
                    "deal_id": result.get("dealId") or result.get("confirmDealId"),
                    "status": result.get("status"),
                    "reason": result.get("reason"),
                }
            )
            if isinstance(result.get("confirm"), dict):
                payload["confirm"] = {
                    "dealId": result["confirm"].get("dealId"),
                    "status": result["confirm"].get("status"),
                    "reason": result["confirm"].get("reason"),
                    "level": result["confirm"].get("level"),
                }
        self.config.runtime.order_audit_file.parent.mkdir(parents=True, exist_ok=True)
        with self.config.runtime.order_audit_file.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def get_account_currency(self) -> str:
        info = self.api.get_account_info()
        account = pick_account_payload(info)
        return normalize_currency_code(account.get("currency")) or "USD"

    def get_margin_to_account_rate(self, margin_currency: str | None, account_currency: str) -> float:
        margin_ccy = normalize_currency_code(margin_currency)
        account_ccy = normalize_currency_code(account_currency)
        if not margin_ccy or not account_ccy or margin_ccy == account_ccy:
            return 1.0

        direct_symbol = f"{margin_ccy}{account_ccy}"
        inverse_symbol = f"{account_ccy}{margin_ccy}"

        for candidate, invert in ((direct_symbol, False), (inverse_symbol, True)):
            try:
                info = self.api.get_market_details(candidate)
                price = mid_price(info)
                if price and price > 0:
                    return (1.0 / price) if invert else price
            except Exception:  # noqa: BLE001
                continue
        return 1.0

    def ensure_session_state(self, now_utc: dt.datetime) -> None:
        session_date = current_session_date(now_utc, self.config.strategy.session_start_hour_utc)
        for symbol, epic in self.config.strategy.symbols.items():
            symbol_state = state.get(symbol, {})
            active_trade_day = trade_day_from_symbol_state(symbol_state, self.config.strategy.session_start_hour_utc)
            if symbol_state.get("session_date") != str(session_date):
                update_symbol(
                    symbol,
                    session_date=str(session_date),
                    asian_high=None,
                    asian_low=None,
                    trade_taken_today=bool(symbol_state.get("daily_trades")) or active_trade_day == session_date,
                    last_processed_signal_candle=None,
                    last_breakout_detected_at=None,
                    last_breakout_side=None,
                    last_entry_candidate=None,
                    last_stop_loss=None,
                    last_take_profit=None,
                    last_relative_volume=None,
                    last_block_reason=None,
                )
                symbol_state = state.get(symbol, {})

            if now_utc.hour < self.config.strategy.session_start_hour_utc:
                continue
            if symbol_state.get("asian_high") is not None and symbol_state.get("asian_low") is not None:
                continue

            df = parse_candles(self.api.get_candles(epic, resolution="HOUR", max_candles=self.config.strategy.history_candles))
            if df.empty:
                continue
            asian_high, asian_low = get_asian_range(df, session_date)
            if asian_high is None or asian_low is None:
                continue
            update_symbol(symbol, asian_high=asian_high, asian_low=asian_low, session_date=str(session_date))

    def sync_closed_history(self, force: bool = False) -> None:
        now = time.time()
        if force or now - self.last_trade_sync_at >= 120:
            sync_closed_trades(self.api, self.config.strategy.symbols, last_period=86400)
            self.last_trade_sync_at = now
        if force or now - self.last_archive_sync_at >= 1800:
            sync_closed_trades_archive(self.api, self.config.strategy.symbols, days_back=7)
            self.last_archive_sync_at = now

    def sync_live_broker_state(self, now_utc: dt.datetime) -> None:
        self.sync_closed_history()
        for symbol, epic in self.config.strategy.symbols.items():
            symbol_state = state.get(symbol, {})
            live_position = self.api.find_open_position_by_epic(epic)
            live_order = self.api.find_working_order_by_epic(epic)

            if live_position:
                update_symbol(
                    symbol,
                    open_deal_id=live_position.get("dealId"),
                    position_opened_at=symbol_state.get("position_opened_at") or now_utc.isoformat(),
                    pending_direction=live_position.get("direction"),
                    trade_taken_today=True,
                    active_trade_day_utc=symbol_state.get("active_trade_day_utc") or str(current_session_date(now_utc, self.config.strategy.session_start_hour_utc)),
                )
            elif symbol_state.get("open_deal_id"):
                update_symbol(symbol, open_deal_id=None, position_opened_at=None)

            if live_order:
                update_symbol(
                    symbol,
                    working_order_id=live_order.get("dealId"),
                    pending_direction=live_order.get("direction"),
                    pending_entry=live_order.get("level"),
                    working_order_created_at=symbol_state.get("working_order_created_at") or now_utc.isoformat(),
                    trade_taken_today=True,
                    active_trade_day_utc=symbol_state.get("active_trade_day_utc") or str(current_session_date(now_utc, self.config.strategy.session_start_hour_utc)),
                )
            elif symbol_state.get("working_order_id"):
                update_symbol(
                    symbol,
                    working_order_id=None,
                    pending_entry=None,
                    working_order_created_at=None,
                    pending_direction=symbol_state.get("pending_direction") if symbol_state.get("open_deal_id") else None,
                )

    def refresh_regime_guards(self, now_utc: dt.datetime) -> None:
        settings = regime_guard_settings_from_strategy(self.config.strategy)
        for symbol in self.config.strategy.symbols:
            symbol_state = state.get(symbol, {})
            updates, triggered = regime_guard_state_updates(
                symbol_state,
                settings,
                now_utc=now_utc,
            )
            if any(symbol_state.get(key) != value for key, value in updates.items()):
                update_symbol(symbol, **updates)
                symbol_state = state.get(symbol, {})

            if not triggered:
                continue

            pause_until = updates.get("regime_pause_until_utc")
            self.send_dedup(
                f"regime_pause:{symbol}:{pause_until}",
                (
                    f"<b>{symbol} REGIME PAUSE</b>\n"
                    f"Recent trades: <code>{updates.get('regime_recent_trades')}</code>\n"
                    f"Win rate: <code>{updates.get('regime_recent_win_rate_pct')}%</code>\n"
                    f"Net PnL: <code>{updates.get('regime_recent_net_pnl')}</code>\n"
                    f"Consecutive losses: <code>{updates.get('regime_recent_consecutive_losses')}</code>\n"
                    f"Pause until: <code>{pause_until}</code>"
                ),
                ttl_seconds=86400,
            )

    def sync_filled_positions(self) -> None:
        for symbol, epic in self.config.strategy.symbols.items():
            symbol_state = state.get(symbol, {})
            if not symbol_state.get("working_order_id") or symbol_state.get("open_deal_id"):
                continue
            direction = symbol_state.get("pending_direction")
            if not direction:
                continue
            position = self.api.find_real_open_position(epic=epic, direction=direction, wait_seconds=1)
            if not position:
                continue
            update_symbol(
                symbol,
                open_deal_id=position.get("dealId"),
                working_order_id=None,
                position_opened_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                trade_taken_today=True,
            )
            self.send_dedup(
                f"filled:{symbol}:{position['dealId']}",
                (
                    f"<b>{symbol} ORDER FILLED</b>\n"
                    f"Direction: <b>{position.get('direction')}</b>\n"
                    f"Size: <code>{position.get('size')}</code>\n"
                    f"DealId: <code>{position.get('dealId')}</code>"
                ),
                ttl_seconds=12 * 3600,
            )

    def get_position_pnl(self, epic: str) -> float | None:
        position = self.api.find_open_position_by_epic(epic)
        if not position:
            return None
        market = position.get("raw", {}).get("market", {})
        try:
            if market.get("profitLoss") is not None:
                return float(market.get("profitLoss"))
        except (TypeError, ValueError):
            return None
        return None

    def enforce_time_boundaries(self, now_utc: dt.datetime) -> None:
        for symbol, epic in self.config.strategy.symbols.items():
            symbol_state = state.get(symbol, {})

            working_order_id = symbol_state.get("working_order_id")
            order_trade_day = trade_day_from_symbol_state(symbol_state, self.config.strategy.session_start_hour_utc)
            if working_order_id and order_trade_day and now_utc >= cancel_deadline_for_trade_day(
                order_trade_day,
                weekend_close_hour_utc=self.config.strategy.weekend_close_hour_utc,
                weekend_close_minute_utc=self.config.strategy.weekend_close_minute_utc,
            ):
                if order_trade_day.weekday() == 4:
                    cancel_reason = "Friday pre-weekend rule"
                else:
                    cancel_reason = "UTC day expired"
                try:
                    self.api.cancel_working_order(working_order_id)
                except Exception:  # noqa: BLE001
                    pass
                update_symbol(
                    symbol,
                    working_order_id=None,
                    pending_entry=None,
                    working_order_created_at=None,
                    pending_direction=symbol_state.get("pending_direction") if symbol_state.get("open_deal_id") else None,
                )
                self.send_dedup(
                    f"cancel:{symbol}:{working_order_id}:{order_trade_day}",
                    (
                        f"<b>{symbol} ORDER CANCELED</b>\n"
                        f"Reason: <b>{cancel_reason}</b>\n"
                        f"OrderId: <code>{working_order_id}</code>"
                    ),
                    ttl_seconds=86400,
                )

            symbol_state = state.get(symbol, {})
            deal_id = symbol_state.get("open_deal_id")
            position_trade_day = trade_day_from_symbol_state(symbol_state, self.config.strategy.session_start_hour_utc)
            if deal_id and position_trade_day and now_utc >= close_deadline_for_trade_day(
                position_trade_day,
                next_day_close_hour_utc=self.config.strategy.position_force_close_hour_utc,
                next_day_close_minute_utc=self.config.strategy.position_force_close_minute_utc,
                weekend_close_hour_utc=self.config.strategy.weekend_close_hour_utc,
                weekend_close_minute_utc=self.config.strategy.weekend_close_minute_utc,
            ):
                if position_trade_day.weekday() == 4:
                    close_reason = "Friday pre-weekend rule"
                else:
                    close_reason = "08:59 UTC next-day rule"
                pnl = self.get_position_pnl(epic)
                result = self.api.close_position(deal_id)
                record_closed_trade(
                    symbol,
                    deal_id=deal_id,
                    closed_at=now_utc.isoformat(),
                    pnl=pnl,
                    source="bot_close",
                    direction=symbol_state.get("pending_direction") or symbol_state.get("last_trade_direction"),
                    entry_at=symbol_state.get("position_opened_at"),
                    trade_day_utc=symbol_state.get("active_trade_day_utc"),
                )
                update_symbol(symbol, open_deal_id=None, position_opened_at=None)
                self.send_dedup(
                    f"force_close:{symbol}:{deal_id}:{position_trade_day}",
                    (
                        f"<b>{symbol} FORCE CLOSED</b>\n"
                        f"Reason: <b>{close_reason}</b>\n"
                        f"DealId: <code>{deal_id}</code>\n"
                        f"Status: <code>{result.get('status')}</code>"
                    ),
                    ttl_seconds=86400,
                )

    def check_entries(self, source: str = "live") -> None:
        now_utc = dt.datetime.now(dt.timezone.utc)
        account_info = self.api.get_account_info()
        account_prefs = self.api.get_account_preferences()
        account_ccy = self.get_account_currency()
        metrics = account_metrics(account_info)
        balance = metrics.get("balance")
        if balance is None or balance <= 0:
            return
        dynamic_target_margin = float(balance * self.config.strategy.portfolio_margin_fraction)
        if dynamic_target_margin <= 0:
            return

        for symbol, epic in self.config.strategy.symbols.items():
            try:
                symbol_state = state.get(symbol, {})
                if symbol_state.get("trade_taken_today"):
                    continue
                if symbol_state.get("working_order_id") or symbol_state.get("open_deal_id"):
                    continue
                pause_until = parse_utc_timestamp(symbol_state.get("regime_pause_until_utc"))
                if pause_until is not None and now_utc < pause_until:
                    continue
                asian_high = symbol_state.get("asian_high")
                asian_low = symbol_state.get("asian_low")
                if asian_high is None or asian_low is None:
                    continue

                df = parse_candles(self.api.get_candles(epic, resolution="HOUR", max_candles=self.config.strategy.history_candles))
                if df.empty or len(df) < self.config.strategy.atr_period + 5:
                    continue
                relative_volume_frame = (
                    build_relative_signal_volume_frame(df)
                    if self.config.strategy.signal_relative_volume_threshold > 0
                    else None
                )

                signal, candle_time = check_breakout(df, asian_high, asian_low)
                if not signal:
                    continue
                candle_key = candle_time.isoformat() if hasattr(candle_time, "isoformat") else str(candle_time)
                if symbol_state.get("last_processed_signal_candle") == candle_key:
                    continue

                entry = asian_high if signal == "BUY" else asian_low
                atr_value = atr_filter(df, entry, self.strategy_params)
                if atr_value is None:
                    update_symbol(
                        symbol,
                        last_processed_signal_candle=candle_key,
                        last_breakout_detected_at=candle_key,
                        last_breakout_side=signal,
                        last_entry_candidate=entry,
                        last_stop_loss=None,
                        last_take_profit=None,
                        last_relative_volume=None,
                        last_block_reason="ATR filter blocked entry",
                    )
                    continue

                stop_loss, take_profit = calculate_levels(entry, atr_value, signal, self.strategy_params)
                relative_volume_value = None
                if relative_volume_frame is not None:
                    relative_volume_subset = relative_volume_frame[relative_volume_frame["time"] == candle_time]
                    if not relative_volume_subset.empty:
                        raw_relative_volume = relative_volume_subset.iloc[-1]["rel_volume"]
                        if raw_relative_volume is not None:
                            relative_volume_value = float(raw_relative_volume)
                    if not passes_relative_signal_volume_filter(
                        signal_time=candle_time,
                        min_relative_volume=self.config.strategy.signal_relative_volume_threshold,
                        relative_volume_frame=relative_volume_frame,
                    ):
                        threshold = self.config.strategy.signal_relative_volume_threshold
                        reason = (
                            f"Relative volume {relative_volume_value:.2f} below {threshold:.2f}"
                            if relative_volume_value is not None
                            else f"Relative volume unavailable below {threshold:.2f}"
                        )
                        update_symbol(
                            symbol,
                            last_processed_signal_candle=candle_key,
                            last_breakout_detected_at=candle_key,
                            last_breakout_side=signal,
                            last_entry_candidate=entry,
                            last_stop_loss=stop_loss,
                            last_take_profit=take_profit,
                            last_relative_volume=relative_volume_value,
                            last_block_reason=reason,
                        )
                        continue

                market_info = self.api.get_market_details(epic)
                margin_currency = market_info.get("instrument", {}).get("currency")
                margin_to_account_rate = self.get_margin_to_account_rate(margin_currency, account_ccy)
                size_info = choose_size_for_target_margin_live(
                    entry_price=entry,
                    market_info=market_info,
                    account_preferences=account_prefs,
                    target_margin=dynamic_target_margin,
                    leverage_overrides=self.config.strategy.target_leverage_by_type,
                    margin_to_account_rate=margin_to_account_rate,
                )
                if not size_info.get("ok"):
                    update_symbol(
                        symbol,
                        last_processed_signal_candle=candle_key,
                        last_breakout_detected_at=candle_key,
                        last_breakout_side=signal,
                        last_entry_candidate=entry,
                        last_stop_loss=stop_loss,
                        last_take_profit=take_profit,
                        last_relative_volume=relative_volume_value,
                        last_block_reason=f"Size calc failed: {size_info.get('reason')}",
                    )
                    self.send_dedup(
                        f"size_fail:{symbol}:{candle_key}",
                        (
                            f"<b>{symbol} SIZE CALC FAILED</b>\n"
                            f"Entry: <code>{entry:.5f}</code>\n"
                            f"Reason: <code>{size_info.get('reason')}</code>"
                        ),
                        ttl_seconds=6 * 3600,
                    )
                    continue

                entry = normalize_price(entry, market_info) or entry
                stop_loss = normalize_price(stop_loss, market_info) or stop_loss
                take_profit = normalize_price(take_profit, market_info) or take_profit
                size = float(size_info["size"])
                order_type = choose_working_order_type(signal, entry, market_info)

                result = self.api.place_working_order(
                    symbol=epic,
                    direction=signal,
                    price=entry,
                    sl=stop_loss,
                    tp=take_profit,
                    size=size,
                    order_type=order_type,
                )
                self.append_order_audit(
                    symbol,
                    event="working_order_submit",
                    source=source,
                    signal=signal,
                    entry=entry,
                    sl=stop_loss,
                    tp=take_profit,
                    size=size,
                    result=result,
                )
                working_order_id = result.get("dealId")
                if not working_order_id:
                    update_symbol(
                        symbol,
                        last_processed_signal_candle=candle_key,
                        last_breakout_detected_at=candle_key,
                        last_breakout_side=signal,
                        last_entry_candidate=entry,
                        last_stop_loss=stop_loss,
                        last_take_profit=take_profit,
                        last_relative_volume=relative_volume_value,
                        last_block_reason=f"Order not confirmed: {result.get('reason') or result.get('status')}",
                    )
                    self.send_dedup(
                        f"submit_fail:{symbol}:{candle_key}",
                        (
                            f"<b>{symbol} ORDER NOT CONFIRMED</b>\n"
                            f"Direction: <b>{signal}</b>\n"
                            f"Entry: <code>{entry:.5f}</code>\n"
                            f"Status: <code>{result.get('status')}</code>\n"
                            f"Reason: <code>{result.get('reason')}</code>"
                        ),
                        ttl_seconds=6 * 3600,
                    )
                    continue

                update_symbol(
                    symbol,
                    trade_taken_today=True,
                    working_order_id=working_order_id,
                    open_deal_id=None,
                    pending_direction=signal,
                    pending_entry=entry,
                    working_order_created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                    position_opened_at=None,
                    active_trade_day_utc=str(current_session_date(dt.datetime.now(dt.timezone.utc), self.config.strategy.session_start_hour_utc)),
                    last_trade_direction=signal,
                    last_processed_signal_candle=candle_key,
                    last_breakout_detected_at=candle_key,
                    last_breakout_side=signal,
                    last_entry_candidate=entry,
                    last_stop_loss=stop_loss,
                    last_take_profit=take_profit,
                    last_relative_volume=relative_volume_value,
                    last_block_reason=None,
                )
                self.send_dedup(
                    f"submitted:{symbol}:{candle_key}",
                    (
                        f"<b>{symbol} {order_type} ORDER SUBMITTED</b>\n"
                        f"Direction: <b>{signal}</b>\n"
                        f"Entry: <code>{entry:.5f}</code>\n"
                        f"SL: <code>{stop_loss:.5f}</code>\n"
                        f"TP: <code>{take_profit:.5f}</code>\n"
                        f"Size: <code>{size:.4f}</code>"
                    ),
                    ttl_seconds=6 * 3600,
                )
            except Exception as error:  # noqa: BLE001
                self.append_order_audit(symbol, event="working_order_exception", source=source, error=error)
                self.send_dedup(
                    f"entry_error:{symbol}:{type(error).__name__}:{str(error)}",
                    f"<b>{symbol}</b>\nEntry error:\n<code>{str(error)}</code>",
                    ttl_seconds=1800,
                )

    def run(self) -> None:
        self.api.session_manager.login()
        self.sync_closed_history(force=True)
        startup_now = dt.datetime.now(dt.timezone.utc)
        self.ensure_session_state(startup_now)
        self.sync_live_broker_state(startup_now)
        self.refresh_regime_guards(startup_now)
        self.send("<b>BOT STARTED</b>\nAsian Breakout backend bot active.")

        while True:
            now = dt.datetime.now(dt.timezone.utc)
            try:
                self.ensure_session_state(now)
                self.sync_live_broker_state(now)
                self.enforce_time_boundaries(now)
                self.refresh_regime_guards(now)
                if (
                    is_bot_enabled()
                    and self.config.strategy.entry_start_hour_utc <= now.hour <= self.config.strategy.entry_end_hour_utc
                ):
                    minute_in_window = (
                        self.config.strategy.entry_check_start_minute_utc
                        <= now.minute
                        <= self.config.strategy.entry_check_end_minute_utc
                    )
                    check_key = (now.date(), now.hour, now.minute)
                    if minute_in_window and self.last_entry_check_key != check_key:
                        self.check_entries(source="live")
                        self.last_entry_check_key = check_key
                self.sync_filled_positions()
            except Exception as error:  # noqa: BLE001
                self.send(f"<b>MAIN LOOP ERROR</b>\n<code>{str(error)}</code>")
            time.sleep(self.config.strategy.loop_interval_seconds)
