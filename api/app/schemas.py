from __future__ import annotations

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field, conint


class DType(str, Enum):
    fp16 = "fp16"
    fp32 = "fp32"


class Op(str, Enum):
    gemm = "gemm"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class GemmSpec(BaseModel):
    op: Literal["gemm"] = "gemm"
    m: conint(ge=1, le=1_000_000)  # shape only; compute may be simulated
    n: conint(ge=1, le=1_000_000)
    k: conint(ge=1, le=1_000_000)
    dtype: DType = DType.fp32
    repeats: conint(ge=1, le=10_000) = 1
    seed: conint(ge=0, le=2**31 - 1) = 0

    # Feature toggles for early testing
    simulate: bool = Field(
        default=False,
        description="If true, don't compute; return deterministic checksum + timing metadata.",
    )

    # Future: let the client request a tile configuration explicitly
    tile_m: Optional[conint(ge=1, le=256)] = None
    tile_n: Optional[conint(ge=1, le=256)] = None
    tile_k: Optional[conint(ge=1, le=256)] = None


class SubmitJobRequest(BaseModel):
    spec: GemmSpec


class SubmitJobResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    state: JobState
    created_at: float
    updated_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None

    # basic perf counters
    wall_time_ms: float | None = None
    compute_time_ms: float | None = None


class JobResultResponse(BaseModel):
    job_id: str
    state: JobState
    result_summary: dict | None = None
    error: str | None = None
