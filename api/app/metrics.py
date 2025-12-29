from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge

jobs_submitted_total = Counter(
    "jobs_submitted_total",
    "Total number of jobs submitted",
    ["op", "dtype", "simulate"],
)

jobs_completed_total = Counter(
    "jobs_completed_total",
    "Total number of jobs completed",
    ["op", "dtype", "state"],
)

job_end_to_end_ms = Histogram(
    "job_end_to_end_ms",
    "End-to-end job wall time in milliseconds",
    ["op", "dtype", "simulate"],
)

job_compute_ms = Histogram(
    "job_compute_ms",
    "Job compute time in milliseconds (CPU compute for Feature 1)",
    ["op", "dtype", "simulate"],
)

jobs_in_memory = Gauge(
    "jobs_in_memory",
    "Number of jobs currently tracked in memory",
)
