# 20-minute walkthrough

Before the call: start the pod with `ALLOW_FAULT_INJECTION=true`, keep the Serverless
endpoint at 0 active workers (so the first request is a real cold start), and have the
Runpod console open on the endpoint's page in a second tab.

| Min | Slide | What to show |
|---|---|---|
| 0 to 1 | Cover; 57 mm of rain is coming. Then what? | The question, and why the answer is a range. |
| 1 to 3 | Two free APIs feed one GPU forecast | Both APIs are model inputs; keys never leave the pod. |
| 3 to 7 | Live demo | Forecast the Potomac; the steps are Runpod's job states. Run it again (warm). Failure drills: Open-Meteo down, GPU down, USGS 429. |
| 7 to 9 | One forecast, 3 services, under 3 s | The live trace, then the code path: `service.create()` → `runpod_client.submit()` → `worker/handler.py`. |
| 9 to 11 | GPU power that's free until it's used | The four numbers; click *Run burst* and show the Runpod console. Say the caveat yourself. |
| 11 to 12 | Runpod's pod proxy closes any request after 100 s | Why `/run` + polling. |
| 12 to 13 | Failures degrade, never break | Four rows, each with a test. |
| 13 to 16 | What broke, and what I learned | Silent data loss, two production bugs, the Potomac at 6x the upper bound. |
| 16 to 18 | What I'd do next; How I used AI | Batch states, basin rain + backtest, hardening. AI built it, I directed it, evidence was the referee. |
| 18 to 20 | Close | Q&A. |

Backup if the endpoint misbehaves live: the app falls back to the baseline on its own, which
is itself the failure-handling demo. Say so and move on.
