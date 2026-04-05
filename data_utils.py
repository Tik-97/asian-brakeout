import pandas as pd


def _extract_price_side(price_obj, side):
    if not isinstance(price_obj, dict):
        return None
    return price_obj.get(side)


def parse_candles(data):
    candles = data.get("prices", [])
    rows = []

    for c in candles:
        raw_time = c.get("snapshotTimeUTC") or c.get("snapshotTime")
        if not raw_time:
            continue

        open_price = c.get("openPrice", {})
        high_price = c.get("highPrice", {})
        low_price = c.get("lowPrice", {})
        close_price = c.get("closePrice", {})

        rows.append({
            "time": raw_time,
            "open": _extract_price_side(open_price, "bid"),
            "high": _extract_price_side(high_price, "bid"),
            "low": _extract_price_side(low_price, "bid"),
            "close": _extract_price_side(close_price, "bid"),
            "volume": candle.get("lastTradedVolume"),
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)

    return df


def parse_candles_bid_ask(data):
    candles = data.get("prices", [])
    rows = []

    for candle in candles:
        raw_time = candle.get("snapshotTimeUTC") or candle.get("snapshotTime")
        if not raw_time:
            continue

        open_price = candle.get("openPrice", {})
        high_price = candle.get("highPrice", {})
        low_price = candle.get("lowPrice", {})
        close_price = candle.get("closePrice", {})

        rows.append({
            "time": raw_time,
            "open": _extract_price_side(open_price, "bid"),
            "high": _extract_price_side(high_price, "bid"),
            "low": _extract_price_side(low_price, "bid"),
            "close": _extract_price_side(close_price, "bid"),
            "open_bid": _extract_price_side(open_price, "bid"),
            "open_ask": _extract_price_side(open_price, "ask"),
            "high_bid": _extract_price_side(high_price, "bid"),
            "high_ask": _extract_price_side(high_price, "ask"),
            "low_bid": _extract_price_side(low_price, "bid"),
            "low_ask": _extract_price_side(low_price, "ask"),
            "close_bid": _extract_price_side(close_price, "bid"),
            "close_ask": _extract_price_side(close_price, "ask"),
            "volume": candle.get("lastTradedVolume"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    required = [
        "time",
        "open_bid",
        "open_ask",
        "high_bid",
        "high_ask",
        "low_bid",
        "low_ask",
        "close_bid",
        "close_ask",
    ]
    df = df.dropna(subset=required)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.sort_values("time").reset_index(drop=True)
    return df

def get_asian_range(df, target_date):
    if df is None or df.empty:
        return None, None

    work = df.copy()
    work["time"] = pd.to_datetime(work["time"], utc=True, errors="coerce")
    work = work.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    asian = work[
        (work["time"].dt.date == target_date) &
        (work["time"].dt.hour >= 0) &
        (work["time"].dt.hour <= 8)
    ].copy()

    if asian.empty:
        return None, None

    high = asian["high"].max()
    low = asian["low"].min()

    return float(high), float(low)


def calculate_atr(df, period):
    work = df.copy()

    work["prev_close"] = work["close"].shift(1)
    work["tr1"] = work["high"] - work["low"]
    work["tr2"] = (work["high"] - work["prev_close"]).abs()
    work["tr3"] = (work["low"] - work["prev_close"]).abs()
    work["tr"] = work[["tr1", "tr2", "tr3"]].max(axis=1)

    atr = work["tr"].rolling(period).mean().iloc[-1]
    return float(atr)
