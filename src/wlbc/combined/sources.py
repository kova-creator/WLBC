"""Pull both sources and hand back merged daily records."""

from __future__ import annotations

import datetime as dt

from .merge import (
    DailyRecord,
    Pick,
    add_deltas,
    add_trends,
    merge_daily,
    oura_by_day,
    renpho_by_day,
)


def fetch_renpho(pick: Pick = "first") -> dict:
    """Every weigh-in on the account, collapsed to one record per day."""
    from ..renpho.client import RenphoConnection

    with RenphoConnection.from_env() as renpho:
        return renpho_by_day(renpho.measurements(), pick=pick)


def fetch_oura(start: dt.date, end: dt.date, sandbox: bool = False) -> dict:
    """Oura's daily collections over a date range, folded into one record per day."""
    from ..oura.client import OuraClient

    with OuraClient(sandbox=sandbox) as oura:
        return oura_by_day(
            daily_sleep=oura.date_range("daily_sleep", start, end),
            daily_readiness=oura.date_range("daily_readiness", start, end),
            daily_activity=oura.date_range("daily_activity", start, end),
            sleep_periods=oura.date_range("sleep", start, end),
        )


def collect(
    start: dt.date,
    end: dt.date,
    *,
    pick: Pick = "first",
    window_days: int = 7,
    use_oura: bool = True,
    use_renpho: bool = True,
    sandbox: bool = False,
    body_start: dt.date | None = None,
) -> list[DailyRecord]:
    """Fetch, join, and smooth. Either source can be skipped.

    Renpho is fetched in full (the API has no date filter) and trimmed here.
    Weigh-ins from before *start* are still used to warm up the trailing trend,
    so the first day of the chart has a real trend value rather than a lone
    reading.

    ``body_start`` cuts body-composition data off before a given day while
    leaving Oura's range untouched — for when older weigh-ins came from a
    different scale, a different person, or a period you don't want counted.
    Oura still covers the full span; the body-comp charts start where the
    trustworthy readings do.
    """
    body = fetch_renpho(pick=pick) if use_renpho else {}
    if body_start is not None:
        body = {day: values for day, values in body.items() if day >= body_start}
    oura = fetch_oura(start, end, sandbox=sandbox) if use_oura else {}

    # The trend warm-up may reach back before `start`, but never before
    # `body_start` — that cutoff is a statement about data quality, not a window.
    warmup = start - dt.timedelta(days=window_days)
    records = merge_daily(body, oura, start=warmup, end=end)
    add_trends(records, window_days=window_days)
    # Deltas are baselined after trimming, so zero is the start of the range the
    # user asked for rather than the invisible warm-up window.
    in_range = [record for record in records if record.day >= start]
    add_deltas(in_range)
    return in_range
