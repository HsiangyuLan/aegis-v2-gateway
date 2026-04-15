"""
In-memory telemetry state manager.

Design contract
───────────────
* ``TelemetrySnapshot`` and ``GpuSnapshot`` are *frozen* Pydantic models – once
  created they cannot be mutated.  This guarantees that any reference held by a
  request handler always reads a consistent, coherent snapshot.

* ``TelemetryState`` is the single shared mutable object in the process.  It
  wraps a ``threading.Lock`` so that the background sampler thread (ThreadPool
  executor) and the ASGI event-loop thread can both safely access it.

* The request path **only reads** from ``TelemetryState.get_snapshot()``.  This
  is an O(1) operation: it acquires a short-lived lock, reads a single Python
  reference, and releases the lock.  No NVML calls ever happen here.

* The sampler calls ``TelemetryState.update_snapshot()`` at most once per poll
  cycle, atomically replacing the reference with a brand-new snapshot object.
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GpuSnapshot(BaseModel):
    """Per-GPU metrics captured in a single NVML poll cycle."""

    model_config = ConfigDict(frozen=True)

    gpu_index: int

    memory_used_bytes: Optional[int] = None
    memory_free_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None

    # TODO (Architecture): True fragmentation requires introspection into the CUDA
    # Caching Allocator (e.g., exposing vLLM internal metrics) and will be integrated
    # via an external metrics endpoint in Phase 2.  Keep this NVML layer strictly for
    # OS-level hardware limit telemetry.
    #
    # For Sprint 1 MVP this is a proxy: used_bytes / total_bytes.
    # Variable is intentionally named ``vram_utilization_ratio`` (not "fragmentation")
    # to be mathematically accurate about what NVML actually provides.
    vram_utilization_ratio: Optional[float] = None

    # Streaming Multiprocessor occupancy reported by nvmlDeviceGetUtilizationRates.
    sm_utilization_percent: Optional[int] = None

    # Memory-bandwidth utilization reported by nvmlDeviceGetUtilizationRates.
    memory_bandwidth_utilization_percent: Optional[int] = None


class TelemetrySnapshot(BaseModel):
    """
    Immutable snapshot of the full GPU telemetry state at one point in time.

    ``telemetry_available=False`` with a populated ``degrade_reason`` indicates
    the system is running in CPU-only / Cloud-only fallback mode.
    """

    model_config = ConfigDict(frozen=True)

    timestamp_ms: int
    telemetry_available: bool
    gpu_count: Optional[int] = None
    per_gpu: List[GpuSnapshot] = Field(default_factory=list)
    degrade_reason: Optional[str] = None


class TelemetryState:
    """
    Thread-safe singleton-like state manager holding the latest snapshot.

    Reads are O(1) and safe to perform from any thread or coroutine.
    Writes atomically replace the snapshot reference under a short-lived lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Initialise with an explicit degrade snapshot so callers always see a
        # valid object – never None – even before the first sampler cycle runs.
        self._snapshot: TelemetrySnapshot = TelemetrySnapshot(
            timestamp_ms=int(time.time() * 1000),
            telemetry_available=False,
            gpu_count=None,
            per_gpu=[],
            degrade_reason="Initializing – awaiting first NVML telemetry sample",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(self) -> TelemetrySnapshot:
        """Return the latest immutable snapshot.  Never blocks for more than a
        few nanoseconds (just a Python lock acquire/release)."""
        with self._lock:
            return self._snapshot

    def update_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        """Atomically replace the current snapshot.

        Called exclusively by the background sampler task.
        """
        with self._lock:
            self._snapshot = snapshot
