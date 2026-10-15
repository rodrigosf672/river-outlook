"""HTTP surface of the gateway.

POST /api/forecasts            start a forecast (202 + job, or completed baseline)
GET  /api/forecasts/{job_id}   poll it; each poll advances the Runpod job
GET  /api/health               liveness + which integrations are configured
GET  /                         the frontend (same origin, so one URL to share)
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .errors import InputError, UpstreamError
from .jobs import JobStore
from .service import FAULTS, ForecastService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))


class ForecastRequest(BaseModel):
    # USGS site numbers are 8 to 15 digits.
    site_id: str = Field(pattern=r"^\d{8,15}$", examples=["01646500"])
    horizon_days: int = Field(default=7, ge=1, le=14)


class RateLimiter:
    """Sliding one-minute window per client IP. Protects our upstream quotas."""

    def __init__(self, per_min: int) -> None:
        self.per_min = per_min
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = time.monotonic(), self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_min:
            return False
        q.append(now)
        return True


def client_ip(request: Request) -> str:
    # Runpod's proxy sits behind Cloudflare, which sets CF-Connecting-IP.
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def error(status: int, code: str, message: str, **extra) -> JSONResponse:
    headers = {"Retry-After": str(extra["retry_after"])} if extra.get("retry_after") else None
    return JSONResponse({"error": {"code": code, "message": message, **extra}},
                        status_code=status, headers=headers)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=s.http_timeout_s, transport=transport) as client:
            app.state.service = ForecastService(s, client, JobStore())
            yield

    app = FastAPI(title="River Outlook gateway", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    limiter = RateLimiter(s.rate_limit_per_min)

    @app.exception_handler(UpstreamError)
    async def upstream_error(_: Request, exc: UpstreamError):
        if exc.kind == "rate_limited":
            return error(503, "upstream_rate_limited", f"{exc.message}. Try again shortly.",
                         service=exc.service, retry_after=exc.retry_after or 60)
        status = 503 if exc.kind == "unavailable" else 502
        return error(status, f"upstream_{exc.kind}", exc.message, service=exc.service)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "body"
        return error(422, "invalid_input", f"{field}: {first.get('msg', 'invalid value')}")

    @app.exception_handler(InputError)
    async def input_error(_: Request, exc: InputError):
        return error(422, exc.code, exc.message)

    @app.get("/api/health")
    async def health():
        return {"ok": True, "gpu_configured": s.gpu_enabled, "usgs_key": bool(s.usgs_api_key),
                "fault_injection": s.allow_fault_injection}

    @app.post("/api/forecasts", status_code=202)
    async def create_forecast(body: ForecastRequest, request: Request,
                              simulate: str | None = Query(default=None)):
        if not limiter.allow(client_ip(request)):
            return error(429, "rate_limited", "Too many forecasts from this address; wait a minute.",
                         retry_after=60)
        faults = {f.strip() for f in (simulate or "").split(",") if f.strip()}
        if faults and not s.allow_fault_injection:
            return error(400, "fault_injection_disabled", "Failure simulation is disabled on this server.")
        if faults - FAULTS:
            return error(400, "unknown_fault", f"Unknown fault(s): {sorted(faults - FAULTS)}. "
                                               f"Valid: {sorted(FAULTS)}.")
        job = await request.app.state.service.create(body.site_id, body.horizon_days, faults)
        return job.public()

    @app.get("/api/forecasts/{job_id}")
    async def get_forecast(job_id: str, request: Request):
        svc: ForecastService = request.app.state.service
        job = svc.store.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown or expired forecast id.")
        return (await svc.refresh(job)).public()

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
