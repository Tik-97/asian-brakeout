from __future__ import annotations

import csv
import json
from datetime import date

import pandas as pd

from capital_api import CapitalAPI
from config import AppConfig
from data_utils import calculate_atr, get_asian_range, parse_candles
from state import load_state


def _trade_day(value):
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _load_trade_rows():
    current_state = load_state()
    rows = []
    for symbol, info in current_state.items():
        for trade in info.get("all_trades", []):
            if not isinstance(trade, dict):
                continue
            row = dict(trade)
            row["symbol"] = symbol
            rows.append(row)
    rows.sort(key=lambda trade: (trade.get("trade_day_utc") or "", trade.get("closed_at") or "", trade.get("symbol") or ""))
    return rows


def _infer_trade_context(df, trade_day, direction):
    asian_high, asian_low = get_asian_range(df, trade_day)
    session = df[(df["time"].dt.date == trade_day) & (df["time"].dt.hour >= 9)].copy()
    signal_row = None
    signal_close = None
    if asian_high is not None and asian_low is not None and not session.empty:
        for _, candle in session.iterrows():
            close_price = float(candle["close"])
            if direction == "BUY" and close_price >= asian_high:
                signal_row = candle
                signal_close = close_price
                break
            if direction == "SELL" and close_price <= asian_low:
                signal_row = candle
                signal_close = close_price
                break
    return {
        "asian_high": asian_high,
        "asian_low": asian_low,
        "signal_row": signal_row,
        "signal_close": signal_close,
        "entry_level_used": asian_high if direction == "BUY" else asian_low if direction == "SELL" else None,
    }


def build_performance_journal(api: CapitalAPI, config: AppConfig):
    trades = _load_trade_rows()
    candles_cache = {}
    context_cache = {}
    journal = []

    for trade in trades:
        symbol = trade.get("symbol")
        epic = config.strategy.symbols.get(symbol)
        trade_day = _trade_day(trade.get("trade_day_utc"))
        direction = str(trade.get("direction") or "").upper()
        if not epic or trade_day is None or direction not in {"BUY", "SELL"}:
            journal.append(
                {
                    "symbol": symbol,
                    "deal_id": trade.get("deal_id"),
                    "trade_day_utc": trade.get("trade_day_utc"),
                    "entry_at": trade.get("entry_at"),
                    "closed_at": trade.get("closed_at"),
                    "direction": direction or None,
                    "result": trade.get("result"),
                    "pnl": trade.get("pnl"),
                    "entry_time_source": "insufficient_data",
                    "signal_time_used_utc": None,
                    "asian_high": None,
                    "asian_low": None,
                    "entry_level_used": None,
                    "signal_close": None,
                    "atr": None,
                    "atr_percent": None,
                    "source": trade.get("source"),
                }
            )
            continue

        if symbol not in candles_cache:
            candles_cache[symbol] = parse_candles(api.get_candles(epic, resolution="HOUR", max_candles=250))
        df = candles_cache[symbol]

        context_key = (symbol, trade_day.isoformat(), direction)
        if context_key not in context_cache:
            context_cache[context_key] = _infer_trade_context(df, trade_day, direction)
        context = context_cache[context_key]

        entry_at = trade.get("entry_at")
        time_source = "exact_entry_at" if entry_at else "inferred_breakout_candle"
        signal_time_used = None
        atr_value = None

        if entry_at:
            parsed_entry = pd.to_datetime(entry_at, utc=True, errors="coerce")
            subset = df[df["time"] <= parsed_entry].copy()
            if len(subset) >= config.strategy.atr_period:
                atr_value = calculate_atr(subset, config.strategy.atr_period)
                signal_time_used = subset.iloc[-1]["time"]
        elif context["signal_row"] is not None:
            signal_time_used = context["signal_row"]["time"]
            subset = df[df["time"] <= signal_time_used].copy()
            if len(subset) >= config.strategy.atr_period:
                atr_value = calculate_atr(subset, config.strategy.atr_period)

        entry_level_used = context["entry_level_used"]
        atr_percent = None
        if atr_value is not None and entry_level_used:
            atr_percent = atr_value / entry_level_used * 100.0

        journal.append(
            {
                "symbol": symbol,
                "deal_id": trade.get("deal_id"),
                "trade_day_utc": trade.get("trade_day_utc"),
                "entry_at": trade.get("entry_at"),
                "closed_at": trade.get("closed_at"),
                "direction": direction,
                "result": trade.get("result"),
                "pnl": trade.get("pnl"),
                "entry_time_source": time_source,
                "signal_time_used_utc": signal_time_used.isoformat() if signal_time_used is not None else None,
                "asian_high": context["asian_high"],
                "asian_low": context["asian_low"],
                "entry_level_used": entry_level_used,
                "signal_close": context["signal_close"],
                "atr": atr_value,
                "atr_percent": atr_percent,
                "source": trade.get("source"),
            }
        )
    return journal


def export_performance_journal(api: CapitalAPI, config: AppConfig):
    journal = build_performance_journal(api, config)
    config.runtime.journal_json_file.write_text(json.dumps(journal, indent=2), encoding="utf-8")

    fieldnames = [
        "symbol",
        "deal_id",
        "trade_day_utc",
        "entry_at",
        "closed_at",
        "direction",
        "result",
        "pnl",
        "entry_time_source",
        "signal_time_used_utc",
        "asian_high",
        "asian_low",
        "entry_level_used",
        "signal_close",
        "atr",
        "atr_percent",
        "source",
    ]
    with config.runtime.journal_csv_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in journal:
            writer.writerow(row)

    return {
        "rows": len(journal),
        "json_path": str(config.runtime.journal_json_file),
        "csv_path": str(config.runtime.journal_csv_file),
    }
