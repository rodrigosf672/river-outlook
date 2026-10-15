"""Runtime settings, read once from environment variables.

Secrets (USGS_API_KEY, RUNPOD_API_KEY) only ever live here, server-side.
The frontend never sees them; it talks to this gateway and nothing else.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Upstream APIs
    usgs_base: str = os.getenv("USGS_BASE", "https://api.waterdata.usgs.gov/ogcapi/v1")
    usgs_api_key: str | None = os.getenv("USGS_API_KEY") or None
    openmeteo_base: str = os.getenv("OPENMETEO_BASE", "https://api.open-meteo.com/v1")
    user_agent: str = os.getenv("USER_AGENT", "river-outlook/0.1 (Runpod DevRel demo)")

    # Runpod Serverless GPU endpoint (optional: without it we serve the CPU baseline)
    runpod_api_key: str | None = os.getenv("RUNPOD_API_KEY") or None
    runpod_endpoint_id: str | None = os.getenv("RUNPOD_ENDPOINT_ID") or None
    runpod_base: str = os.getenv("RUNPOD_BASE", "https://api.runpod.ai/v2")
    # Give up on the GPU and fall back to the baseline after this many seconds.
    gpu_deadline_s: float = float(os.getenv("GPU_DEADLINE_S", "120"))

    # Behaviour
    history_days: int = int(os.getenv("HISTORY_DAYS", "90"))
    http_timeout_s: float = float(os.getenv("HTTP_TIMEOUT_S", "10"))
    cache_ttl_s: float = float(os.getenv("CACHE_TTL_S", "900"))
    stale_ttl_s: float = float(os.getenv("STALE_TTL_S", "21600"))
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
    allowed_origins: list[str] = field(default_factory=lambda: _csv("ALLOWED_ORIGINS", "*"))
    # Lets the demo trigger failures on purpose (?simulate=...). Off by default.
    allow_fault_injection: bool = _bool("ALLOW_FAULT_INJECTION")

    @property
    def gpu_enabled(self) -> bool:
        return bool(self.runpod_api_key and self.runpod_endpoint_id)


def get_settings() -> Settings:
    return Settings()
