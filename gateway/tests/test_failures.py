"""Every external dependency can fail; none of them should break the app."""
import json
from dataclasses import replace

import httpx
from httpx import Response

from .conftest import daily_json

BODY = {"site_id": "01646500", "horizon_days": 7}


def test_openmeteo_down_degrades_to_forecast_without_rain(client, upstream):
    upstream["rain"].mock(return_value=Response(503))
    r = client.post("/api/forecasts", json=BODY)
    assert r.status_code == 202
    job = r.json()
    assert job["rain"] is None and job["status"] == "queued"
    assert any("Open-Meteo returned HTTP 503" in n for n in job["notices"])
    assert upstream["rain"].call_count == 3  # 1 try + 2 retries on 5xx
    sent = json.loads(upstream["run"].calls.last.request.content)["input"]
    assert sent["rain_past"] is None and sent["rain_future"] is None


def test_usgs_rate_limit_returns_503_with_retry_after(client, upstream):
    upstream["daily"].mock(return_value=Response(429, headers={"Retry-After": "120"}))
    r = client.post("/api/forecasts", json=BODY)
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "120"
    assert r.json()["error"] == {"code": "upstream_rate_limited", "service": "USGS",
                                 "message": "USGS rate limit reached. Try again shortly.",
                                 "retry_after": 120}
    assert upstream["daily"].call_count == 1  # never retry a 429


def test_usgs_timeout_served_from_stale_cache(make_client, settings, upstream):
    client = make_client(replace(settings, cache_ttl_s=0))  # force a refetch every time
    assert client.post("/api/forecasts", json=BODY).status_code == 202
    upstream["daily"].mock(side_effect=httpx.ConnectTimeout("boom"))
    r = client.post("/api/forecasts", json=BODY)
    assert r.status_code == 202
    assert "USGS is failing; showing cached gauge data." in r.json()["notices"]


def test_runpod_submit_failure_falls_back_to_baseline(client, upstream):
    upstream["run"].mock(return_value=Response(500))
    job = client.post("/api/forecasts", json=BODY).json()
    assert job["status"] == "completed" and job["mode"] == "baseline"
    assert len(job["forecast"]) == 7
    assert any("Runpod returned HTTP 500" in n for n in job["notices"])


def test_gpu_job_failure_falls_back_to_baseline(client, upstream):
    job = client.post("/api/forecasts", json=BODY).json()
    upstream["status"].mock(return_value=Response(200, json={"status": "FAILED", "error": "CUDA OOM"}))
    done = client.get(f"/api/forecasts/{job['job_id']}").json()
    assert done["mode"] == "baseline" and "CUDA OOM" in done["notices"][-1]


def test_gpu_deadline_cancels_and_falls_back(make_client, settings, upstream):
    client = make_client(replace(settings, gpu_deadline_s=0))
    job = client.post("/api/forecasts", json=BODY).json()
    done = client.get(f"/api/forecasts/{job['job_id']}").json()
    assert done["mode"] == "baseline"
    assert upstream["cancel"].called


def test_simulated_faults_for_the_live_demo(client, upstream):
    job = client.post("/api/forecasts?simulate=openmeteo_down,gpu_down", json=BODY).json()
    assert job["rain"] is None and job["mode"] == "baseline"
    assert not upstream["rain"].called and not upstream["run"].called


def test_fault_injection_is_off_unless_enabled(make_client, settings):
    client = make_client(replace(settings, allow_fault_injection=False))
    r = client.post("/api/forecasts?simulate=gpu_down", json=BODY)
    assert r.status_code == 400 and r.json()["error"]["code"] == "fault_injection_disabled"


def test_baseline_band_is_ordered():
    from app import baseline
    from app.series import regularize
    rows = [(f["properties"]["time"], float(f["properties"]["value"]))
            for f in daily_json(value=lambda i: 1000 + (300 if i % 7 == 0 else 0))["features"]]
    for day in baseline.forecast(regularize(rows), 7):
        assert 0 <= day["p10"] <= day["p50"] <= day["p90"]


def test_partial_rain_trims_history_instead_of_dropping_rain(client, upstream):
    from .conftest import rain_json
    rain = rain_json()
    # Open-Meteo really does return null for its oldest past days.
    first_history_day = "2026-08-11"
    rain["daily"]["precipitation_sum"] = [None if t <= first_history_day else 1.0
                                          for t in rain["daily"]["time"]]
    upstream["rain"].mock(return_value=Response(200, json=rain))
    job = client.post("/api/forecasts", json=BODY).json()
    assert job["rain"] is not None
    assert job["history"][0]["date"] == "2026-08-12" and len(job["history"]) == 59
    sent = json.loads(upstream["run"].calls.last.request.content)["input"]
    assert len(sent["history"]) == len(sent["rain_past"]) == 59
