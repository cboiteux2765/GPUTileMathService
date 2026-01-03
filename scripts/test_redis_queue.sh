#!/usr/bin/env bash
# Self-contained Redis queue smoke test (Feature 2)
# Requires: bash, curl, python3, and python package "redis" installed in the current env.

set -u

HOST="${HOST:-http://127.0.0.1:8000}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
STREAM="${STREAM:-queue:jobs}"
TIMEOUT_SEC="${TIMEOUT_SEC:-10}"

PASS_COUNT=0
FAIL_COUNT=0

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
NC="\033[0m"

pass() { echo -e "${GREEN}PASS${NC} - $1"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo -e "${RED}FAIL${NC} - $1"; FAIL_COUNT=$((FAIL_COUNT+1)); }
info() { echo -e "${YELLOW}INFO${NC} - $1"; }

http_get() {
  local url="$1"
  local body_file
  body_file="$(mktemp)"
  local code
  code="$(curl -sS -o "$body_file" -w "%{http_code}" "$url" 2>/dev/null || echo "000")"
  echo "$code"
  cat "$body_file"
  rm -f "$body_file"
}

http_post_json() {
  local url="$1"
  local json="$2"
  local body_file
  body_file="$(mktemp)"
  local code
  code="$(curl -sS -o "$body_file" -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -d "$json" \
    "$url" 2>/dev/null || echo "000")"
  echo "$code"
  cat "$body_file"
  rm -f "$body_file"
}

extract_json_path() {
  # usage: extract_json_path "a.b.c"
  # reads JSON from stdin; prints value or empty string
  local path="$1"
  python3 -c '
import sys, json
path = sys.argv[1]
data = sys.stdin.read().strip()
if not data:
    print(""); raise SystemExit(0)
try:
    obj = json.loads(data)
except Exception:
    print(""); raise SystemExit(0)

cur = obj
for key in path.split("."):
    if isinstance(cur, dict) and key in cur:
        cur = cur[key]
    else:
        print(""); raise SystemExit(0)

if cur is None:
    print("")
elif isinstance(cur, (dict, list)):
    print(json.dumps(cur))
else:
    print(cur)
' "$path"
}

contains() { [[ "$1" == *"$2"* ]]; }

python_has_redis() {
  python3 - <<'PY' >/dev/null 2>&1
import redis
print("ok")
PY
}

redis_ping() {
  REDIS_URL="$REDIS_URL" python3 - <<'PY'
import os, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
print("PONG" if r.ping() else "NO")
PY
}

stream_find_msg_id_for_job() {
  local job_id="$1"
  REDIS_URL="$REDIS_URL" STREAM="$STREAM" JOB_ID="$job_id" python3 - <<'PY'
import os, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
stream = os.environ["STREAM"]
job_id = os.environ["JOB_ID"]
msgs = r.xrange(stream, min="-", max="+", count=500)
for mid, fields in msgs:
    if fields.get("job_id") == job_id:
        print(mid)
        raise SystemExit(0)
print("")
PY
}

fake_process_job_once() {
  local job_id="$1"
  local sleep_ms="${2:-50}"
  REDIS_URL="$REDIS_URL" STREAM="$STREAM" JOB_ID="$job_id" SLEEP_MS="$sleep_ms" python3 - <<'PY'
import os, time, json, hashlib, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
stream = os.environ["STREAM"]
job_id = os.environ["JOB_ID"]
sleep_ms = int(os.environ.get("SLEEP_MS","50"))

msgs = r.xrange(stream, min="-", max="+", count=500)
msg_id = None
fields = None
for mid, f in msgs:
    if f.get("job_id") == job_id:
        msg_id = mid
        fields = f
        break
if msg_id is None:
    print("NOT_FOUND")
    raise SystemExit(2)

spec_json = fields.get("spec_json","{}")
chk = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()

meta_key = f"job:{job_id}:meta"
t0 = time.perf_counter()
now = time.time()
r.hset(meta_key, mapping={"state":"RUNNING","updated_at":str(now),"started_at":str(now)})

time.sleep(sleep_ms/1000.0)

result = {"mode":"fake_worker","checksum":chk,"note":"Redis queue test worker"}
wall_ms = (time.perf_counter()-t0)*1000.0
now2 = time.time()

r.set(f"job:{job_id}:result", json.dumps(result, sort_keys=True, separators=(",",":")))
r.hset(meta_key, mapping={
    "state":"DONE",
    "updated_at":str(now2),
    "finished_at":str(now2),
    "wall_time_ms":str(wall_ms),
    "compute_time_ms":str(sleep_ms),
    "error":""
})

r.xdel(stream, msg_id)
print(f"PROCESSED job_id={job_id} msg_id={msg_id}")
PY
}

wait_for_state() {
  local job_id="$1"
  local target="$2"
  local deadline=$((SECONDS + TIMEOUT_SEC))
  local state=""
  while (( SECONDS < deadline )); do
    local resp code body
    resp="$(http_get "${HOST}/v1/jobs/${job_id}")"
    code="$(echo "$resp" | head -n1)"
    body="$(echo "$resp" | tail -n +2)"
    state="$(echo "$body" | extract_json_path state)"
    if [[ "$code" == "200" ]] && [[ "$state" == "$target" ]]; then
      echo "$state"
      return 0
    fi
    if [[ "$code" == "200" ]] && [[ "$state" == "FAILED" ]]; then
      echo "$state"
      return 1
    fi
    sleep 0.2
  done
  echo "$state"
  return 2
}

echo "============================================================"
echo "Redis queue smoke test (Feature 2)"
echo "HOST=${HOST}"
echo "REDIS_URL=${REDIS_URL}"
echo "STREAM=${STREAM}"
echo "============================================================"

if python_has_redis; then
  pass "python can import redis package"
else
  fail "python cannot import redis. Activate the venv and run: pip install redis"
  exit 1
fi

resp="$(http_get "${HOST}/healthz")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"
if [[ "$code" == "200" ]] && contains "$body" '"status"' && contains "$body" 'ok'; then
  pass "GET /healthz reachable"
else
  fail "GET /healthz failed (code=$code, body=$body)"
fi

pong="$(redis_ping 2>/dev/null || true)"
if [[ "$pong" == "PONG" ]]; then
  pass "Redis reachable (PING)"
else
  fail "Redis not reachable at $REDIS_URL (is Redis running?)"
fi

JOB_PAYLOAD='{
  "spec": {
    "op": "gemm",
    "m": 64,
    "n": 64,
    "k": 64,
    "dtype": "fp32",
    "repeats": 2,
    "seed": 7,
    "simulate": false
  }
}'

resp="$(http_post_json "${HOST}/v1/jobs" "$JOB_PAYLOAD")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"
JOB_ID="$(echo "$body" | extract_json_path job_id)"

if [[ "$code" == "200" ]] && [[ -n "$JOB_ID" ]]; then
  pass "POST /v1/jobs returns job_id"
  info "job_id=$JOB_ID"
else
  fail "POST /v1/jobs failed (code=$code, body=$body)"
  exit 1
fi

resp="$(http_get "${HOST}/v1/jobs/${JOB_ID}")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"
STATE="$(echo "$body" | extract_json_path state)"

if [[ "$code" == "200" ]] && ([[ "$STATE" == "QUEUED" ]] || [[ "$STATE" == "RUNNING" ]]); then
  pass "Job initially QUEUED/RUNNING (Redis mode likely active) (state=$STATE)"
elif [[ "$code" == "200" ]] && [[ "$STATE" == "DONE" ]]; then
  fail "Job DONE immediately — likely not in Redis mode (or another worker processed it)"
else
  fail "Unexpected job status (code=$code, state=$STATE, body=$body)"
fi

MSG_ID="$(stream_find_msg_id_for_job "$JOB_ID")"
if [[ -n "$MSG_ID" ]]; then
  pass "Redis stream contains message for job_id (msg_id=$MSG_ID)"
else
  fail "Did not find job_id in stream '$STREAM' (stream name mismatch?)"
fi

if [[ -n "$MSG_ID" ]]; then
  out="$(fake_process_job_once "$JOB_ID" 50 2>&1 || true)"
  if echo "$out" | grep -q "^PROCESSED"; then
    pass "Fake-processed the queued job via Redis"
    info "$out"
  else
    fail "Fake-process failed. Output: $out"
  fi
else
  fail "Skipping fake-process because stream message wasn't found."
fi

state_after="$(wait_for_state "$JOB_ID" "DONE")"
rc=$?
if [[ $rc -eq 0 ]]; then
  pass "Job reached DONE"
elif [[ $rc -eq 1 ]]; then
  fail "Job reached FAILED"
else
  fail "Timed out waiting for DONE (last state=${state_after:-unknown})"
fi

resp="$(http_get "${HOST}/v1/jobs/${JOB_ID}/result")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"
RSTATE="$(echo "$body" | extract_json_path state)"
MODE="$(echo "$body" | extract_json_path result_summary.mode)"
CHECKSUM="$(echo "$body" | extract_json_path result_summary.checksum)"

if [[ "$code" == "200" ]] && [[ "$RSTATE" == "DONE" ]] && [[ "$MODE" == "fake_worker" ]] && [[ -n "$CHECKSUM" ]]; then
  pass "Result shows DONE with fake_worker result + checksum"
else
  fail "Unexpected result (code=$code, state=$RSTATE, mode=$MODE, checksum=${CHECKSUM:-empty})"
fi

echo
echo "============================================================"
echo -e "Summary: ${GREEN}${PASS_COUNT} passed${NC}, ${RED}${FAIL_COUNT} failed${NC}"
echo "============================================================"

if [[ "$FAIL_COUNT" -ne 0 ]]; then
  exit 1
fi
exit 0
