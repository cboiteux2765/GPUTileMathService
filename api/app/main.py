from __future__ import annotations

import hashlib
import json
import math
import os
import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from .metrics import (
    jobs_submitted_total,
    jobs_completed_total,
    job_end_to_end_ms,
    job_compute_ms,
    jobs_in_memory,
)
from .redis_backend import RedisJobBackend
from .schemas import (
    SubmitJobRequest,
    SubmitJobResponse,
    JobStatusResponse,
    JobResultResponse,
    JobState,
)
from .store import InMemoryJobStore

app = FastAPI(title="GPU Tile Math Service (Feature 1: API-only)")
store = InMemoryJobStore()

JOB_BACKEND = os.getenv("JOB_BACKEND", "inmemory").lower()
redis_backend = RedisJobBackend() if JOB_BACKEND == "redis" else None

def _deterministic_checksum(payload: Dict[str, Any]) -> str:
    b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def _cpu_gemm_summary(m: int, n: int, k: int, seed: int, repeats: int) -> Dict[str, Any]:
    # Tiny CPU GEMM to validate pipeline. Not optimized.
    # Hard cap to keep API responsive.
    max_elems = 128 * 128
    if m * n > max_elems or m * k > max_elems or k * n > max_elems:
        raise ValueError("Shape too large for CPU compute mode; set simulate=true.")

    # simple deterministic pseudo-random matrix generation (no numpy dependency)
    def rand(i: int) -> float:
        # xorshift-ish
        x = (seed ^ (i * 0x9E3779B9)) & 0xFFFFFFFF
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        return (x / 0xFFFFFFFF) - 0.5

    A = [rand(i) for i in range(m * k)]
    B = [rand(10_000_000 + i) for i in range(k * n)]

    C = [0.0 for _ in range(m * n)]

    for _ in range(repeats):
        for i in range(m):
            for j in range(n):
                s = 0.0
                row = i * k
                col = j
                for kk in range(k):
                    s += A[row + kk] * B[kk * n + col]
                C[i * n + j] = s

    mean = sum(C) / (m * n)
    var = sum((x - mean) * (x - mean) for x in C) / (m * n)
    l2 = math.sqrt(sum(x * x for x in C))
    checksum = _deterministic_checksum({"m": m, "n": n, "k": k, "seed": seed, "repeats": repeats, "mean": mean, "var": var, "l2": l2})
    return {"mean": mean, "var": var, "l2": l2, "checksum": checksum, "mode": "cpu_gemm"}


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    try:
        # private access is fine in-process
        jobs_in_memory.set(len(store._jobs))
    except Exception:
        pass
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/jobs", response_model=SubmitJobResponse)
def submit_job(req: SubmitJobRequest) -> SubmitJobResponse:
    spec = req.spec.model_dump()

    # metrics: submitted
    jobs_submitted_total.labels(
        op=spec["op"],
        dtype=spec["dtype"],
        simulate=str(spec["simulate"]).lower(),
    ).inc()

    if redis_backend is not None:
        job_id = redis_backend.create_job(spec)
        redis_backend.enqueue(job_id, spec)
        jobs_submitted_total.labels(
            op=spec["op"],
            dtype=spec["dtype"],
            simulate=str(spec["simulate"]).lower(),
        ).inc()
        return SubmitJobResponse(job_id=job_id)

    job_id = store.create_job(spec)

    t0 = time.perf_counter()
    store.set_state(job_id, JobState.RUNNING)

    try:
        c0 = time.perf_counter()
        if spec["simulate"]:
            checksum = _deterministic_checksum(spec)
            result = {
                "checksum": checksum,
                "mode": "simulated",
                "note": "Set simulate=false for tiny shapes to run CPU GEMM summary.",
            }
            compute_ms = (time.perf_counter() - c0) * 1000.0
        else:
            result = _cpu_gemm_summary(
                m=int(spec["m"]),
                n=int(spec["n"]),
                k=int(spec["k"]),
                seed=int(spec["seed"]),
                repeats=int(spec["repeats"]),
            )
            compute_ms = (time.perf_counter() - c0) * 1000.0

        wall_ms = (time.perf_counter() - t0) * 1000.0
        store.set_result(job_id, result_summary=result, wall_time_ms=wall_ms, compute_time_ms=compute_ms)
        store.set_state(job_id, JobState.DONE)

        jobs_completed_total.labels(op=spec["op"], dtype=spec["dtype"], state="done").inc()
        job_end_to_end_ms.labels(op=spec["op"], dtype=spec["dtype"], simulate=str(spec["simulate"]).lower()).observe(wall_ms)
        job_compute_ms.labels(op=spec["op"], dtype=spec["dtype"], simulate=str(spec["simulate"]).lower()).observe(compute_ms)

    except Exception as e:
        wall_ms = (time.perf_counter() - t0) * 1000.0
        store.set_result(job_id, result_summary=None, wall_time_ms=wall_ms, compute_time_ms=None)
        store.set_state(job_id, JobState.FAILED, error=str(e))
        jobs_completed_total.labels(op=spec["op"], dtype=spec["dtype"], state="failed").inc()

    return SubmitJobResponse(job_id=job_id)


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    if redis_backend is not None:
        meta = redis_backend.get_meta(job_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="job_id not found")
        return JobStatusResponse(**meta)

    rec = store.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    return JobStatusResponse(
        job_id=job_id,
        state=rec.state,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        started_at=rec.started_at,
        finished_at=rec.finished_at,
        error=rec.error,
        wall_time_ms=rec.wall_time_ms,
        compute_time_ms=rec.compute_time_ms,
    )

@app.get("/v1/jobs/{job_id}/result", response_model=JobResultResponse)
def get_result(job_id: str) -> JobResultResponse:
    if redis_backend is not None:
        meta = redis_backend.get_meta(job_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="job_id not found")
        result = redis_backend.get_result(job_id)
        return JobResultResponse(
            job_id=job_id,
            state=meta["state"],
            result_summary=result,
            error=meta.get("error"),
        )

    rec = store.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    return JobResultResponse(
        job_id=job_id,
        state=rec.state,
        result_summary=rec.result_summary,
        error=rec.error,
    )

@app.get("/v1/backend")
def backend():
    return {
        "JOB_BACKEND": JOB_BACKEND,
        "REDIS_URL": os.getenv("REDIS_URL"),
        "REDIS_STREAM": os.getenv("REDIS_STREAM"),
        "redis_enabled": redis_backend is not None,
    }