"""CPU fallback forecast, used whenever the GPU path is unavailable.

Persistence with an empirical uncertainty band: the median stays at the last
observed flow, and the 10th/90th percentiles come from how much this river's
flow actually changed over k days within the history window. Simple, honest,
and always available.
"""
from __future__ import annotations

import math
import statistics

from .series import future_dates

NAME = "persistence baseline (CPU)"


def _quantile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[max(0, min(98, round(q * 100) - 1))]


def forecast(history: list[tuple[str, float]], horizon: int) -> list[dict]:
    flows = [v for _, v in history]
    last = flows[-1]
    out = []
    for k, day in enumerate(future_dates(history[-1][0], horizon), start=1):
        # Log-ratios of flow k days apart; +1 guards against zero flow.
        ratios = [math.log((flows[i + k] + 1) / (flows[i] + 1)) for i in range(len(flows) - k)]
        lo, hi = (_quantile(ratios, 0.1), _quantile(ratios, 0.9)) if ratios else (0.0, 0.0)
        out.append({
            "date": day,
            "p10": round(max(0.0, (last + 1) * math.exp(min(lo, 0.0)) - 1), 2),
            "p50": round(last, 2),
            "p90": round((last + 1) * math.exp(max(hi, 0.0)) - 1, 2),
        })
    return out
