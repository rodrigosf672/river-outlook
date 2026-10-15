"""Turn raw gauge readings into a clean daily series a model can use."""
from __future__ import annotations

from datetime import date, timedelta

from .errors import InputError

MAX_GAP_DAYS = 3      # interpolate short outages; longer ones break the series
MIN_POINTS = 30       # below this a forecast is not meaningful


def regularize(rows: list[tuple[str, float | None]]) -> list[tuple[str, float]]:
    """Daily, gap-free series ending at the latest valid reading.

    Short gaps (<= MAX_GAP_DAYS) are linearly interpolated. If a longer gap
    exists, only the contiguous segment after it is kept.
    """
    valid = {date.fromisoformat(d): v for d, v in rows if v is not None and v >= 0}
    if not valid:
        raise InputError("no_discharge_data",
                         "This gauge has no recent discharge readings (it may not measure flow).")
    days = sorted(valid)
    out: list[tuple[date, float]] = [(days[0], valid[days[0]])]
    for prev, cur in zip(days, days[1:]):
        gap = (cur - prev).days
        if gap > MAX_GAP_DAYS + 1:
            out = []  # restart after a long outage
        else:
            for i in range(1, gap):
                frac = i / gap
                out.append((prev + timedelta(days=i), valid[prev] + frac * (valid[cur] - valid[prev])))
        out.append((cur, valid[cur]))
    if len(out) < MIN_POINTS:
        raise InputError("insufficient_data",
                         f"Only {len(out)} usable days of discharge data; need at least {MIN_POINTS}.")
    return [(d.isoformat(), round(v, 3)) for d, v in out]


def future_dates(last: str, horizon: int) -> list[str]:
    start = date.fromisoformat(last)
    return [(start + timedelta(days=i)).isoformat() for i in range(1, horizon + 1)]
