# Live examples

Captured from the live deployment on 2026-10-15 (`$APP` = https://qkgna8kyrv02jx-8000.proxy.runpod.net).
Long arrays are trimmed; everything else is verbatim.

## 1. Submit a forecast

```console
$ curl -s -X POST $APP/api/forecasts -H 'content-type: application/json' \
    -d '{"site_id":"01646500","horizon_days":7}'
HTTP 202
```
```json
{
  "job_id": "6e99a8561912",
  "status": "queued",
  "runpod_status": "IN_QUEUE",
  "elapsed_s": 0.2,
  "mode": null,
  "site": {
    "id": "01646500",
    "name": "POTOMAC RIVER NEAR WASH, DC LITTLE FALLS PUMP STA",
    "state": "Maryland",
    "lat": 38.949777777777776,
    "lon": -77.12763888888888
  },
  "history": "[59 days]",
  "rain": "{past: [...], future: [...]}",
  "trace": [
    {
      "name": "USGS · gauge metadata",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "USGS · daily discharge",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "Open-Meteo · rainfall",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "Runpod · submit job",
      "start_ms": 1,
      "ms": 203,
      "ok": true,
      "detail": ""
    }
  ]
}
```

## 2. Poll until it completes

```console
$ curl -s $APP/api/forecasts/6e99a8561912
0.9 queued IN_QUEUE
1.7 completed COMPLETED
```
```json
{
  "status": "completed",
  "mode": "gpu",
  "model": {
    "name": "amazon/chronos-2",
    "device": "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb",
    "covariates": true
  },
  "notices": [],
  "forecast": [
    {
      "date": "2026-10-14",
      "p10": 7040.67,
      "p50": 14146.63,
      "p90": 18572.79
    },
    "...",
    {
      "date": "2026-10-20",
      "p10": 1727.71,
      "p50": 11124.07,
      "p90": 22111.59
    }
  ],
  "trace": [
    {
      "name": "USGS · gauge metadata",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "USGS · daily discharge",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "Open-Meteo · rainfall",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "Runpod · submit job",
      "start_ms": 1,
      "ms": 203,
      "ok": true,
      "detail": ""
    },
    {
      "name": "Runpod · queue + cold start",
      "start_ms": 204,
      "ms": 1131,
      "ok": true,
      "detail": "waiting for a GPU worker"
    },
    {
      "name": "Runpod · GPU execution",
      "start_ms": 1335,
      "ms": 178,
      "ok": true,
      "detail": "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb, model 33 ms"
    }
  ]
}
```

## 3. Runpod's queue API, called directly

```console
$ curl -s -X POST https://api.runpod.ai/v2/xbni1o6sdjtjae/run \
    -H "Authorization: Bearer $RUNPOD_API_KEY" --data @worker/test_input.json
{"id":"9f9f378a-8034-4673-8277-706cf66ee300-u2","status":"IN_QUEUE"}
$ curl -s https://api.runpod.ai/v2/xbni1o6sdjtjae/status/<id> -H "Authorization: Bearer $RUNPOD_API_KEY"
```
```json
{
  "id": "9f9f378a-8034-4673-8277-706cf66ee300-u2",
  "status": "COMPLETED",
  "delayTime": 19,
  "executionTime": 124,
  "workerId": "81jcfp6201muze",
  "output": {
    "model": "amazon/chronos-2",
    "device": "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb",
    "covariates_used": true,
    "inference_ms": 17,
    "forecast": [
      "...",
      {
        "date": "2026-10-16",
        "p10": 825.55,
        "p50": 1597.23,
        "p90": 2889.16
      }
    ]
  }
}
```
```console
$ curl -s https://api.runpod.ai/v2/xbni1o6sdjtjae/health -H "Authorization: Bearer $RUNPOD_API_KEY"
{"jobs":{"completed":49,"failed":0,"inProgress":0,"inQueue":0,"retried":0},"workers":{"idle":2,"initializing":0,"ready":2,"running":1,"throttled":0,"unhealthy":0}}
```

## 4. Failures

```console
$ curl -s -X POST "$APP/api/forecasts?simulate=usgs_rate_limit" -d '{"site_id":"01646500"}' ...
HTTP/2 503
retry-after: 60
{"error":{"code":"upstream_rate_limited","message":"USGS rate limit reached (simulated). Try again shortly.","service":"USGS","retry_after":60}}

$ ... -d '{"site_id":"abc"}'                        # HTTP 422
{"error":{"code":"invalid_input","message":"site_id: String should match pattern '^\\d{8,15}$'"}}

$ ... -d '{"site_id":"01646500","horizon_days":99}' # HTTP 422
{"error":{"code":"invalid_input","message":"horizon_days: Input should be less than or equal to 14"}}

$ ... -d '{"site_id":"03085000"}'                   # HTTP 422 (gauge without flow data)
{"error":{"code":"no_discharge_data","message":"This gauge has no recent discharge readings (it may not measure flow)."}}

$ ... "?simulate=meteor"                            # HTTP 400
{"error":{"code":"unknown_fault","message":"Unknown fault(s): ['meteor']. Valid: ['gpu_down', 'openmeteo_down', 'usgs_down', 'usgs_rate_limit']."}}
```

Open-Meteo and the GPU both down still returns a forecast (HTTP 202):

```json
{
  "status": "completed",
  "mode": "baseline",
  "rain": null,
  "model": {
    "name": "persistence baseline (CPU)",
    "device": "CPU",
    "covariates": false
  },
  "notices": [
    "Simulated failure: gpu_down",
    "Simulated failure: openmeteo_down",
    "Open-Meteo is down (simulated). Forecast runs without rainfall.",
    "Runpod is down (simulated); using the CPU baseline."
  ],
  "forecast": [
    "...",
    {
      "date": "2026-10-20",
      "p10": 7518.43,
      "p50": 12600.0,
      "p90": 22090.1
    }
  ],
  "trace": [
    {
      "name": "USGS · gauge metadata",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "USGS · daily discharge",
      "start_ms": 0,
      "ms": 0,
      "ok": true,
      "detail": "cache hit"
    },
    {
      "name": "Open-Meteo · rainfall",
      "start_ms": 0,
      "ms": 0,
      "ok": false,
      "detail": "Open-Meteo is down (simulated)"
    },
    {
      "name": "Runpod · submit job",
      "start_ms": 0,
      "ms": 0,
      "ok": false,
      "detail": "Runpod is down (simulated)"
    }
  ]
}
```
