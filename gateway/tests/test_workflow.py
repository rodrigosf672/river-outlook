"""Main workflow: USGS + Open-Meteo -> Runpod GPU job -> forecast."""
import json

from httpx import Response

from .conftest import gpu_output

BODY = {"site_id": "01646500", "horizon_days": 7}


def test_forecast_happy_path_runs_on_gpu(client, upstream):
    r = client.post("/api/forecasts", json=BODY)
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "queued" and job["runpod_status"] == "IN_QUEUE"
    assert job["site"]["name"].startswith("POTOMAC")
    assert len(job["history"]) == 60 and len(job["rain"]["future"]) == 7

    # Both APIs feed the GPU job: discharge history plus aligned rainfall.
    sent = json.loads(upstream["run"].calls.last.request.content)["input"]
    assert len(sent["history"]) == len(sent["rain_past"]) == 60
    assert len(sent["rain_future"]) == 7
    # Secrets go to the upstreams, never to the browser.
    assert upstream["run"].calls.last.request.headers["Authorization"] == "Bearer rp_secret"
    assert upstream["daily"].calls.last.request.headers["X-Api-Key"] == "usgs_secret"
    assert "secret" not in r.text

    upstream["status"].mock(return_value=Response(200, json={"status": "IN_PROGRESS"}))
    assert client.get(f"/api/forecasts/{job['job_id']}").json()["status"] == "running"

    upstream["status"].mock(return_value=Response(200, json={
        "status": "COMPLETED", "delayTime": 8000, "executionTime": 450, "output": gpu_output()}))
    done = client.get(f"/api/forecasts/{job['job_id']}").json()
    assert done["status"] == "completed" and done["mode"] == "gpu"
    assert done["model"]["device"] == "NVIDIA RTX 4090" and done["model"]["covariates"] is True
    assert len(done["forecast"]) == 7
    spans = [s["name"] for s in done["trace"]]
    assert spans[:3] == ["USGS · gauge metadata", "USGS · daily discharge", "Open-Meteo · rainfall"]
    assert "Runpod · GPU execution" in spans


def test_no_gpu_configured_serves_baseline(make_client, settings, upstream):
    from dataclasses import replace
    client = make_client(replace(settings, runpod_api_key=None))
    job = client.post("/api/forecasts", json=BODY).json()
    assert job["status"] == "completed" and job["mode"] == "baseline"
    assert not upstream["run"].called


def test_invalid_input_never_reaches_upstreams(client, upstream):
    for bad in ({"site_id": "abc"}, {"site_id": "01646500", "horizon_days": 99}, {}):
        r = client.post("/api/forecasts", json=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    assert not upstream["site"].called and not upstream["daily"].called


def test_gauge_without_discharge_is_a_clear_422(client, upstream):
    upstream["daily"].mock(return_value=Response(200, json={"features": [
        {"properties": {"time": "2026-10-09", "value": None}}]}))
    r = client.post("/api/forecasts", json=BODY)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_discharge_data"


def test_per_ip_rate_limit(make_client, settings):
    from dataclasses import replace
    client = make_client(replace(settings, rate_limit_per_min=1))
    assert client.post("/api/forecasts", json=BODY).status_code == 202
    r = client.post("/api/forecasts", json=BODY)
    assert r.status_code == 429 and r.headers["Retry-After"] == "60"
