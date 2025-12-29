#!/usr/bin/env bash
# Test script for Feature 1 (API-only) endpoints.

HOST="${HOST:-http://127.0.0.1:8000}"

PASS_COUNT=0
FAIL_COUNT=0

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
NC="\033[0m"

pass() {
  echo -e "${GREEN}PASS${NC} - $1"
  PASS_COUNT=$((PASS_COUNT+1))
}

fail() {
  echo -e "${RED}FAIL${NC} - $1"
  FAIL_COUNT=$((FAIL_COUNT+1))
}

info() {
  echo -e "${YELLOW}INFO${NC} - $1"
}

http_get() {
  # usage: http_get URL
  # prints: "<code>\n<body>"
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
  # usage: http_post_json URL JSON_STRING
  # prints: "<code>\n<body>"
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

extract_json_field() {
  # usage: extract_json_field FIELD_NAME
  # reads JSON from stdin, prints field value or empty string
  local field="$1"
  python3 -c 'import sys, json
data = sys.stdin.read().strip()
try:
    obj = json.loads(data) if data else {}
    v = obj.get(sys.argv[1], "")
    print("" if v is None else v)
except Exception:
    print("")' "$field"
}

contains() {
  # usage: contains "haystack" "needle"
  [[ "$1" == *"$2"* ]]
}

echo "============================================================"
echo "API smoke test (Feature 1)"
echo "HOST=${HOST}"
echo "============================================================"

# 1) healthz
resp="$(http_get "${HOST}/healthz")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"

if [[ "$code" == "200" ]] && contains "$body" '"status"' && contains "$body" 'ok'; then
  pass "GET /healthz returns 200 and contains status=ok"
else
  fail "GET /healthz expected 200 and status=ok (got code=$code, body=$body)"
fi

# 2) Submit CPU GEMM job (small enough to compute)
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

JOB_ID="$(echo "$body" | extract_json_field job_id)"

if [[ "$code" == "200" ]] && [[ -n "$JOB_ID" ]]; then
  pass "POST /v1/jobs returns 200 and job_id"
  info "job_id=$JOB_ID"
else
  fail "POST /v1/jobs expected 200 and job_id (got code=$code, body=$body)"
fi

# If submit failed, we can’t continue meaningful tests
if [[ -z "$JOB_ID" ]]; then
  echo
  echo "============================================================"
  echo -e "Summary: ${GREEN}${PASS_COUNT} passed${NC}, ${RED}${FAIL_COUNT} failed${NC}"
  echo "============================================================"
  exit 1
fi

# 3) Get job status
resp="$(http_get "${HOST}/v1/jobs/${JOB_ID}")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"

STATE="$(echo "$body" | extract_json_field state)"

if [[ "$code" == "200" ]] && ([[ "$STATE" == "DONE" ]] || [[ "$STATE" == "FAILED" ]] || [[ "$STATE" == "RUNNING" ]] || [[ "$STATE" == "QUEUED" ]]); then
  pass "GET /v1/jobs/{id} returns 200 and a valid state (state=$STATE)"
else
  fail "GET /v1/jobs/{id} expected 200 and state field (got code=$code, body=$body)"
fi

# In Feature 1, submit executes inline, so typically DONE/FAILED immediately.
# If it’s still RUNNING/QUEUED somehow, wait briefly and re-check once.
if [[ "$STATE" == "RUNNING" ]] || [[ "$STATE" == "QUEUED" ]]; then
  info "job state=$STATE; waiting 0.5s then re-checking..."
  sleep 0.5
  resp="$(http_get "${HOST}/v1/jobs/${JOB_ID}")"
  code="$(echo "$resp" | head -n1)"
  body="$(echo "$resp" | tail -n +2)"
  STATE="$(echo "$body" | extract_json_field state)"
  info "job state now=$STATE"
fi

# 4) Get job result
resp="$(http_get "${HOST}/v1/jobs/${JOB_ID}/result")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"

RSTATE="$(echo "$body" | extract_json_field state)"

# Check that when DONE, it includes a result_summary with cpu_gemm mode
if [[ "$code" != "200" ]]; then
  fail "GET /v1/jobs/{id}/result expected 200 (got code=$code, body=$body)"
else
  if [[ "$RSTATE" == "DONE" ]]; then
    if contains "$body" '"result_summary"' && contains "$body" '"mode"' && contains "$body" 'cpu_gemm'; then
      pass "GET /v1/jobs/{id}/result returns DONE with cpu_gemm result_summary"
    else
      fail "Result missing expected cpu_gemm summary (body=$body)"
    fi
  elif [[ "$RSTATE" == "FAILED" ]]; then
    fail "Job FAILED; result endpoint reports FAILED (body=$body)"
  else
    fail "Unexpected result state: $RSTATE (body=$body)"
  fi
fi

# 5) Metrics endpoint
resp="$(http_get "${HOST}/metrics")"
code="$(echo "$resp" | head -n1)"
body="$(echo "$resp" | tail -n +2)"

if [[ "$code" == "200" ]] && contains "$body" "jobs_submitted_total" && contains "$body" "jobs_completed_total" && contains "$body" "job_end_to_end_ms_bucket"; then
  pass "GET /metrics returns 200 and includes expected metric names"
else
  fail "GET /metrics expected 200 and metric names (got code=$code)"
fi

echo
echo "============================================================"
echo -e "Summary: ${GREEN}${PASS_COUNT} passed${NC}, ${RED}${FAIL_COUNT} failed${NC}"
echo "============================================================"

# Exit non-zero if any failures
if [[ "$FAIL_COUNT" -ne 0 ]]; then
  exit 1
fi
exit 0
