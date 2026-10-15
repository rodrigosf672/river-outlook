"""In-memory store for forecasts in flight.

The brief rules out a database, and one gateway process is enough here. The
tradeoff: jobs vanish on restart and the store is not shared across replicas.
A Redis (or Runpod's own job history) would remove both limits.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

TTL_S = 1800  # Runpod keeps /run results for 30 minutes; match it


@dataclass
class Job:
    id: str
    created: float
    status: str                      # queued | running | completed
    site: dict
    history: list[tuple[str, float]]
    horizon: int
    rain: dict | None                # {"past": [...], "future": [...]} or None
    trace: list[dict]
    notices: list[str] = field(default_factory=list)
    runpod_job_id: str | None = None
    runpod_status: str | None = None
    mode: str | None = None          # gpu | baseline
    model: dict | None = None
    forecast: list[dict] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "mode": self.mode,
            "runpod_status": self.runpod_status,
            "elapsed_s": round(time.monotonic() - self.created, 1),
            "site": self.site,
            "horizon": self.horizon,
            "history": [{"date": d, "value": v} for d, v in self.history],
            "rain": self.rain,
            "forecast": self.forecast,
            "model": self.model,
            "notices": self.notices,
            "trace": self.trace,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def put(self, job: Job) -> None:
        self._evict()
        self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        self._evict()
        return self._jobs.get(job_id)

    def _evict(self) -> None:
        now = time.monotonic()
        for jid in [j for j, job in self._jobs.items() if now - job.created > TTL_S]:
            del self._jobs[jid]
