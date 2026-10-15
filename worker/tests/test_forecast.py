import pandas as pd
import pytest

from forecast import BadInput, build_frames, to_rows, validate


def job(n=30, horizon=7, rain=True):
    dates = pd.date_range("2026-09-01", periods=n, freq="D")
    inp = {"horizon": horizon, "history": [{"date": d.strftime("%Y-%m-%d"), "value": 100.0 + i}
                                           for i, d in enumerate(dates)]}
    if rain:
        inp["rain_past"] = [0.0] * n
        inp["rain_future"] = [5.0] * horizon
    return inp


def test_valid_input_builds_aligned_frames():
    context, future = build_frames(validate(job()))
    assert list(context.columns) == ["id", "timestamp", "target", "precip"]
    assert len(future) == 7
    assert future["timestamp"].iloc[0] == context["timestamp"].iloc[-1] + pd.Timedelta(days=1)


def test_missing_rain_means_univariate():
    context, future = build_frames(validate(job(rain=False)))
    assert future is None and "precip" not in context


@pytest.mark.parametrize("mutate, msg", [
    (lambda j: j.update(horizon=0), "horizon"),
    (lambda j: j.update(history=j["history"][:5]), "history"),
    (lambda j: j["history"][3].update(value=-1), "non-negative"),
    (lambda j: j["history"].pop(10), "consecutive"),
    (lambda j: j.update(rain_future=[1.0]), "rain_future"),
])
def test_rejects_bad_input(mutate, msg):
    inp = job()
    mutate(inp)
    with pytest.raises(BadInput, match=msg):
        validate(inp)


def test_to_rows_clips_negative_quantiles():
    pred = pd.DataFrame({"timestamp": pd.date_range("2026-10-01", periods=2),
                         "0.1": [-5.0, 1.0], "0.5": [2.0, 3.0], "0.9": [4.0, 6.0]})
    rows = to_rows(pred, [0.1, 0.5, 0.9])
    assert rows[0] == {"date": "2026-10-01", "p10": 0.0, "p50": 2.0, "p90": 4.0}
