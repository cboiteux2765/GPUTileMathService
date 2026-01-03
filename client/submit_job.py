@app.post("/v1/jobs", response_model=SubmitJobResponse)
def submit_job(req: SubmitJobRequest) -> SubmitJobResponse:
    spec = req.spec.model_dump()

    jobs_submitted_total.labels(
        op=spec["op"],
        dtype=spec["dtype"],
        simulate=str(spec["simulate"]).lower(),
    ).inc()

    # ✅ Redis queue mode: enqueue only, do NOT execute inline
    if redis_backend is not None:
        job_id = redis_backend.create_job(spec)
        redis_backend.enqueue(job_id, spec)
        return SubmitJobResponse(job_id=job_id)

    # Feature 1 (in-memory): execute inline
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