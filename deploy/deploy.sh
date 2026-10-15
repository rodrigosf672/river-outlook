#!/usr/bin/env bash
# Deploy River Outlook to Runpod: secret -> Serverless GPU endpoint -> CPU pod.
# These are the exact calls used for the live deployment.
#
#   RUNPOD_API_KEY=...  ./deploy/deploy.sh [image-tag]
#
# Needs: curl, python3, runpodctl (brew install runpod/runpodctl/runpodctl).
# The images are built by .github/workflows/images.yml; image-tag defaults to "latest".
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-latest}"
API=https://api.runpod.io/v2
KEY="${RUNPOD_API_KEY:-$(sed -n "s/^apikey = '\(.*\)'$/\1/p" ~/.runpod/config.toml 2>/dev/null)}"
[ -n "$KEY" ] || { echo "Set RUNPOD_API_KEY (or run 'runpodctl doctor')." >&2; exit 1; }
SECRET_NAME=river_outlook_runpod_key
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

# 1. Store the key the gateway uses as a Runpod secret (skipped if it exists).
#    Better: a restricted key scoped to this endpoint (console > Settings > API Keys).
GATEWAY_KEY="${GATEWAY_RUNPOD_KEY:-$KEY}"
if curl -sf "$API/account/secrets" -H "Authorization: Bearer $KEY" | grep -q "\"name\":\"$SECRET_NAME\""; then
  echo "secret $SECRET_NAME exists"
else
  python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "value": sys.argv[2]}))' \
    "$SECRET_NAME" "$GATEWAY_KEY" |
    curl -sf -X POST "$API/account/secrets" -H "Authorization: Bearer $KEY" \
      -H "Content-Type: application/json" --data @- >/dev/null
  echo "secret $SECRET_NAME created"
fi

# 2. Serverless GPU endpoint for the worker (scales to zero; see endpoint.json).
ENDPOINT_ID=$(python3 -c 'import json,sys; d=json.load(open("endpoint.json")); d["image"]=d["image"].rsplit(":",1)[0]+":"+sys.argv[1]; print(json.dumps(d))' "$TAG" |
  curl -sf -X POST "$API/serverless" -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" --data @- | json '["id"]')
echo "endpoint $ENDPOINT_ID"

# 3. CPU pod for the gateway + frontend. The key arrives via the secret reference.
ENV=$(python3 -c 'import json,sys; d=json.load(open("pod-env.json")); d["RUNPOD_ENDPOINT_ID"]=sys.argv[1]; print(json.dumps(d))' "$ENDPOINT_ID")
POD_ID=$(runpodctl pod create --name river-outlook-gateway --compute-type CPU \
  --image "ghcr.io/rodrigosf672/river-outlook-gateway:$TAG" --ports 8000/http \
  --container-disk-in-gb 5 --ssh=false --env "$ENV" | json '["id"]')
URL="https://$POD_ID-8000.proxy.runpod.net"
echo "pod $POD_ID"

# 4. Wait until the gateway answers through Runpod's proxy.
for _ in $(seq 1 60); do
  if curl -sf "$URL/api/health" >/dev/null; then
    echo "ready: $URL"; curl -s "$URL/api/health"; echo; exit 0
  fi
  sleep 5
done
echo "pod did not answer within 5 minutes: $URL" >&2; exit 1
