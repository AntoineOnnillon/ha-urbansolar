from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Iterable, List, Tuple


def _date_to_start_ts(value: str) -> float:
    d = date.fromisoformat(value)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def _date_to_end_ts(value: str) -> float:
    d = date.fromisoformat(value)
    # end is exclusive: start of next day (UTC)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() + 86400.0


def periods_to_ranges(periods: Iterable[dict]) -> List[Tuple[float, float, float]]:
    ranges: List[Tuple[float, float, float]] = []
    for p in periods:
        start_ts = _date_to_start_ts(str(p["from"]))
        end_ts = _date_to_end_ts(str(p["to"]))
        price = float(p["price"])
        ranges.append((start_ts, end_ts, price))
    ranges.sort(key=lambda r: r[0])
    return ranges


def price_for_ts(ranges: List[Tuple[float, float, float]], ts: float) -> float:
    for start_ts, end_ts, price in ranges:
        if start_ts <= ts < end_ts:
            return price
    return 0.0
