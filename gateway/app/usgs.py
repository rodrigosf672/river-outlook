"""USGS Water Data OGC API client: gauge metadata + daily mean discharge.

Uses api.waterdata.usgs.gov (the legacy waterservices.usgs.gov is scheduled
for decommission). Without a key the API allows ~1,000 requests/hour per IP;
a free api.data.gov key (USGS_API_KEY) raises that.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings
from .errors import InputError
from .http import FetchResult, get_json

DISCHARGE = "00060"   # cubic feet per second
DAILY_MEAN = "00003"


@dataclass
class Site:
    id: str
    name: str
    state: str | None
    lat: float
    lon: float


def _headers(s: Settings) -> dict[str, str]:
    h = {"User-Agent": s.user_agent}
    if s.usgs_api_key:
        h["X-Api-Key"] = s.usgs_api_key
    return h


async def get_site(client: httpx.AsyncClient, s: Settings, site_id: str) -> tuple[Site, FetchResult]:
    res = await get_json(
        client, "USGS", f"{s.usgs_base}/collections/monitoring-locations/items/USGS-{site_id}",
        params={"f": "json"}, headers=_headers(s),
        ttl_s=86400, stale_ttl_s=7 * 86400, not_found_ok=True,
    )
    if res.data is None:
        raise InputError("site_not_found", f"No USGS gauge with id {site_id}.")
    props = res.data.get("properties") or {}
    geom = res.data.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        raise InputError("site_not_located", f"USGS gauge {site_id} has no coordinates.")
    site = Site(
        id=site_id,
        name=props.get("monitoring_location_name") or f"USGS {site_id}",
        state=props.get("state_name"),
        lat=float(coords[1]),
        lon=float(coords[0]),
    )
    return site, res


async def get_daily_discharge(client: httpx.AsyncClient, s: Settings, site_id: str,
                              days: int) -> tuple[list[tuple[str, float | None]], FetchResult]:
    res = await get_json(
        client, "USGS", f"{s.usgs_base}/collections/daily/items",
        params={
            "f": "json",
            "monitoring_location_id": f"USGS-{site_id}",
            "parameter_code": DISCHARGE,
            "statistic_id": DAILY_MEAN,
            "time": f"P{days}D",
            "properties": "time,value",
            "skipGeometry": "true",
            "sortby": "time",
            "limit": 1000,
        },
        headers=_headers(s), ttl_s=s.cache_ttl_s, stale_ttl_s=s.stale_ttl_s,
    )
    rows: list[tuple[str, float | None]] = []
    for feat in res.data.get("features", []):
        p = feat.get("properties") or {}
        value = p.get("value")
        try:
            rows.append((p["time"][:10], float(value) if value is not None else None))
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than failing the whole request
    return rows, res
