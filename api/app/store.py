from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .schemas import JobState


@dataclass
class JobRecord:
    spec: Dict[str, Any]
    state: JobState
    created_at: float
    updated_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result_summary: Optional[Dict[str, Any]] = None
    wall_time_ms: Optional[float] = None
    compute_time_ms: Optional[float] = None


class InMemoryJobStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, JobRecord] = {}

    def create_job(self, spec: Dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        rec = JobRecord(spec=spec, state=JobState.QUEUED, created_at=now, updated_at=now)
        with self._lock:
            self._jobs[job_id] = rec
        return job_id

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def set_state(self, job_id: str, state: JobState, *, error: str | None = None) -> None:
        now = time.time()
        with self._lock:
            rec = self._jobs[job_id]
            rec.state = state
            rec.updated_at = now
            if error is not None:
                rec.error = error
            if state == JobState.RUNNING and rec.started_at is None:
                rec.started_at = now
            if state in (JobState.DONE, JobState.FAILED):
                rec.finished_at = now

    def set_result(
        self,
        job_id: str,
        *,
        result_summary: Dict[str, Any] | None,
        wall_time_ms: float | None,
        compute_time_ms: float | None,
    ) -> None:
        now = time.time()
        with self._lock:
            rec = self._jobs[job_id]
            rec.updated_at = now
            rec.result_summary = result_summary
            rec.wall_time_ms = wall_time_ms
            rec.compute_time_ms = compute_time_ms
