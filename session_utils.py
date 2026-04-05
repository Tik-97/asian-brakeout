from __future__ import annotations

import datetime as dt
import os


def get_session_start_hour_utc(default: int = 9) -> int:
    raw_value = os.getenv("AB_SESSION_START_HOUR_UTC")
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def current_session_date(
    now_utc: dt.datetime,
    session_start_hour_utc: int | None = None,
) -> dt.date:
    resolved_start_hour = (
        get_session_start_hour_utc()
        if session_start_hour_utc is None
        else session_start_hour_utc
    )
    if now_utc.hour >= resolved_start_hour:
        return now_utc.date()
    return (now_utc - dt.timedelta(days=1)).date()


def parse_utc_timestamp(value: str | None) -> dt.datetime | None:
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


def parse_utc_day(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def trade_day_from_runtime_fields(
    *,
    active_trade_day_utc: str | None,
    position_opened_at: str | None,
    working_order_created_at: str | None,
    session_start_hour_utc: int | None = None,
) -> dt.date | None:
    trade_day = parse_utc_day(active_trade_day_utc)
    if trade_day is not None:
        return trade_day

    opened_at = parse_utc_timestamp(position_opened_at)
    if opened_at is not None:
        return current_session_date(opened_at, session_start_hour_utc)

    created_at = parse_utc_timestamp(working_order_created_at)
    if created_at is not None:
        return current_session_date(created_at, session_start_hour_utc)

    return None
