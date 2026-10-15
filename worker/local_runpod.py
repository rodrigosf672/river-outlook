"""Local stand-in for the Runpod Serverless queue API, for development only.

Serves the same routes the gateway uses in production (POST /{endpoint}/run,
GET /{endpoint}/status/{id}, POST /{endpoint}/cancel/{id}) and runs the real
handler, with a simulated cold start. Lets you run the whole stack on a laptop:

    python local_runpod.py           # listens on :8090, endpoint id "local"
    RUNPOD_BASE=http://localhost:8090 RUNPOD_ENDPOINT_ID=local RUNPOD_API_KEY=dev \
        uvicorn app.main:app          # in gateway/
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import uvicorn
from fastapi import FastAPI, HTTPException

from handler import handler

COLD_START_S = float(os.getenv("COLD_START_S", "4"))
app = FastAPI(title="local Runpod stand-in")
jobs: dict[str, dict] = {}
warm = False


async def _execute(job_id: str, payload: dict) -> None:
    global warm
    job = jobs[job_id]
    if not warm:
        await asyncio.sleep(COLD_START_S)  # pretend to boot a worker
        warm = True
    job["delayTime"] = round((time.time() - job["_t"]) * 1000)
    job["status"] = "IN_PROGRESS"
    t = time.time()
    output = await asyncio.to_thread(handler, {"id": job_id, "input": payload})
    job["executionTime"] = round((time.time() - t) * 1000)
    job["output"], job["status"] = output, "COMPLETED"


@app.post("/{endpoint}/run")
async def run(endpoint: str, body: dict):
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"id": job_id, "status": "IN_QUEUE", "_t": time.time()}
    asyncio.create_task(_execute(job_id, body.get("input", {})))
    return {"id": job_id, "status": "IN_QUEUE"}


@app.get("/{endpoint}/status/{job_id}")
async def status(endpoint: str, job_id: str):
    if job_id not in jobs:
        raise HTTPException(404)
    return {k: v for k, v in jobs[job_id].items() if not k.startswith("_")}


@app.post("/{endpoint}/cancel/{job_id}")
async def cancel(endpoint: str, job_id: str):
    if job_id in jobs:
        jobs[job_id]["status"] = "CANCELLED"
    return {"id": job_id, "status": "CANCELLED"}


if __name__ == "__main__":
    uvicorn.run(app, port=int(os.getenv("PORT", "8090")))
