# worker_cuda (placeholder)

We’ll add a standalone CUDA benchmark binary here (tiled GEMM first) so you can test CUDA tiling
independently from the API/queue/worker.

Next step after Feature 1 is usually:
- Feature 2: Redis queue + metadata
- Feature 3: Worker stub (no CUDA yet) that consumes Redis jobs
- Feature 4: This CUDA binary, then integrate it into Feature 3