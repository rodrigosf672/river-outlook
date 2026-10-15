"""Open-Meteo client: daily precipitation, past and forecast, at the gauge.

Free for non-commercial use, no key. Documented limits: 10,000 calls/day,
5,000/hour, 600/minute. `past_days` is capped at 92 by the API.
"""
from __future__ import annotations

import httpx

from .config import Settings
from .http import FetchResult, get_json

MAX_PAST_DAYS = 92


async def get_daily_precip(client: httpx.AsyncClient, s: Settings, lat: float, lon: float,
                           forecast_days: int) -> tuple[dict[str, float], FetchResult]:
    """Return {date: precipitation_mm} covering the last 92 days plus the forecast."""
    res = await get_json(
        client, "Open-Meteo", f"{s.openmeteo_base}/forecast",
        params={
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "daily": "precipitation_sum",
            "past_days": MAX_PAST_DAYS,
            "forecast_days": min(forecast_days, 16),
            "timezone": "UTC",
        },
        headers={"User-Agent": s.user_agent},
        ttl_s=s.cache_ttl_s, stale_ttl_s=s.stale_ttl_s,
    )
    daily = res.data.get("daily") or {}
    times, values = daily.get("time") or [], daily.get("precipitation_sum") or []
    precip = {t: float(v) for t, v in zip(times, values) if v is not None}
    return precip, res
