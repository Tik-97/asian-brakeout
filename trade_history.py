from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from capital_api import CapitalAPI
from session_utils import current_session_date
from state import load_state, record_closed_trade


@dataclass(slots=True)
class StrategyStats:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    profit_factor: float
    long_count: int
    short_count: int
    by_symbol: dict[str, dict[str, float | int]]


def normalize_symbol_name(raw_value: str | None, symbols: dict[str, str]) -> str | None:
    if not raw_value:
        return None
    compact = str(raw_value).replace("/", "").replace(" ", "").upper()
    if compact in symbols:
        return compact
    epic_map = {str(epic).upper(): symbol for symbol, epic in symbols.items()}
    return epic_map.get(compact)


def parse_trade_timestamp(value: str | None) -> dt.datetime | None:
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
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def parse_transaction_pnl(tx: dict[str, Any]) -> float | None:
    for key in ("profitAndLoss", "profitLoss", "amount", "size"):
        value = tx.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_transaction_direction(tx: dict[str, Any]) -> str | None:
    for key in ("direction", "dealDirection", "side"):
        direction = str(tx.get(key) or "").upper()
        if direction in {"BUY", "SELL"}:
            return direction
    note = str(tx.get("note") or "").upper()
    if "SHORT" in note or "SELL" in note:
        return "SELL"
    if "LONG" in note or "BUY" in note:
        return "BUY"
    return None


def session_day_for_timestamp(timestamp: dt.datetime, session_start_hour_utc: int = 9) -> dt.date:
    return current_session_date(timestamp, session_start_hour_utc)


def sync_closed_trades(
    api: CapitalAPI,
    symbols: dict[str, str],
    *,
    last_period: int = 86400,
) -> int:
    synced = 0
    current_state = load_state()
    for tx in api.get_transactions(last_period=last_period):
        if tx.get("transactionType") != "TRADE":
            continue
        if "closed" not in str(tx.get("note", "")).lower():
            continue
        symbol = normalize_symbol_name(tx.get("instrumentName"), symbols)
        if symbol is None:
            symbol = normalize_symbol_name(tx.get("epic"), symbols)
        if symbol is None:
            continue
        symbol_state = current_state.get(symbol, {})
        direction = (
            parse_transaction_direction(tx)
            or symbol_state.get("pending_direction")
            or symbol_state.get("last_trade_direction")
        )
        record_closed_trade(
            symbol,
            deal_id=tx.get("dealId") or tx.get("reference"),
            closed_at=tx.get("dateUtc") or tx.get("date"),
            pnl=parse_transaction_pnl(tx),
            source="capital_history",
            direction=direction,
        )
        synced += 1
    return synced


def sync_closed_trades_archive(
    api: CapitalAPI,
    symbols: dict[str, str],
    *,
    days_back: int = 7,
) -> int:
    synced = 0
    utc_now = dt.datetime.now(dt.timezone.utc)
    for day_offset in range(days_back):
        day_start = (utc_now - dt.timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = min(day_start + dt.timedelta(days=1) - dt.timedelta(seconds=1), utc_now)
        synced += sync_transactions_window(
            api,
            symbols,
            from_date=day_start.strftime("%Y-%m-%dT%H:%M:%S"),
            to_date=day_end.strftime("%Y-%m-%dT%H:%M:%S"),
        )
    return synced


def sync_transactions_window(
    api: CapitalAPI,
    symbols: dict[str, str],
    *,
    from_date: str,
    to_date: str,
) -> int:
    synced = 0
    current_state = load_state()
    for tx in api.get_transactions(from_date=from_date, to_date=to_date):
        if tx.get("transactionType") != "TRADE":
            continue
        if "closed" not in str(tx.get("note", "")).lower():
            continue
        symbol = normalize_symbol_name(tx.get("instrumentName"), symbols)
        if symbol is None:
            symbol = normalize_symbol_name(tx.get("epic"), symbols)
        if symbol is None:
            continue
        symbol_state = current_state.get(symbol, {})
        direction = (
            parse_transaction_direction(tx)
            or symbol_state.get("pending_direction")
            or symbol_state.get("last_trade_direction")
        )
        record_closed_trade(
            symbol,
            deal_id=tx.get("dealId") or tx.get("reference"),
            closed_at=tx.get("dateUtc") or tx.get("date"),
            pnl=parse_transaction_pnl(tx),
            source="capital_history",
            direction=direction,
        )
        synced += 1
    return synced


def collect_all_trades() -> list[dict[str, Any]]:
    current_state = load_state()
    trades: list[dict[str, Any]] = []
    for symbol, info in current_state.items():
        symbol_trades = info.get("all_trades", [])
        if not isinstance(symbol_trades, list):
            continue
        for trade in symbol_trades:
            if not isinstance(trade, dict):
                continue
            row = dict(trade)
            row["symbol"] = symbol
            trades.append(row)
    trades.sort(key=lambda trade: (trade.get("closed_at") or "", trade.get("symbol") or ""))
    return trades


def compute_stats() -> StrategyStats:
    trades = [trade for trade in collect_all_trades() if isinstance(trade.get("pnl"), (int, float))]
    wins = [trade for trade in trades if float(trade["pnl"]) >= 0]
    losses = [trade for trade in trades if float(trade["pnl"]) < 0]

    gross_profit = sum(float(trade["pnl"]) for trade in wins)
    gross_loss = abs(sum(float(trade["pnl"]) for trade in losses))
    total_trades = len(trades)
    win_rate = (len(wins) / total_trades) * 100.0 if total_trades else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss else 0.0
    by_symbol: dict[str, dict[str, float | int]] = {}

    for trade in trades:
        symbol = str(trade.get("symbol") or "")
        symbol_bucket = by_symbol.setdefault(
            symbol,
            {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "net_pnl": 0.0,
            },
        )
        symbol_bucket["trades"] = int(symbol_bucket["trades"]) + 1
        symbol_bucket["net_pnl"] = float(symbol_bucket["net_pnl"]) + float(trade["pnl"])
        if float(trade["pnl"]) >= 0:
            symbol_bucket["wins"] = int(symbol_bucket["wins"]) + 1
        else:
            symbol_bucket["losses"] = int(symbol_bucket["losses"]) + 1

    return StrategyStats(
        total_trades=total_trades,
        wins=len(wins),
        losses=len(losses),
        win_rate=round(win_rate, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        net_pnl=round(sum(float(trade["pnl"]) for trade in trades), 2),
        profit_factor=round(profit_factor, 2),
        long_count=sum(1 for trade in trades if str(trade.get("direction") or "").upper() == "BUY"),
        short_count=sum(1 for trade in trades if str(trade.get("direction") or "").upper() == "SELL"),
        by_symbol=by_symbol,
    )


def format_stats_report(stats: StrategyStats) -> str:
    lines = [
        "Asian Breakout Stats",
        f"Trades: {stats.total_trades}",
        f"Wins/Losses: {stats.wins}/{stats.losses}",
        f"Win rate: {stats.win_rate:.2f}%",
        f"Net PnL: {stats.net_pnl:.2f}",
        f"Gross profit: {stats.gross_profit:.2f}",
        f"Gross loss: {stats.gross_loss:.2f}",
        f"Profit factor: {stats.profit_factor:.2f}",
        f"Long/Short: {stats.long_count}/{stats.short_count}",
    ]
    if stats.by_symbol:
        lines.append("By symbol:")
        for symbol, bucket in sorted(stats.by_symbol.items()):
            lines.append(
                f"- {symbol}: trades={bucket['trades']} wins={bucket['wins']} "
                f"losses={bucket['losses']} net_pnl={float(bucket['net_pnl']):.2f}"
            )
    return "\n".join(lines)
