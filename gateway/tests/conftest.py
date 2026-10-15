from datetime import date, timedelta

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app import http
from app.config import Settings
from app.main import create_app

SITE = "01646500"
USGS = "https://api.waterdata.usgs.gov/ogcapi/v1"
OPENMETEO = "https://api.open-meteo.com/v1/forecast"
RUNPOD = "https://api.runpod.ai/v2/ep123"
LAST = date(2026, 10, 9)


def site_json():
    return {"type": "Feature",
            "properties": {"monitoring_location_name": "POTOMAC RIVER NEAR WASH, DC", "state_name": "Maryland"},
            "geometry": {"type": "Point", "coordinates": [-77.1276, 38.9498]}}


def daily_json(n=60, value=lambda i: 1000.0 + 10 * i):
    days = [LAST - timedelta(days=n - 1 - i) for i in range(n)]
    return {"features": [{"properties": {"time": d.isoformat(), "value": str(value(i))}}
                         for i, d in enumerate(days)]}


def rain_json():
    days = [LAST - timedelta(days=91 - i) for i in range(92 + 16)]
    return {"daily": {"time": [d.isoformat() for d in days], "precipitation_sum": [1.0] * len(days)}}


def gpu_output(horizon=7):
    return {"forecast": [{"date": (LAST + timedelta(days=i)).isoformat(), "p10": 900.0, "p50": 1000.0,
                          "p90": 1200.0} for i in range(1, horizon + 1)],
            "model": "amazon/chronos-2", "device": "NVIDIA RTX 4090", "covariates_used": True,
            "inference_ms": 120}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    http.cache.clear()

    async def no_sleep(_):
        return None
    monkeypatch.setattr(http.asyncio, "sleep", no_sleep)


@pytest.fixture
def settings():
    return Settings(runpod_api_key="rp_secret", runpod_endpoint_id="ep123", usgs_api_key="usgs_secret",
                    allow_fault_injection=True, rate_limit_per_min=100)


@pytest.fixture
def upstream():
    """Every upstream healthy by default; tests override single routes."""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{USGS}/collections/monitoring-locations/items/USGS-{SITE}", name="site").mock(
            return_value=Response(200, json=site_json()))
        router.get(f"{USGS}/collections/daily/items", name="daily").mock(
            return_value=Response(200, json=daily_json()))
        router.get(OPENMETEO, name="rain").mock(return_value=Response(200, json=rain_json()))
        router.post(f"{RUNPOD}/run", name="run").mock(
            return_value=Response(200, json={"id": "rp-job-1", "status": "IN_QUEUE"}))
        router.get(f"{RUNPOD}/status/rp-job-1", name="status").mock(
            return_value=Response(200, json={"id": "rp-job-1", "status": "IN_QUEUE"}))
        router.post(f"{RUNPOD}/cancel/rp-job-1", name="cancel").mock(return_value=Response(200, json={}))
        yield router


@pytest.fixture
def make_client(upstream):
    clients = []

    def make(settings):
        c = TestClient(create_app(settings))
        c.__enter__()
        clients.append(c)
        return c
    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client, settings):
    return make_client(settings)
