"""Runpod Serverless worker: probabilistic river forecast with Chronos-2.

Input  (job["input"]): history [{date, value}], horizon, optional rain_past /
                       rain_future (mm/day, used as covariates), quantiles.
Output: {forecast: [{date, p10, p50, p90}], model, device, covariates_used,
         inference_ms}  or  {error: "..."} for bad input.

The model loads once per worker, at import, so warm requests skip it.
"""
from __future__ import annotations

import os
import time

import runpod
import torch
from chronos import Chronos2Pipeline

from forecast import BadInput, build_frames, to_rows, validate

MODEL_ID = os.getenv("MODEL_ID", "amazon/chronos-2")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DEVICE_NAME = torch.cuda.get_device_name(0) if DEVICE == "cuda" else "CPU"

_t = time.perf_counter()
PIPELINE = Chronos2Pipeline.from_pretrained(MODEL_ID, device_map=DEVICE)
print(f"Loaded {MODEL_ID} on {DEVICE_NAME} in {time.perf_counter() - _t:.1f}s", flush=True)


def handler(job: dict) -> dict:
    try:
        v = validate(job.get("input"))
    except BadInput as exc:
        return {"error": f"invalid input: {exc}"}

    context, future = build_frames(v)
    t = time.perf_counter()
    pred = PIPELINE.predict_df(
        context, future_df=future, prediction_length=v["horizon"],
        quantile_levels=v["quantiles"], id_column="id",
        timestamp_column="timestamp", target="target",
    )
    return {
        "forecast": to_rows(pred, v["quantiles"]),
        "model": MODEL_ID,
        "device": DEVICE_NAME,
        "covariates_used": future is not None,
        "inference_ms": round((time.perf_counter() - t) * 1000),
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
