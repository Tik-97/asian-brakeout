from __future__ import annotations

import datetime as dt
import math


DEFAULT_WEEKEND_CLOSE_HOUR_UTC = 20
DEFAULT_WEEKEND_CLOSE_MINUTE_UTC = 57


def weekend_close_deadline_for_trade_day(
    trade_day_utc: dt.date,
    *,
    weekend_close_hour_utc: int = DEFAULT_WEEKEND_CLOSE_HOUR_UTC,
    weekend_close_minute_utc: int = DEFAULT_WEEKEND_CLOSE_MINUTE_UTC,
) -> dt.datetime | None:
    if trade_day_utc.weekday() != 4:
        return None
    return dt.datetime.combine(
        trade_day_utc,
        dt.time(
            hour=weekend_close_hour_utc,
            minute=weekend_close_minute_utc,
            tzinfo=dt.timezone.utc,
        ),
    )


def cancel_deadline_for_trade_day(
    trade_day_utc: dt.date,
    *,
    weekend_close_hour_utc: int = DEFAULT_WEEKEND_CLOSE_HOUR_UTC,
    weekend_close_minute_utc: int = DEFAULT_WEEKEND_CLOSE_MINUTE_UTC,
) -> dt.datetime:
    weekend_deadline = weekend_close_deadline_for_trade_day(
        trade_day_utc,
        weekend_close_hour_utc=weekend_close_hour_utc,
        weekend_close_minute_utc=weekend_close_minute_utc,
    )
    if weekend_deadline is not None:
        return weekend_deadline
    return dt.datetime.combine(
        trade_day_utc,
        dt.time(hour=23, minute=59, tzinfo=dt.timezone.utc),
    )


def close_deadline_for_trade_day(
    trade_day_utc: dt.date,
    *,
    next_day_close_hour_utc: int,
    next_day_close_minute_utc: int,
    weekend_close_hour_utc: int = DEFAULT_WEEKEND_CLOSE_HOUR_UTC,
    weekend_close_minute_utc: int = DEFAULT_WEEKEND_CLOSE_MINUTE_UTC,
) -> dt.datetime:
    standard_deadline = dt.datetime.combine(
        trade_day_utc + dt.timedelta(days=1),
        dt.time(
            hour=next_day_close_hour_utc,
            minute=next_day_close_minute_utc,
            tzinfo=dt.timezone.utc,
        ),
    )
    weekend_deadline = weekend_close_deadline_for_trade_day(
        trade_day_utc,
        weekend_close_hour_utc=weekend_close_hour_utc,
        weekend_close_minute_utc=weekend_close_minute_utc,
    )
    if weekend_deadline is None:
        return standard_deadline
    return min(standard_deadline, weekend_deadline)


def overnight_funding_charge_times(
    *,
    fill_time_utc: dt.datetime,
    exit_time_utc: dt.datetime,
    swap_charge_timestamp_ms: int | None,
    swap_charge_interval_minutes: int | None,
) -> list[dt.datetime]:
    if (
        swap_charge_timestamp_ms is None
        or swap_charge_interval_minutes is None
        or swap_charge_interval_minutes <= 0
        or exit_time_utc <= fill_time_utc
    ):
        return []

    anchor = dt.datetime.fromtimestamp(swap_charge_timestamp_ms / 1000.0, tz=dt.timezone.utc)
    interval = dt.timedelta(minutes=int(swap_charge_interval_minutes))
    offset_seconds = (fill_time_utc - anchor).total_seconds() / interval.total_seconds()
    periods = math.floor(offset_seconds) + 1
    first_charge = anchor + (interval * periods)

    charges: list[dt.datetime] = []
    current = first_charge
    while current <= exit_time_utc:
        if current > fill_time_utc:
            charges.append(current)
        current = current + interval
    return charges
