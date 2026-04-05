from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

from auth import CapitalSessionManager
from capital_api import CapitalAPI
from config import AppConfig, load_config
from live_bot import account_metrics, normalize_currency_code
from runtime_state import is_bot_enabled
from state import load_state


LIVE_DASHBOARD_FILE = Path("dashboard/public/data/live_dashboard.json")
MANUAL_WITHDRAWALS_FILE = Path("dashboard/manual_withdrawals.json")


def normalize_symbol(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def fmt_timestamp(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(dt.timezone.utc).isoformat()


def round2(value: float | None) -> float:
    return round(float(value or 0.0), 2)


def dashboard_initial_deposit_override() -> float | None:
    raw_value = os.getenv("AB_DASHBOARD_INITIAL_DEPOSIT_USD")
    if raw_value is None or not str(raw_value).strip():
        return None
    try:
        return round2(float(raw_value))
    except (TypeError, ValueError):
        return None


def dashboard_reset_at_utc() -> dt.datetime | None:
    return parse_timestamp(os.getenv("AB_DASHBOARD_RESET_AT_UTC"))


def load_manual_withdrawals(reset_at_utc: dt.datetime | None = None) -> list[dict[str, Any]]:
    if not MANUAL_WITHDRAWALS_FILE.exists():
        return []
    try:
        payload = json.loads(MANUAL_WITHDRAWALS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        time_utc = parse_timestamp(item.get("time_utc") or item.get("time"))
        if reset_at_utc and time_utc and time_utc < reset_at_utc:
            continue
        try:
            amount = round2(float(item.get("withdrawal_amount") or 0.0))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        rows.append(
            {
                "time_utc": fmt_timestamp(time_utc),
                "symbol": normalize_symbol(item.get("symbol")) or "ACCOUNT",
                "withdrawal_kind": str(item.get("withdrawal_kind") or "manual"),
                "withdrawal_amount": amount,
                "trading_equity_after_withdrawal": round2(
                    float(item.get("trading_equity_after_withdrawal") or 0.0)
                )
                if item.get("trading_equity_after_withdrawal") is not None
                else "",
            }
        )
    rows.sort(key=lambda row: row.get("time_utc") or "")
    return rows


def parse_trade_pnl(tx: dict[str, Any]) -> float:
    for key in ("profitAndLoss", "profitLoss", "amount", "size"):
        value = tx.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def load_state_trade_index() -> dict[str, dict[str, Any]]:
    current_state = load_state()
    trade_index: dict[str, dict[str, Any]] = {}
    for symbol, symbol_state in current_state.items():
        all_trades = symbol_state.get("all_trades", [])
        if not isinstance(all_trades, list):
            continue
        for trade in all_trades:
            if not isinstance(trade, dict):
                continue
            deal_id = str(trade.get("deal_id") or "").strip()
            if not deal_id:
                continue
            merged = dict(trade)
            merged["symbol"] = symbol
            trade_index[deal_id] = merged
    return trade_index


def safe_get(mapping: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = mapping or {}
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def current_open_pnl(account_info: dict[str, Any], positions: list[dict[str, Any]]) -> float:
    account = safe_get(account_info, "accounts", 0) or {}
    try:
        balance_profit_loss = float(safe_get(account, "balance", "profitLoss") or 0.0)
    except (TypeError, ValueError):
        balance_profit_loss = 0.0

    if balance_profit_loss:
        return round2(balance_profit_loss)

    pnl = 0.0
    for position in positions:
        try:
            pnl += float(safe_get(position, "position", "upl") or safe_get(position, "market", "profitLoss") or 0.0)
        except (TypeError, ValueError):
            continue
    return round2(pnl)


def build_trade_rows(
    transactions: list[dict[str, Any]],
    *,
    current_balance: float | None,
    state_trade_index: dict[str, dict[str, Any]],
    reset_at_utc: dt.datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []

    for tx in transactions:
        if tx.get("transactionType") != "TRADE":
            continue
        if "closed" not in str(tx.get("note") or "").lower():
            continue

        deal_id = str(tx.get("dealId") or tx.get("reference") or "").strip()
        state_trade = state_trade_index.get(deal_id, {})
        symbol = normalize_symbol(state_trade.get("symbol") or tx.get("instrumentName") or tx.get("epic"))
        if not symbol:
            continue

        closed_at = parse_timestamp(tx.get("dateUtc") or tx.get("date"))
        if reset_at_utc and closed_at and closed_at < reset_at_utc:
            continue
        pnl = parse_trade_pnl(tx)
        direction = str(state_trade.get("direction") or "").upper()
        exit_reason = str(state_trade.get("result") or "trade_closed")
        fill_time = parse_timestamp(state_trade.get("entry_at")) or closed_at

        rows.append(
            {
                "symbol": symbol,
                "side": direction,
                "fill_time_utc": fmt_timestamp(fill_time),
                "exit_time_utc": fmt_timestamp(closed_at),
                "exit_reason": exit_reason,
                "portfolio_pnl_account": round2(pnl),
                "accepted": "True",
                "deal_id": deal_id,
            }
        )

    rows.sort(key=lambda row: row.get("exit_time_utc") or row.get("fill_time_utc") or "")

    total_pnl = sum(float(row["portfolio_pnl_account"]) for row in rows)
    baseline = round2((current_balance or 0.0) - total_pnl)
    running_balance = baseline
    events: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        running_balance += float(row["portfolio_pnl_account"])
        event_time = row.get("exit_time_utc") or row.get("fill_time_utc") or ""
        events.append(
            {
                "time": event_time,
                "event_type": "trade_close",
                "symbol": row["symbol"],
                "trading_equity": round2(running_balance),
                "total_value": round2(running_balance),
                "withdrawal_amount": 0.0,
                "event_index": index,
            }
        )

    return rows, events


def compute_profit_factor(trades: list[dict[str, Any]]) -> float:
    wins = sum(float(row["portfolio_pnl_account"]) for row in trades if float(row["portfolio_pnl_account"]) >= 0)
    losses = abs(sum(float(row["portfolio_pnl_account"]) for row in trades if float(row["portfolio_pnl_account"]) < 0))
    if losses == 0:
        return 0.0
    return round(wins / losses, 2)


def compute_max_drawdown(events: list[dict[str, Any]]) -> float:
    peak = None
    worst = 0.0
    for event in events:
        value = float(event.get("total_value") or 0.0)
        if peak is None or value > peak:
            peak = value
        if peak and peak > 0:
            worst = min(worst, ((value - peak) / peak) * 100.0)
    return round(worst, 2)


def build_summary(
    account_info: dict[str, Any],
    trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    open_pnl: float,
    initial_deposit_override: float | None = None,
    total_withdrawn: float = 0.0,
) -> dict[str, Any]:
    metrics = account_metrics(account_info)
    balance = float(metrics.get("balance") or 0.0)
    available = float(metrics.get("available") or 0.0)
    margin = float(metrics.get("margin") or max(balance - available, 0.0))
    total_pnl = sum(float(row["portfolio_pnl_account"]) for row in trades)
    initial_deposit = round2(initial_deposit_override if initial_deposit_override is not None else (balance - total_pnl))
    ending_total_value = round2(balance + open_pnl + total_withdrawn)
    wins = [row for row in trades if float(row["portfolio_pnl_account"]) >= 0]
    losses = [row for row in trades if float(row["portfolio_pnl_account"]) < 0]

    return {
        "AccountCurrency": normalize_currency_code(safe_get(account_info, "accounts", 0, "currency")) or "USD",
        "InitialDepositUSD": initial_deposit,
        "PriceModel": "Live Capital.com account snapshot",
        "NetPnLUSD": round2(total_pnl),
        "TotalWithdrawnUSD": round2(total_withdrawn),
        "FinalTradingEquityUSD": round2(balance),
        "EndingTotalValueUSD": ending_total_value,
        "ReturnPctOnInitial": round2(((ending_total_value - initial_deposit) / initial_deposit) * 100.0) if initial_deposit else 0.0,
        "AcceptedTrades": len(trades),
        "WinRatePct": round2((len(wins) / len(trades)) * 100.0) if trades else 0.0,
        "ProfitFactor": compute_profit_factor(trades),
        "MaxDrawdownTotalValuePct": compute_max_drawdown(events),
        "TotalOvernightFundingUSD": 0.0,
    }


def build_trade_history_payload(
    api: CapitalAPI,
    *,
    days_back: int,
    current_balance: float | None,
    state_trade_index: dict[str, dict[str, Any]],
    reset_at_utc: dt.datetime | None = None,
) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    from_date = (now - dt.timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")
    to_date = now.strftime("%Y-%m-%dT%H:%M:%S")
    transactions = api.get_transactions(from_date=from_date, to_date=to_date)
    trade_rows, events = build_trade_rows(
        transactions,
        current_balance=current_balance,
        state_trade_index=state_trade_index,
        reset_at_utc=reset_at_utc,
    )
    wins = [row for row in trade_rows if float(row["portfolio_pnl_account"]) >= 0]
    losses = [row for row in trade_rows if float(row["portfolio_pnl_account"]) < 0]
    return {
        "trades": trade_rows,
        "wins": wins,
        "losses": losses,
        "events": events,
        "withdrawals": [],
    }


def build_live_pairs(
    config: AppConfig,
    *,
    account_info: dict[str, Any],
    positions: list[dict[str, Any]],
    working_orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_state = load_state()
    positions_by_symbol = {
        normalize_symbol(safe_get(item, "market", "epic")): item for item in positions if normalize_symbol(safe_get(item, "market", "epic"))
    }
    orders_by_symbol = {
        normalize_symbol(item.get("epic") or safe_get(item, "marketData", "epic")): item
        for item in working_orders
        if normalize_symbol(item.get("epic") or safe_get(item, "marketData", "epic"))
    }

    symbols = sorted(set(config.strategy.symbols.keys()) | set(positions_by_symbol.keys()) | set(orders_by_symbol.keys()))
    now = dt.datetime.now(dt.timezone.utc)
    bot_enabled = is_bot_enabled()
    pairs: list[dict[str, Any]] = []

    for symbol in symbols:
        symbol_state = current_state.get(symbol, {})
        position = positions_by_symbol.get(symbol)
        order = orders_by_symbol.get(symbol)
        daily_trades = symbol_state.get("daily_trades", []) if isinstance(symbol_state.get("daily_trades"), list) else []
        latest_today_trade = daily_trades[-1] if daily_trades else None
        pause_until = parse_timestamp(symbol_state.get("regime_pause_until_utc"))

        position_open = bool(position)
        pending_order = bool(order)
        open_pnl = 0.0
        if position_open:
            try:
                open_pnl = float(safe_get(position, "market", "profitLoss") or 0.0)
            except (TypeError, ValueError):
                open_pnl = 0.0

        block_reason = None
        if symbol in config.strategy.symbols:
            if not bot_enabled:
                block_reason = "Bot disabled"
            elif pause_until and pause_until > now:
                block_reason = f"Regime guard pause until {pause_until.isoformat()}"
            elif symbol_state.get("last_block_reason"):
                block_reason = str(symbol_state.get("last_block_reason"))

        pairs.append(
            {
                "symbol": symbol,
                "asian_high": symbol_state.get("asian_high"),
                "asian_low": symbol_state.get("asian_low"),
                "has_pending_order": pending_order,
                "has_open_position": position_open,
                "open_pnl": round2(open_pnl),
                "breakout_detected": bool(
                    position_open
                    or pending_order
                    or latest_today_trade
                    or symbol_state.get("last_breakout_detected_at")
                ),
                "breakout_side": (
                    safe_get(position, "position", "direction")
                    or (order.get("direction") if isinstance(order, dict) else None)
                )
                or symbol_state.get("pending_direction")
                or symbol_state.get("last_breakout_side")
                or symbol_state.get("last_trade_direction"),
                "entry": (
                    safe_get(position, "position", "level")
                    or safe_get(order, "level")
                    or symbol_state.get("pending_entry")
                    or symbol_state.get("last_entry_candidate")
                ),
                "stop_loss": (
                    safe_get(position, "position", "stopLevel")
                    or safe_get(order, "stopLevel")
                    or symbol_state.get("last_stop_loss")
                ),
                "take_profit": (
                    safe_get(position, "position", "profitLevel")
                    or safe_get(position, "position", "limitLevel")
                    or safe_get(order, "profitLevel")
                    or symbol_state.get("last_take_profit")
                ),
                "fill_price": safe_get(position, "position", "level"),
                "block_reason": block_reason,
                "position_status": (
                    "open" if position_open else "pending" if pending_order else "closed_today" if latest_today_trade else "idle"
                ),
                "latest_trade_result": latest_today_trade.get("result") if isinstance(latest_today_trade, dict) else None,
                "latest_trade_pnl": latest_today_trade.get("pnl") if isinstance(latest_today_trade, dict) else None,
                "latest_trade_closed_at": latest_today_trade.get("closed_at") if isinstance(latest_today_trade, dict) else None,
            }
        )

    return pairs


def build_live_dashboard(
    config: AppConfig,
    api: CapitalAPI,
    *,
    days_back: int = 365,
    history_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api.session_manager.login()
    account_info = api.get_account_info()
    positions = api.get_open_positions()
    working_orders = api.get_working_orders()
    metrics = account_metrics(account_info)
    state_trade_index = load_state_trade_index()
    reset_at_utc = dashboard_reset_at_utc()
    initial_deposit_override = dashboard_initial_deposit_override()
    manual_withdrawals = load_manual_withdrawals(reset_at_utc)
    total_withdrawn = sum(float(item.get("withdrawal_amount") or 0.0) for item in manual_withdrawals)
    history = history_payload or build_trade_history_payload(
        api,
        days_back=days_back,
        current_balance=metrics.get("balance"),
        state_trade_index=state_trade_index,
        reset_at_utc=reset_at_utc,
    )
    open_pnl = current_open_pnl(account_info, positions)
    summary = build_summary(
        account_info,
        history["trades"],
        history["events"],
        open_pnl=open_pnl,
        initial_deposit_override=initial_deposit_override,
        total_withdrawn=total_withdrawn,
    )
    now = dt.datetime.now(dt.timezone.utc)
    live_status = {
        "updated_at_utc": now.isoformat(),
        "account": {
            "balance": round2(metrics.get("balance")),
            "available": round2(metrics.get("available")),
            "margin": round2(metrics.get("margin")),
            "currency": summary["AccountCurrency"],
            "open_positions": len(positions),
            "working_orders": len(working_orders),
            "open_pnl": open_pnl,
        },
        "pairs": build_live_pairs(
            config,
            account_info=account_info,
            positions=positions,
            working_orders=working_orders,
        ),
    }
    return {
        "summary": summary,
        "trades": history["trades"],
        "wins": history["wins"],
        "losses": history["losses"],
        "events": history["events"],
        "withdrawals": manual_withdrawals,
        "liveStatus": live_status,
    }


def write_live_dashboard(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(output_path)


def run_once(env_file: str, *, days_back: int, output_path: Path) -> None:
    config = load_config(env_file)
    session_manager = CapitalSessionManager(config.capital)
    api = CapitalAPI(session_manager)
    payload = build_live_dashboard(config, api, days_back=days_back)
    write_live_dashboard(payload, output_path)
    print(f"Wrote live dashboard snapshot to {output_path}")


def run_watch(env_file: str, *, days_back: int, interval_seconds: int, output_path: Path) -> None:
    config = load_config(env_file)
    session_manager = CapitalSessionManager(config.capital)
    api = CapitalAPI(session_manager)
    last_history_refresh = 0.0
    cached_history_payload: dict[str, Any] | None = None

    while True:
        try:
            now = time.time()
            if cached_history_payload is None or now - last_history_refresh >= max(interval_seconds * 3, 120):
                api.session_manager.login()
                info = api.get_account_info()
                metrics = account_metrics(info)
                cached_history_payload = build_trade_history_payload(
                    api,
                    days_back=days_back,
                    current_balance=metrics.get("balance"),
                    state_trade_index=load_state_trade_index(),
                    reset_at_utc=dashboard_reset_at_utc(),
                )
                last_history_refresh = now

            payload = build_live_dashboard(
                config,
                api,
                days_back=days_back,
                history_payload=cached_history_payload,
            )

            write_live_dashboard(payload, output_path)
            print(f"[{dt.datetime.now().isoformat()}] Live dashboard snapshot updated")
        except Exception as error:  # noqa: BLE001
            print(f"[{dt.datetime.now().isoformat()}] live dashboard bridge error: {error}")
        time.sleep(interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export live Capital.com account data for the dashboard")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--interval-seconds", type=int, default=20)
    parser.add_argument("--output", default=str(LIVE_DASHBOARD_FILE))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("once")
    subparsers.add_parser("watch")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    if args.command == "once":
        run_once(args.env_file, days_back=args.days_back, output_path=output_path)
        return
    if args.command == "watch":
        run_watch(
            args.env_file,
            days_back=args.days_back,
            interval_seconds=args.interval_seconds,
            output_path=output_path,
        )


if __name__ == "__main__":
    main()
