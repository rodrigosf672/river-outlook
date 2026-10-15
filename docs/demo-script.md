# 20-minute walkthrough

Before the call: start the pod with `ALLOW_FAULT_INJECTION=true`, keep the Serverless
endpoint at 0 active workers (so the first request is a real cold start), and have the
Runpod console open on the endpoint's page in a second tab.

| Min | Slide | What to show |
|---|---|---|
| 0 to 1 | Cover, The question | "The Potomac has 57 mm of rain coming. What will the river do?" |
| 1 to 3 | Two free APIs feed one GPU forecast | Both APIs are model inputs; the browser only talks to the gateway. |
| 3 to 6 | Live demo | Forecast the Potomac; narrate the steps (they follow Runpod's real job status). Hover the chart. Run it again: cache hits, warm worker. |
| 6 to 8 | One forecast, 3 services, under 3 s | Read the trace top to bottom, then the code path: `service.create()` → `runpod_client.submit()` → `worker/handler.py`. |
| 8 to 10 | GPU power that's free until it's used | The six measured numbers. Click *Run burst* and show the Runpod console scaling. Say the caveat yourself. |
| 10 to 11 | Why the browser polls | 100 s proxy limit → `/run` + polling; job states become the loading UI. |
| 11 to 13 | Failures degrade, never break | Failure drills live: Open-Meteo down, GPU down, USGS 429 with countdown. |
| 13 to 14 | Quotas, keys and spend stay protected | Free-tier limits, spend caps on a public URL, 0 key matches in live responses. |
| 14 to 16 | What broke, and what I learned | Silent data loss; two production bugs; the Potomac hit 6x the forecast's upper bound. |
| 16 to 17 | 26 tests, half of them failure paths | Point at `tests/test_failures.py`. |
| 17 to 19 | What I'd do with more time, How I used AI | Batch whole states on the GPU, basin rain, backtest. AI built it; I directed it; evidence was the referee. |
| 19 to 20 | Close | App, code, `deploy/deploy.sh`, run locally without credits. Q&A; appendix slides as backup. |

Backup if the endpoint misbehaves live: the app falls back to the baseline on its own, which
is itself the failure-handling demo. Say so and move on.
