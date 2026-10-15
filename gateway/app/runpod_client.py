"""Runpod Serverless queue API: submit a job, poll its status, cancel it.

We use the async /run + /status pair rather than /runsync on purpose: a cold
GPU worker can take longer than the 100 s Cloudflare limit on Runpod's pod
proxy, so the browser polls our gateway and never holds a long request open.
"""
from __future__ import annotations

import httpx

from .config import Settings
from .errors import UpstreamError

SERVICE = "Runpod"


def _url(s: Settings, path: str) -> str:
    return f"{s.runpod_base}/{s.runpod_endpoint_id}/{path}"


def _headers(s: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {s.runpod_api_key}"}


async def _call(client: httpx.AsyncClient, method: str, url: str, s: Settings, **kw) -> dict:
    try:
        resp = await client.request(method, url, headers=_headers(s), **kw)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise UpstreamError(SERVICE, "unavailable", f"Runpod did not respond ({type(exc).__name__})") from exc
    if resp.status_code == 429:
        raise UpstreamError(SERVICE, "rate_limited", "Runpod rate limit reached")
    if resp.status_code in (401, 403):
        raise UpstreamError(SERVICE, "bad_response", "Runpod rejected the API key")
    if resp.status_code >= 400:
        raise UpstreamError(SERVICE, "unavailable", f"Runpod returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise UpstreamError(SERVICE, "bad_response", "Runpod sent invalid JSON") from exc


async def submit(client: httpx.AsyncClient, s: Settings, payload: dict) -> str:
    # Runpod drops the job if no worker picks it up before the TTL (ms).
    body = {"input": payload, "policy": {"ttl": int(s.gpu_deadline_s * 1000)}}
    data = await _call(client, "POST", _url(s, "run"), s, json=body)
    job_id = data.get("id")
    if not job_id:
        raise UpstreamError(SERVICE, "bad_response", "Runpod did not return a job id")
    return job_id


async def status(client: httpx.AsyncClient, s: Settings, job_id: str) -> dict:
    """Raw status: {status, output?, error?, delayTime?, executionTime?}."""
    return await _call(client, "GET", _url(s, f"status/{job_id}"), s)


async def cancel(client: httpx.AsyncClient, s: Settings, job_id: str) -> None:
    try:
        await _call(client, "POST", _url(s, f"cancel/{job_id}"), s)
    except UpstreamError:
        pass  # best effort; the job's TTL will expire it anyway
