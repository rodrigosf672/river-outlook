# 20-minute walkthrough

Before the call: start the pod with `ALLOW_FAULT_INJECTION=true`, keep the Serverless
endpoint at 0 active workers (so the first request is a real cold start), and have the
Runpod console open on the endpoint's page in a second tab.

| Min | Beat | What to show |
|---|---|---|
| 0 to 2 | **Hook** | "The Potomac has 57 mm of rain coming. What will the river do?" State the brief in one line: two free APIs, one workflow, backend on Runpod. |
| 2 to 6 | **Live demo, cold** | Forecast the Potomac. Narrate the steps as they light up: *Fetching USGS + Open-Meteo*, then *Queued on Runpod: waking a GPU worker*, then *Running Chronos-2*. Hover the chart. The band widens with the horizon; don't claim it is the rain (see the README note). |
| 6 to 10 | **Trace one request** | Read the request trace from top to bottom: USGS (parallel), Open-Meteo, Runpod submit, queue and cold start, GPU execution. Then the code: `service.create()`, then `runpod_client.submit()`, then `worker/handler.py`. Run it again: cache hits, and the queue time drops on a warm worker. |
| 10 to 13 | **Failure drills** | Tick *Open-Meteo down*: the forecast still runs, without rain, with a banner. *USGS rate limit*: a 503 with a countdown on the retry button. *Runpod GPU unavailable*: the CPU baseline with a banner. Show `tests/test_failures.py` covers each one. |
| 13 to 15 | **Burst** | Click *Run burst* (9 gauges). Switch to the Runpod console tab and watch workers scale up, then idle back to zero. Mention the cost of the whole project in credits. |
| 15 to 16 | **Technical challenge** | Pick one: (a) USGS is replacing `waterservices` with the new OGC API, which has a 1,000 req/hour per IP limit, hence the caching and never retrying a 429; (b) Open-Meteo returns nulls for its oldest past days, which silently dropped the rain input until the gateway learned to trim the history window (a test now pins it); (c) the 100 s proxy limit, which is why this uses `/run` + polling. |
| 16 to 17 | **Reality check** | The rain fell: the Potomac hit 12,600 cfs on Oct 13, about 6x the forecast's upper bound. Own it: point rain plus 90 days of history can't anticipate a flood. That motivates basin rain and a backtest. |
| 17 to 19 | **Tradeoffs and next steps** | Be honest that one gauge doesn't need a GPU, and say where it does (batching a state's gauges into one job, bigger models). Then cover the in-memory job store, point vs. basin rainfall, and backtesting the 80% band. Explain how AI was used. |
| 19 to 20 | **Close** | The README's local quickstart runs the whole stack without credits via `worker/local_runpod.py`, and deploying is two images: a Pod and an endpoint. |

Backup if the endpoint misbehaves live: the app falls back to the baseline on its own, which
is itself the failure-handling demo. Say so and move on.
