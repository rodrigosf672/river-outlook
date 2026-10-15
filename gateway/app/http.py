"""One place for outbound HTTP: timeouts, retries, caching, and error mapping.

Policy, applied to every upstream call:

* 5xx / timeouts / connection errors -> retry with exponential backoff.
* 429 -> do NOT retry (that burns more quota); surface it with Retry-After.
* Successful GETs are cached for CACHE_TTL_S. If a later call fails, a cached
  copy up to STALE_TTL_S old is served instead and the response is flagged
  as stale ("stale-if-error"). River data moves slowly, so that is honest.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import UpstreamError

RETRYABLE = {500, 502, 503, 504}


@dataclass
class FetchResult:
    data: Any
    ms: float
    cached: bool = False
    stale: bool = False


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, max_age_s: float) -> Any | None:
        hit = self._store.get(key)
        if hit and time.monotonic() - hit[0] <= max_age_s:
            return hit[1]
        return None

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()


cache = TTLCache()


def _retry_after(resp: httpx.Response) -> int | None:
    try:
        return int(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


async def get_json(client: httpx.AsyncClient, service: str, url: str, *,
                   params: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None,
                   ttl_s: float, stale_ttl_s: float,
                   retries: int = 2, not_found_ok: bool = False) -> FetchResult:
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    started = time.perf_counter()

    fresh = cache.get(key, ttl_s)
    if fresh is not None:
        return FetchResult(fresh, (time.perf_counter() - started) * 1000, cached=True)

    try:
        data = await _fetch(client, service, url, params, headers, retries, not_found_ok)
    except UpstreamError:
        stale = cache.get(key, stale_ttl_s)
        if stale is not None:
            return FetchResult(stale, (time.perf_counter() - started) * 1000,
                               cached=True, stale=True)
        raise

    cache.put(key, data)
    return FetchResult(data, (time.perf_counter() - started) * 1000)


async def _fetch(client, service, url, params, headers, retries, not_found_ok):
    last: UpstreamError | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = UpstreamError(service, "unavailable", f"{service} did not respond ({type(exc).__name__})")
        else:
            if resp.status_code == 429:
                raise UpstreamError(service, "rate_limited", f"{service} rate limit reached",
                                    retry_after=_retry_after(resp) or 60)
            if resp.status_code == 404 and not_found_ok:
                return None
            if resp.status_code in RETRYABLE:
                last = UpstreamError(service, "unavailable", f"{service} returned HTTP {resp.status_code}")
            elif resp.status_code >= 400:
                raise UpstreamError(service, "bad_response",
                                    f"{service} rejected the request (HTTP {resp.status_code})")
            else:
                try:
                    # strict=False: USGS site metadata sometimes contains raw
                    # control characters inside strings, which strict JSON rejects.
                    return json.loads(resp.text, strict=False)
                except ValueError as exc:
                    raise UpstreamError(service, "bad_response", f"{service} sent invalid JSON") from exc
        if attempt < retries:
            await asyncio.sleep(0.25 * 2 ** attempt)
    assert last is not None
    raise last
