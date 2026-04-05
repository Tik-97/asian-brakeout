import json
from datetime import datetime, timezone

from app_paths import ensure_parent_dir, resolve_runtime_path
from session_utils import (
    current_session_date,
    parse_utc_day,
    parse_utc_timestamp,
    trade_day_from_runtime_fields,
)

STATE_FILE = resolve_runtime_path("AB_STATE_FILE", "state.json")
state = {}


def default_symbol_state():
    return {
        "session_date": None,
        "asian_high": None,
        "asian_low": None,
        "trade_taken_today": False,
        "working_order_id": None,
        "open_deal_id": None,
        "pending_direction": None,
        "pending_entry": None,
        "working_order_created_at": None,
        "position_opened_at": None,
        "active_trade_day_utc": None,
        "last_processed_signal_candle": None,
        "last_closed_pnl": None,
        "last_closed_at": None,
        "last_closed_deal_id": None,
        "last_trade_result": None,
        "last_trade_direction": None,
        "last_breakout_detected_at": None,
        "last_breakout_side": None,
        "last_entry_candidate": None,
        "last_stop_loss": None,
        "last_take_profit": None,
        "last_relative_volume": None,
        "last_block_reason": None,
        "daily_trades": [],
        "all_trades": [],
        "desk_badge": None,
        "desk_badge_note": None,
        "enabled": True,
        "regime_pause_until_utc": None,
        "regime_last_trigger_trade_id": None,
        "regime_last_trigger_closed_at": None,
        "regime_recent_trades": None,
        "regime_recent_win_rate_pct": None,
        "regime_recent_net_pnl": None,
        "regime_recent_consecutive_losses": None,
    }


def _sorted_trades(trades):
    safe_trades = [trade for trade in trades if isinstance(trade, dict)]
    safe_trades.sort(key=lambda trade: trade.get("closed_at") or "")
    return safe_trades


def save_state():
    state_path = ensure_parent_dir(STATE_FILE)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_state():
    if not STATE_FILE.exists():
        state.clear()
        save_state()
        return state

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        loaded = {}

    state.clear()
    if isinstance(loaded, dict):
        state.update(loaded)

    normalize_state(save=False)

    return state


def init_symbols(symbol_names):
    load_state()

    changed = False

    for name in symbol_names:
        if name not in state:
            state[name] = default_symbol_state()
            changed = True
        else:
            defaults = default_symbol_state()
            for k, v in defaults.items():
                if k not in state[name]:
                    state[name][k] = v
                    changed = True
            if "enabled" not in state[name]:
                state[name]["enabled"] = True
                changed = True

    if changed:
        save_state()


def update_symbol(symbol_name, **kwargs):
    if symbol_name not in state:
        state[symbol_name] = default_symbol_state()

    state[symbol_name].update(kwargs)
    save_state()


def normalize_symbol_state(symbol_state, current_session=None):
    defaults = default_symbol_state()
    for key, value in defaults.items():
        if key not in symbol_state:
            symbol_state[key] = value

    current_session = current_session or _current_session_date()
    current_session_str = str(current_session)

    all_trades = symbol_state.get("all_trades")
    if not isinstance(all_trades, list):
        all_trades = []
    all_trades = _sorted_trades(all_trades)

    daily_trades = symbol_state.get("daily_trades")
    if not isinstance(daily_trades, list):
        daily_trades = []

    normalized_daily = []
    for trade in daily_trades:
        if _trade_day_for_trade(trade) == current_session:
            normalized_daily.append(trade)

    # Rebuild the current UTC-day journal from all known trades. The owning
    # day is the UTC entry day of the trade, not the UTC exit day.
    for trade in all_trades:
        if _trade_day_for_trade(trade) == current_session:
            if not any(existing.get("deal_id") == trade.get("deal_id") for existing in normalized_daily):
                normalized_daily.append(dict(trade))

    normalized_daily = _sorted_trades(normalized_daily)

    latest_daily = normalized_daily[-1] if normalized_daily else None
    active_trade_day = _active_trade_day_for_symbol(symbol_state)
    has_session_activity = bool(normalized_daily or active_trade_day == current_session)

    symbol_state["session_date"] = current_session_str
    symbol_state["daily_trades"] = normalized_daily
    symbol_state["all_trades"] = all_trades
    symbol_state["trade_taken_today"] = has_session_activity

    if latest_daily:
        symbol_state["last_closed_pnl"] = latest_daily.get("pnl")
        symbol_state["last_closed_at"] = latest_daily.get("closed_at")
        symbol_state["last_closed_deal_id"] = latest_daily.get("deal_id")
        symbol_state["last_trade_result"] = latest_daily.get("result")
        symbol_state["last_trade_direction"] = latest_daily.get("direction") or symbol_state.get("last_trade_direction")
    elif not symbol_state.get("open_deal_id") and not symbol_state.get("working_order_id"):
        symbol_state["last_closed_pnl"] = None
        symbol_state["last_closed_at"] = None
        symbol_state["last_closed_deal_id"] = None
        symbol_state["last_trade_result"] = None


def normalize_state(save=True):
    current_session = _current_session_date()
    changed = False

    for symbol_name, symbol_state in list(state.items()):
        if not isinstance(symbol_state, dict):
            state[symbol_name] = default_symbol_state()
            changed = True
            continue

        before = json.dumps(symbol_state, sort_keys=True, default=str)
        normalize_symbol_state(symbol_state, current_session=current_session)
        after = json.dumps(symbol_state, sort_keys=True, default=str)
        if before != after:
            changed = True

    if changed and save:
        save_state()

    return state


def _current_session_date(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    return current_session_date(now_utc)


def _parse_closed_at_utc(value):
    return parse_utc_timestamp(value)


def _parse_trade_day(value):
    return parse_utc_day(value)


def _session_date_for_timestamp(closed_at):
    parsed = _parse_closed_at_utc(closed_at)
    if parsed is None:
        return None
    return current_session_date(parsed)


def _active_trade_day_for_symbol(symbol_state):
    return trade_day_from_runtime_fields(
        active_trade_day_utc=symbol_state.get("active_trade_day_utc"),
        position_opened_at=symbol_state.get("position_opened_at"),
        working_order_created_at=symbol_state.get("working_order_created_at"),
    )


def _trade_day_for_trade(trade):
    if not isinstance(trade, dict):
        return None

    trade_day = _parse_trade_day(trade.get("trade_day_utc"))
    if trade_day is not None:
        return trade_day

    entry_at = _parse_closed_at_utc(trade.get("entry_at"))
    if entry_at is not None:
        return _session_date_for_timestamp(entry_at)

    return _session_date_for_timestamp(trade.get("closed_at"))


def record_closed_trade(symbol_name, *, deal_id, closed_at, pnl, source="broker_history", direction=None, entry_at=None, trade_day_utc=None):
    if symbol_name not in state:
        state[symbol_name] = default_symbol_state()

    symbol_state = state[symbol_name]
    current_session = _current_session_date()
    existing_trade = next(
        (
            trade for trade in symbol_state.get("all_trades", [])
            if isinstance(trade, dict) and trade.get("deal_id") == deal_id
        ),
        None,
    )
    resolved_entry_at = entry_at or (existing_trade or {}).get("entry_at") or symbol_state.get("position_opened_at")
    resolved_trade_day = (
        _parse_trade_day(trade_day_utc)
        or _trade_day_for_trade(existing_trade)
        or _session_date_for_timestamp(resolved_entry_at)
        or _active_trade_day_for_symbol(symbol_state)
        or _session_date_for_timestamp(closed_at)
    )
    trade_session = resolved_trade_day
    belongs_to_current_session = trade_session == current_session

    daily_trades = symbol_state.get("daily_trades")
    if not isinstance(daily_trades, list):
        daily_trades = []
    all_trades = symbol_state.get("all_trades")
    if not isinstance(all_trades, list):
        all_trades = []

    existing = next((trade for trade in daily_trades if trade.get("deal_id") == deal_id), None)
    existing_all = next((trade for trade in all_trades if trade.get("deal_id") == deal_id), None)
    trade_result = None
    if pnl is not None:
        trade_result = "win" if pnl >= 0 else "loss"

    trade_payload = {
        "deal_id": deal_id,
        "entry_at": resolved_entry_at,
        "trade_day_utc": str(resolved_trade_day) if resolved_trade_day else None,
        "closed_at": closed_at,
        "pnl": pnl,
        "result": trade_result,
        "source": source,
        "direction": direction,
    }

    if belongs_to_current_session:
        if existing is None:
            daily_trades.append(trade_payload)
        else:
            existing.update(trade_payload)
    elif existing is not None:
        daily_trades = [trade for trade in daily_trades if trade.get("deal_id") != deal_id]

    if existing_all is None:
        all_trades.append(dict(trade_payload))
    else:
        existing_all.update(trade_payload)

    daily_trades = _sorted_trades(daily_trades)
    all_trades = _sorted_trades(all_trades)

    symbol_state["daily_trades"] = daily_trades
    symbol_state["all_trades"] = all_trades
    symbol_state["trade_taken_today"] = bool(daily_trades)

    if belongs_to_current_session:
        symbol_state["last_closed_pnl"] = pnl
        symbol_state["last_closed_at"] = closed_at
        symbol_state["last_closed_deal_id"] = deal_id
        symbol_state["last_trade_result"] = trade_result
        symbol_state["last_trade_direction"] = direction
    elif not daily_trades:
        symbol_state["last_closed_pnl"] = None
        symbol_state["last_closed_at"] = None
        symbol_state["last_closed_deal_id"] = None
        symbol_state["last_trade_result"] = None
        symbol_state["last_trade_direction"] = None

    normalize_symbol_state(symbol_state, current_session=current_session)
    save_state()
