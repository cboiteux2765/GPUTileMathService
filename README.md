# GPU Tile Math Service (incremental build)

This repo is structured so you can test each feature **individually** before wiring components together.

## What’s implemented right now (Feature 1)
**API-only** FastAPI service with an **in-memory** job store and a simple “executor” that can:
- compute a small CPU GEMM result summary (for tiny shapes), or
- simulate a result for larger shapes (deterministic checksum)

This lets you test:
- request validation
- job lifecycle (QUEUED/RUNNING/DONE/FAILED)
- metrics endpoint

## Repo layout
- `api/` FastAPI service (Feature 1)
- `client/` simple CLI client to submit jobs to the API
- `worker_cuda/` placeholder for the standalone CUDA kernel benchmark (Feature 4 later)
- `docs/` notes / architecture

## Quickstart (Feature 1: API only)

### 1) Create a venv and install deps
```bash
cd api
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2) Run the API
```bash
uvicorn app.main:app --reload --port 8000
```

### 3) Submit a job
```bash
python ../client/submit_job.py --m 64 --n 64 --k 64 --dtype fp32 --repeats 5
python ../client/submit_job.py --m 4096 --n 4096 --k 4096 --dtype fp16 --simulate
```

### 4) Check status/results
```bash
# replace JOB_ID
curl http://127.0.0.1:8000/v1/jobs/JOB_ID
curl http://127.0.0.1:8000/v1/jobs/JOB_ID/result
curl http://127.0.0.1:8000/metrics
```

## Next features we’ll implement (one-by-one)
2. Redis queue + metadata store (API still runnable alone)
3. Worker stub (no CUDA yet): pulls from Redis, produces results
4. Standalone CUDA tiled GEMM binary (benchmark CLI)
5. Integrate worker + CUDA + batching/streams

