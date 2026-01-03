from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Optional

import redis

DEFAULT_STREAM = "queue:jobs"


def _r() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


class RedisJobBackend:
    def __init__(self) -> None:
        self.r = _r()
        self.stream = os.getenv("REDIS_STREAM", DEFAULT_STREAM)

    def create_job(self, spec: Dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        meta_key = f"job:{job_id}:meta"

        self.r.hset(
            meta_key,
            mapping={
                "job_id": job_id,
                "state": "QUEUED",
                "created_at": str(now),
                "updated_at": str(now),
                "started_at": "",
                "finished_at": "",
                "error": "",
                "wall_time_ms": "",
                "compute_time_ms": "",
                "spec_json": json.dumps(spec, sort_keys=True, separators=(",", ":")),
            },
        )
        return job_id

    def enqueue(self, job_id: str, spec: Dict[str, Any]) -> str:
        return self.r.xadd(
            self.stream,
            {
                "job_id": job_id,
                "spec_json": json.dumps(spec, sort_keys=True, separators=(",", ":")),
            },
        )

    def get_meta(self, job_id: str) -> Optional[Dict[str, Any]]:
        meta_key = f"job:{job_id}:meta"
        m = self.r.hgetall(meta_key)
        if not m:
            return None

        def ffloat(k: str) -> float | None:
            v = m.get(k, "")
            return float(v) if v not in ("", None) else None

        return {
            "job_id": job_id,
            "state": m.get("state", "QUEUED"),
            "created_at": float(m.get("created_at", "0") or "0"),
            "updated_at": float(m.get("updated_at", "0") or "0"),
            "started_at": ffloat("started_at"),
            "finished_at": ffloat("finished_at"),
            "error": (m.get("error") or None),
            "wall_time_ms": ffloat("wall_time_ms"),
            "compute_time_ms": ffloat("compute_time_ms"),
        }

    def get_result(self, job_id: str) -> Dict[str, Any] | None:
        s = self.r.get(f"job:{job_id}:result")
        if not s:
            return None
        return json.loads(s)
