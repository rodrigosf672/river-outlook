"""Pure helpers for the worker: validate the job input and shape Chronos-2 frames.

Kept free of torch and the model so it can be unit-tested anywhere.
"""
from __future__ import annotations

import math

import pandas as pd

MAX_HISTORY = 2000
MAX_HORIZON = 14


class BadInput(ValueError):
    pass


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(inp: dict) -> dict:
    """Return a normalized copy of the job input, or raise BadInput."""
    if not isinstance(inp, dict):
        raise BadInput("input must be an object")
    horizon = inp.get("horizon")
    if not isinstance(horizon, int) or not 1 <= horizon <= MAX_HORIZON:
        raise BadInput(f"horizon must be an integer between 1 and {MAX_HORIZON}")
    history = inp.get("history")
    if not isinstance(history, list) or not 10 <= len(history) <= MAX_HISTORY:
        raise BadInput(f"history must be a list of 10 to {MAX_HISTORY} points")
    try:
        dates = pd.to_datetime([h["date"] for h in history])
        values = [h["value"] for h in history]
    except (KeyError, TypeError, ValueError) as exc:
        raise BadInput("history items need 'date' (YYYY-MM-DD) and 'value'") from exc
    if not all(_finite(v) and v >= 0 for v in values):
        raise BadInput("history values must be finite, non-negative numbers")
    if not (pd.Series(dates).diff().dropna() == pd.Timedelta(days=1)).all():
        raise BadInput("history must be consecutive daily values")

    rain_past, rain_future = inp.get("rain_past"), inp.get("rain_future")
    use_rain = rain_past is not None and rain_future is not None
    if use_rain:
        if (not isinstance(rain_past, list) or len(rain_past) != len(history)
                or not isinstance(rain_future, list) or len(rain_future) != horizon
                or not all(_finite(r) for r in rain_past + rain_future)):
            raise BadInput("rain_past must match history length and rain_future must match horizon")

    quantiles = inp.get("quantiles") or [0.1, 0.5, 0.9]
    if sorted(quantiles) != quantiles or not all(0 < q < 1 for q in quantiles) or 0.5 not in quantiles:
        raise BadInput("quantiles must be sorted, in (0, 1), and include 0.5")

    return {"dates": dates, "values": values, "horizon": horizon, "quantiles": quantiles,
            "rain_past": rain_past if use_rain else None,
            "rain_future": rain_future if use_rain else None}


def build_frames(v: dict) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Chronos-2 long format: context (target + past covariates), future covariates."""
    context = pd.DataFrame({"id": "site", "timestamp": v["dates"], "target": v["values"]})
    if v["rain_past"] is None:
        return context, None
    context["precip"] = v["rain_past"]
    future_ts = pd.date_range(v["dates"][-1] + pd.Timedelta(days=1), periods=v["horizon"], freq="D")
    future = pd.DataFrame({"id": "site", "timestamp": future_ts, "precip": v["rain_future"]})
    return context, future


def to_rows(pred: pd.DataFrame, quantiles: list[float]) -> list[dict]:
    lo, hi = str(quantiles[0]), str(quantiles[-1])
    return [{"date": ts.strftime("%Y-%m-%d"),
             "p10": round(max(0.0, float(r[lo])), 2),
             "p50": round(max(0.0, float(r["0.5"])), 2),
             "p90": round(max(0.0, float(r[hi])), 2)}
            for ts, (_, r) in zip(pred["timestamp"], pred.iterrows())]
