# River Outlook

[![tests](https://github.com/rodrigosf672/river-outlook/actions/workflows/tests.yml/badge.svg)](https://github.com/rodrigosf672/river-outlook/actions/workflows/tests.yml)
[![images](https://github.com/rodrigosf672/river-outlook/actions/workflows/images.yml/badge.svg)](https://github.com/rodrigosf672/river-outlook/actions/workflows/images.yml)

**Live app:** https://qkgna8kyrv02jx-8000.proxy.runpod.net (gateway on a Runpod CPU pod,
forecasts on a Runpod Serverless GPU endpoint)

**What will this river do next week?** Pick a USGS river gauge and River Outlook
returns a 7-day probabilistic flow forecast that accounts for the rain on its way.

It combines two free public APIs in one workflow:

1. **USGS Water Data API**: the gauge's location and its last 90 days of daily discharge.
2. **Open-Meteo**: daily rainfall at the gauge, the past 92 days plus the forecast.

Then it hands both series to **Chronos-2**, a time-series foundation model, running
on a **Runpod Serverless GPU** endpoint. Rainfall is passed as a *covariate*: past
rain alongside past flow, plus the rain forecast for the days being predicted. If
the GPU path fails, the gateway answers with a CPU statistical baseline instead.

> **Does the rain input help? Not proven yet.** On the Potomac (2026-10-09, 57 mm
> forecast over 7 days), adding rain made the day-7 forecast *lower and narrower*
> (median 1,597 cfs, 90th percentile 2,889) than flow alone (2,042 and 3,955). The
> model learns the rain-to-flow link in context from only 60 to 90 days, so its
> effect is unverified.
>
> **What actually happened:** the rain fell, and the Potomac rose from 1,430 cfs (Oct 9)
> to 12,600 cfs (Oct 13). Both forecasts missed the rise; even the rain-aware 90th
> percentile was 2,889 cfs. One event proves little either way, which is why a proper
> backtest is the first item under next steps.

![River Outlook: Potomac forecast, request trace, and burst run](docs/screenshot.png)

> Exploratory tool, not a flood warning system.

## Architecture

```mermaid
flowchart LR
    B[Browser<br/>frontend/] -- "POST /api/forecasts<br/>GET /api/forecasts/{id} (poll)" --> G
    subgraph Pod["Runpod CPU Pod"]
      G[Gateway<br/>FastAPI · gateway/]
    end
    G -- "site + daily discharge" --> U[(USGS Water Data API)]
    G -- "rainfall past + forecast" --> O[(Open-Meteo)]
    G -- "/run, /status" --> S
    subgraph SL["Runpod Serverless (GPU, scales 0 to N)"]
      S[Worker<br/>Chronos-2 · worker/]
    end
```

```text
Browser ──► Gateway (Runpod CPU Pod) ──┬──► USGS        discharge history
             holds all API keys        ├──► Open-Meteo  rainfall
             cache · retries · limits  └──► Runpod Serverless GPU ──► Chronos-2 forecast
                                             (fallback: CPU baseline in the gateway)
```

**Why this split.** The gateway is always on, cheap, and holds every secret. The
model runs on Serverless GPUs that cost nothing while idle and scale out when many
forecasts arrive at once (try the *burst* button). The browser never sees a key.

### One request, end to end

1. The browser `POST`s `{site_id, horizon_days}`. The gateway validates it (8 to 15 digit
   site id, horizon 1 to 14).
2. The gateway fetches gauge metadata and discharge from USGS **in parallel**, cleans the
   series (interpolates gaps of up to 7 days and says so, cuts at longer outages), then
   fetches rainfall from Open-Meteo using the gauge's coordinates.
3. It aligns both series by date and submits a job to the Runpod endpoint with `/run`.
   The response is `202` with a job id and `runpod_status: IN_QUEUE`.
4. The browser polls `GET /api/forecasts/{id}`. Each poll asks Runpod for `/status` and
   maps it to the loading UI: *queued (waking a GPU)*, then *running*, then *done*.
5. On `COMPLETED`, the gateway validates the output and adds Runpod's `delayTime` (queue
   and cold start) and `executionTime` to the request trace shown under the chart.

**Why async `/run` and not `/runsync`?** A cold worker has to start and load the
model. Runpod's pod proxy closes any connection after 100 seconds (Cloudflare
returns 524), so holding one long request open is fragile. Short polls also
turn Runpod's job states into a real loading state.

## Run it locally (no GPU or credits needed)

```bash
# 1. The worker behind a local stand-in for the Runpod queue API (real Chronos-2, on CPU)
cd worker
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python local_runpod.py                  # :8090, simulates a 4 s cold start

# 2. The gateway, which also serves the frontend
cd gateway
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
RUNPOD_BASE=http://localhost:8090 RUNPOD_ENDPOINT_ID=local RUNPOD_API_KEY=dev \
ALLOW_FAULT_INJECTION=true .venv/bin/uvicorn app.main:app --port 8000

# 3. Open http://localhost:8000
```

Skip step 1 and the `RUNPOD_*` variables to run with the CPU baseline only.
To test the real handler through the Runpod SDK: `cd worker && python handler.py`
(it reads `test_input.json`, real Potomac data).

## Deploy on Runpod

### Images

Every push to `main` builds both images on x86 runners and pushes them to GHCR
(`.github/workflows/images.yml`), tagged `latest` and with the commit SHA:

- `ghcr.io/rodrigosf672/river-outlook-worker` (Runpod PyTorch base, Chronos-2 weights baked in)
- `ghcr.io/rodrigosf672/river-outlook-gateway` (gateway + frontend)

The packages are public, so Runpod pulls them without registry credentials.

### One command

```bash
brew install runpod/runpodctl/runpodctl     # or: curl -sSL https://cli.runpod.net | bash
runpodctl doctor                            # saves your API key to ~/.runpod/config.toml
./deploy/deploy.sh <image-tag>              # defaults to "latest"
```

[`deploy/deploy.sh`](deploy/deploy.sh) makes the same calls used for the live deployment:

1. **Secret.** It stores the key the gateway uses as the Runpod secret
   `river_outlook_runpod_key` (`POST /v2/account/secrets`). Set `GATEWAY_RUNPOD_KEY` to
   a **restricted key** scoped to the endpoint instead of your account key.
2. **Serverless GPU endpoint** from [`deploy/endpoint.json`](deploy/endpoint.json)
   (`POST /v2/serverless`). It's queue-based, can use three GPU pools (`ADA_24`, `AMPERE_24`,
   `AMPERE_16`) for availability, needs CUDA 12.8 or newer, has 0 to 3 workers with a 60 s
   idle timeout, uses FlashBoot, and has a 120 s execution timeout.
3. **CPU pod** for the gateway (`runpodctl pod create --compute-type CPU`), on port
   `8000/http`, with env from [`deploy/pod-env.json`](deploy/pod-env.json). The key is a
   secret reference, `{{ RUNPOD_SECRET_river_outlook_runpod_key }}`, never a literal value.
4. It waits for `https://<POD_ID>-8000.proxy.runpod.net/api/health` and prints the URL.

**Measured on the live deployment (Oct 2026):**

- **First cold start:** 56 s of `delayTime` (worker start, image pull, model load). Execution took 346 ms, of which inference was 180 ms.
- **A warm forecast:** 1.4 s end to end in the browser. The Runpod queue took 142 ms and inference 33 ms.
- **Burst of 9 gauges:** 10.6 s.
- **Cost:** the CPU pod is $0.06/hour, and the endpoint costs nothing while idle.

**Teardown:** `runpodctl pod delete <pod-id>`, then `runpodctl serverless delete <endpoint-id>`.

**Updating:** after a new image builds, `runpodctl pod update <pod-id> --image ghcr.io/rodrigosf672/river-outlook-gateway:<sha>`.
For the worker, `PATCH /v2/serverless/<id>` with the new `image`.

To host the frontend elsewhere (e.g. GitHub Pages), set `window.RIVER_API_BASE` in
`frontend/config.js` to the pod URL and set `ALLOWED_ORIGINS` on the gateway.

## Environment variables

| Variable | Where | Required | Purpose |
|---|---|---|---|
| `RUNPOD_API_KEY` | gateway | for GPU | Calls the Serverless endpoint. Server-side only. |
| `RUNPOD_ENDPOINT_ID` | gateway | for GPU | Which endpoint runs the worker. |
| `USGS_API_KEY` | gateway | no | Free api.data.gov key; raises the USGS rate limit. |
| `GPU_DEADLINE_S` | gateway | no (120) | After this, cancel the GPU job and serve the baseline. |
| `HISTORY_DAYS` | gateway | no (90) | Days of discharge history to request. |
| `CACHE_TTL_S` / `STALE_TTL_S` | gateway | no (900 / 21600) | Fresh cache window / how long stale data may be served when an upstream fails. |
| `RATE_LIMIT_PER_MIN` | gateway | no (30) | Forecasts per client IP per minute. |
| `ALLOWED_ORIGINS` | gateway | no (`*`) | CORS, if the frontend is hosted elsewhere. |
| `ALLOW_FAULT_INJECTION` | gateway | no (false) | Enables `?simulate=` failure drills for demos. |
| `MODEL_ID` | worker | no | Defaults to `amazon/chronos-2`. |

See `.env.example`.

## Free-tier limits and how the app handles them

| Service | Limit | What we do |
|---|---|---|
| **USGS Water Data API** | About 1,000 requests/hour per IP without a key; higher with a free api.data.gov key | Site metadata is cached 24 h and discharge 15 min, so a repeat forecast costs 0 calls. A 429 is **never retried** (that burns quota); the client gets `503` + `Retry-After` and the UI counts down. |
| **Open-Meteo** | Free for non-commercial use: 10,000/day, 5,000/hour, 600/minute. `past_days` is at most 92. | 1 call per forecast, cached 15 min. If it fails, the forecast **still runs without rain** and says so. Null values for its oldest past days are handled by trimming the history window rather than dropping the rain input. |
| **Runpod Serverless** | Billed per second of worker time; `/run` results kept 30 minutes; the pod proxy times out at 100 s | Scales to zero when idle. Async `/run` + polling avoids the proxy timeout. A job TTL and the `GPU_DEADLINE_S` cancel stop jobs from piling up. |
| **This gateway** | `RATE_LIMIT_PER_MIN` per client IP | Protects the shared upstream quotas from one noisy client. |

## Failure handling

| What fails | User sees | HTTP |
|---|---|---|
| Invalid site id or horizon | Inline form error, and the server rejects it too | 422 `invalid_input` |
| Gauge doesn't measure flow (e.g. Monongahela at Braddock) | "This gauge doesn't measure flow" | 422 `no_discharge_data` |
| USGS rate limited | "USGS is rate limiting us", with a countdown on the retry button | 503 `upstream_rate_limited` + `Retry-After` |
| USGS down / timing out | Cached data with a warning if we have it; otherwise a clear error | 202 with notice, or 503 |
| Open-Meteo down | Forecast without rain, with a warning banner | 202 with notice |
| Runpod submit fails / job FAILED / no result within deadline | CPU baseline forecast, with a warning banner | 202, `mode: "baseline"` |
| Gateway unreachable mid-poll | Polls retry up to 3 times before showing an error | n/a |

5xx responses and timeouts from USGS and Open-Meteo are retried twice with backoff.
Set `ALLOW_FAULT_INJECTION=true` and use **Failure drills** in the UI (or
`?simulate=openmeteo_down,usgs_rate_limit,usgs_down,gpu_down`) to trigger each case live.

## Security and cost guardrails

- **Keys stay server-side.** The browser talks only to the gateway. The Runpod key
  reaches the pod as a Runpod secret, and a test asserts that no key appears in any
  response.
- **Least privilege (recommended).** The live deployment uses an account key. Use a
  restricted key that can only run this endpoint (Runpod console → Settings → API
  Keys), and rotate any key that was ever shared.
- **Bounded GPU spend from a public URL.** There's a per-IP rate limit (30 forecasts per
  minute) and a 3-worker cap. Each job has a 120 s execution timeout, a queue TTL and a
  gateway deadline that cancels it. Idle workers scale to zero after 60 s.
- **Input validation happens before any upstream call**, in the browser and the gateway,
  and again in the worker, which rejects malformed jobs with an error result.
- **Failure drills are opt-in** (`ALLOW_FAULT_INJECTION`) and only affect the request that
  asks for them. They're on for the live demo.

## Tests

```bash
cd gateway && .venv/bin/pytest -q    # 16 tests, upstreams mocked with respx
cd worker  && pytest -q              # 8 tests, input validation + frame shaping (no model)
```

They cover the full workflow (both APIs feeding the GPU job, secrets never leaking to the
client, status transitions, trace spans) and every failure path in the table above. CI
runs both suites (`.github/workflows/tests.yml`).

## Repository layout

```
gateway/   FastAPI gateway: app/{main,service,usgs,openmeteo,runpod_client,baseline,series,http,jobs}.py
worker/    Runpod Serverless handler (Chronos-2), local Runpod stand-in, tests
frontend/  Static HTML/CSS/JS, no build step; served by the gateway
deploy/    deploy.sh plus the endpoint and pod configs used for the live deployment
docs/      Screenshot and demo script
```

## Known limitations and next steps

- **Is a GPU necessary?** Not for one gauge: Chronos-2 forecasts a single site in under
  a second on CPU. The GPU matters for scale: batch many gauges per request (the
  burst case), or move to larger models and longer context windows. The next step
  is to batch a whole state's gauges into one GPU job.
- **In-memory job store**: jobs are lost on restart and not shared across replicas. Redis would fix both.
- **Point rainfall**: the rain is at the gauge, not across the upstream watershed. Using
  basin-averaged precipitation would be the biggest accuracy gain.
- **No accuracy evaluation yet**: next is a backtest against held-out USGS weeks, with and
  without rain, reporting error and coverage of the 80% band. That settles whether the rain
  input earns its place (see the note at the top).
- **Cold starts**: the first worker took 56 s (image pull and model load). Next, compare
  Runpod's cached models (`--model-reference`) against baking the weights into the image.
- **USGS outages**: gaps of up to 7 days are interpolated and disclosed in the UI (Missouri
  at Hermann had a real 4-day gap). Longer gaps cut the history.
- **Not done**: no USGS API key configured on the live pod (it's optional; the app works
  within the keyless limit thanks to caching), and no restricted Runpod key yet (see guardrails).

## How AI was used

> _Draft: edit to reflect your own process before submitting._
> I used Claude Code to scaffold the gateway, worker, frontend, and tests from my design, and to
> check the USGS, Open-Meteo, Runpod, and Chronos-2 APIs against their live behavior. I reviewed
> and ran every part, and can walk through or change any of it.

## Data and licenses

USGS water data is public domain. Open-Meteo data is CC BY 4.0. Chronos-2 is by Amazon Science
(Apache-2.0). This project is independent and not affiliated with USGS, Open-Meteo, or Amazon.
