"""The workflow: USGS + Open-Meteo -> Runpod GPU forecast (or CPU baseline).

create()  fetches both APIs, cleans the data, and submits a GPU job.
refresh() is called on every poll; it advances the job from Runpod's status
          and falls back to the baseline if the GPU path fails or stalls.

Every hop is recorded as a trace span so the UI can show the request's path.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from . import baseline, openmeteo, runpod_client, usgs
from .config import Settings
from .errors import UpstreamError
from .jobs import Job, JobStore
from .series import MIN_POINTS, future_dates, regularize

FAULTS = {"usgs_down", "usgs_rate_limit", "openmeteo_down", "gpu_down"}
CHRONOS_QUANTILES = [0.1, 0.5, 0.9]


class Tracer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.spans: list[dict] = []

    def add(self, name: str, ms: float, *, ok: bool = True, detail: str = "") -> None:
        end = (time.perf_counter() - self.t0) * 1000
        self.spans.append({"name": name, "start_ms": round(max(0.0, end - ms)),
                           "ms": round(ms), "ok": ok, "detail": detail})

    def fetch(self, name: str, res) -> None:
        detail = "stale cache (upstream failing)" if res.stale else "cache hit" if res.cached else ""
        self.add(name, res.ms, detail=detail)


def _simulated(service: str, fault: str) -> UpstreamError:
    if fault == "usgs_rate_limit":
        return UpstreamError(service, "rate_limited", f"{service} rate limit reached (simulated)", retry_after=60)
    return UpstreamError(service, "unavailable", f"{service} is down (simulated)")


class ForecastService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient, store: JobStore) -> None:
        self.s = settings
        self.client = client
        self.store = store

    # ------------------------------------------------------------------ create
    async def create(self, site_id: str, horizon: int, faults: set[str] = frozenset()) -> Job:
        tr = Tracer()
        notices = [f"Simulated failure: {f}" for f in sorted(faults)]

        # 1. USGS: metadata and discharge history, in parallel.
        for f in ("usgs_down", "usgs_rate_limit"):
            if f in faults:
                tr.add("USGS", 0, ok=False, detail=f)
                raise _simulated("USGS", f)
        (site, site_res), (rows, daily_res) = await asyncio.gather(
            usgs.get_site(self.client, self.s, site_id),
            usgs.get_daily_discharge(self.client, self.s, site_id, self.s.history_days),
        )
        tr.fetch("USGS · gauge metadata", site_res)
        tr.fetch("USGS · daily discharge", daily_res)
        if site_res.stale or daily_res.stale:
            notices.append("USGS is failing; showing cached gauge data.")
        history = regularize(rows)
        future = future_dates(history[-1][0], horizon)

        # 2. Open-Meteo: rainfall at the gauge. Optional: degrade, don't fail.
        rain = None
        try:
            if "openmeteo_down" in faults:
                raise _simulated("Open-Meteo", "openmeteo_down")
            # USGS daily data lags ~1 day, so ask for a little extra forecast.
            precip, om_res = await openmeteo.get_daily_precip(
                self.client, self.s, site.lat, site.lon, forecast_days=horizon + 3)
            tr.fetch("Open-Meteo · rainfall", om_res)
            # Open-Meteo's oldest past days can come back null; keep the
            # longest recent stretch where both APIs have data.
            start = len(history)
            while start > 0 and history[start - 1][0] in precip:
                start -= 1
            ahead = [precip.get(d) for d in future]
            if None in ahead or len(history) - start < MIN_POINTS:
                notices.append("Rainfall did not cover enough days; forecasting without it.")
            else:
                history = history[start:]
                past = [precip[d] for d, _ in history]
                rain = {"past": [{"date": d, "mm": mm} for (d, _), mm in zip(history, past)],
                        "future": [{"date": d, "mm": mm} for d, mm in zip(future, ahead)]}
        except UpstreamError as exc:
            tr.add("Open-Meteo · rainfall", 0, ok=False, detail=exc.message)
            notices.append(f"{exc.message}. Forecast runs without rainfall.")

        job = Job(id=self.store.new_id(), created=time.monotonic(), status="queued",
                  site={"id": site.id, "name": site.name, "state": site.state,
                        "lat": site.lat, "lon": site.lon},
                  history=history, horizon=horizon, rain=rain, trace=tr.spans, notices=notices)

        # 3. Runpod: hand the combined data to the GPU worker.
        if not self.s.gpu_enabled:
            self._fallback(job, "GPU endpoint not configured; using the CPU baseline.")
        else:
            payload = {"site_id": site.id, "horizon": horizon, "quantiles": CHRONOS_QUANTILES,
                       "history": [{"date": d, "value": v} for d, v in history],
                       "rain_past": [r["mm"] for r in rain["past"]] if rain else None,
                       "rain_future": [r["mm"] for r in rain["future"]] if rain else None}
            t = time.perf_counter()
            try:
                if "gpu_down" in faults:
                    raise _simulated("Runpod", "gpu_down")
                job.runpod_job_id = await runpod_client.submit(self.client, self.s, payload)
                job.runpod_status = "IN_QUEUE"
                tr.add("Runpod · submit job", (time.perf_counter() - t) * 1000)
            except UpstreamError as exc:
                tr.add("Runpod · submit job", (time.perf_counter() - t) * 1000, ok=False, detail=exc.message)
                self._fallback(job, f"{exc.message}; using the CPU baseline.")

        self.store.put(job)
        return job

    # ----------------------------------------------------------------- refresh
    async def refresh(self, job: Job) -> Job:
        if job.status == "completed" or not job.runpod_job_id:
            return job

        if time.monotonic() - job.created > self.s.gpu_deadline_s:
            await runpod_client.cancel(self.client, self.s, job.runpod_job_id)
            self._fallback(job, f"No GPU result within {int(self.s.gpu_deadline_s)} s; using the CPU baseline.")
            return job

        try:
            st = await runpod_client.status(self.client, self.s, job.runpod_job_id)
        except UpstreamError:
            return job  # transient: keep polling until the deadline

        job.runpod_status = st.get("status")
        if job.runpod_status == "IN_QUEUE":
            job.status = "queued"
        elif job.runpod_status == "IN_PROGRESS":
            job.status = "running"
        elif job.runpod_status == "COMPLETED":
            self._complete_from_gpu(job, st)
        elif job.runpod_status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            reason = st.get("error") or job.runpod_status.lower()
            self._fallback(job, f"GPU job {job.runpod_status.lower()} ({str(reason)[:200]}); using the CPU baseline.")
        return job

    def _complete_from_gpu(self, job: Job, st: dict) -> None:
        out = st.get("output") or {}
        rows = out.get("forecast") if isinstance(out, dict) else None
        valid = (isinstance(rows, list) and len(rows) == job.horizon
                 and all({"date", "p10", "p50", "p90"} <= set(r) for r in rows))
        if not valid:
            err = out.get("error") if isinstance(out, dict) else None
            self._fallback(job, f"GPU worker returned {'an error: ' + err if err else 'an unexpected output'}; "
                                "using the CPU baseline.")
            return
        end = job.trace[-1]["start_ms"] + job.trace[-1]["ms"] if job.trace else 0
        queue_ms, exec_ms = st.get("delayTime") or 0, st.get("executionTime") or 0
        job.trace.append({"name": "Runpod · queue + cold start", "start_ms": end, "ms": queue_ms,
                          "ok": True, "detail": "waiting for a GPU worker"})
        job.trace.append({"name": "Runpod · GPU execution", "start_ms": end + queue_ms, "ms": exec_ms,
                          "ok": True, "detail": f"{out.get('device', 'GPU')}, model {out.get('inference_ms', '?')} ms"})
        job.forecast = rows
        job.mode = "gpu"
        job.model = {"name": out.get("model", "Chronos-2"), "device": out.get("device"),
                     "covariates": out.get("covariates_used", False)}
        job.status = "completed"

    def _fallback(self, job: Job, notice: str) -> None:
        job.forecast = baseline.forecast(job.history, job.horizon)
        job.mode = "baseline"
        job.model = {"name": baseline.NAME, "device": "CPU", "covariates": False}
        job.status = "completed"
        job.notices.append(notice)
