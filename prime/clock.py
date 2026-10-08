"""Time helpers. The competition counts trading days in Hong Kong time (UTC+8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))


def hkt_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=HKT)


def hkt_day(ts: float) -> str:
    """Calendar day in Hong Kong time, e.g. '2026-10-09'."""
    return hkt_dt(ts).strftime("%Y-%m-%d")


def hkt_hour(ts: float) -> float:
    """Hour of day in Hong Kong time as a float, e.g. 9.5 for 09:30."""
    d = hkt_dt(ts)
    return d.hour + d.minute / 60.0 + d.second / 3600.0
