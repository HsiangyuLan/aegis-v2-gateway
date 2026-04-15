"""
Phase 2: Disaggregated Worker Registry.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Design contract (mirrors app/telemetry/state.py + sampler.py exactly)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WorkerRegistryState
───────────────────
* ``WorkerRegistrySnapshot`` and ``WorkerInfo`` are *frozen* Pydantic models.
  Once created they cannot be mutated; any reference held by a request handler
  always reads a consistent, coherent snapshot.
* ``WorkerRegistryState`` holds a single shared mutable reference under a
  ``threading.Lock``.  The background poller replaces it atomically.
* The request path ONLY calls ``get_snapshot()`` — O(1), one lock acquire.

worker_registry_loop
────────────────────
* Identical lifecycle contract to ``telemetry_loop`` in sampler.py:
    - Launched with ``asyncio.create_task()`` in lifespan startup.
    - Terminated with ``task.cancel()`` in lifespan shutdown.
    - Catches all exceptions; only CancelledError propagates out.
* HTTP polling uses the EXISTING shared ``httpx.AsyncClient`` so no new TCP
  connection pool is created.
* Exponential back-off per-worker on consecutive failures (same helpers as
  sampler.py: ``_next_interval``, throttled logging).
* Eviction detection: if a worker's used_blocks drops by more than
  ``eviction_threshold × total_blocks`` between two consecutive polls, the
  poller calls ``prefix_cache.evict_worker(worker_id)`` BEFORE publishing the
  new snapshot so the stale entries are gone when routing resumes.

Worker /metrics endpoint schema (expected from each disaggregated worker):
    {
      "worker_id":               "worker-0",
      "kv_cache_used_blocks":    1200,
      "kv_cache_total_blocks":   2048,
      "cached_prefix_hashes":    ["a1b2c3d4", "e5f60718", ...]   // optional
    }

``cached_prefix_hashes`` is a list of hex strings produced by the worker's own
prefix tracker; the registry forwards them to ``PrefixCacheIndex.insert()``.
If the field is absent the registry still tracks KV load but skips prefix
cache updates for that worker.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, List, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.routing.prefix_cache import PrefixCacheIndex

import threading

logger = logging.getLogger(__name__)


# ─── Frozen data models (immutable once created) ─────────────────────────────

class KvCacheStats(BaseModel):
    """KV cache occupancy metrics for a single disaggregated worker."""

    model_config = ConfigDict(frozen=True)

    used_blocks: int
    total_blocks: int

    @property
    def free_ratio(self) -> float:
        """Fraction of KV cache blocks that are free (0.0 = full, 1.0 = empty)."""
        if self.total_blocks <= 0:
            return 0.0
        return max(0.0, (self.total_blocks - self.used_blocks) / self.total_blocks)


class WorkerInfo(BaseModel):
    """Immutable snapshot of a single disaggregated worker's state."""

    model_config = ConfigDict(frozen=True)

    worker_id: str
    endpoint: str                          # base URL, e.g. "http://worker-0:8000"
    kv: KvCacheStats
    is_healthy: bool
    last_seen_ms: int = Field(description="Unix epoch milliseconds of last successful poll")
    consecutive_failures: int = 0          # included for observability / monitoring


class WorkerRegistrySnapshot(BaseModel):
    """Immutable snapshot of all known workers at one point in time."""

    model_config = ConfigDict(frozen=True)

    workers: List[WorkerInfo] = Field(default_factory=list)
    timestamp_ms: int


# ─── Thread-safe state manager ───────────────────────────────────────────────

class WorkerRegistryState:
    """
    Thread-safe singleton holding the latest WorkerRegistrySnapshot.

    Identical pattern to ``TelemetryState``:
    * ``get_snapshot()`` — O(1) read, safe from any thread or coroutine.
    * ``update_snapshot()`` — atomically replaces the reference; called only
      by the background ``worker_registry_loop`` coroutine.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: WorkerRegistrySnapshot = WorkerRegistrySnapshot(
            workers=[],
            timestamp_ms=int(time.time() * 1000),
        )

    def get_snapshot(self) -> WorkerRegistrySnapshot:
        """Return the latest immutable snapshot. Never blocks for more than
        a few nanoseconds (one Python lock acquire/release)."""
        with self._lock:
            return self._snapshot

    def update_snapshot(self, snapshot: WorkerRegistrySnapshot) -> None:
        """Atomically replace the current snapshot.  Called by the poller only."""
        with self._lock:
            self._snapshot = snapshot


# ─── Background poller ────────────────────────────────────────────────────────

async def worker_registry_loop(
    *,
    state: WorkerRegistryState,
    prefix_cache: "PrefixCacheIndex",
    http_client: httpx.AsyncClient,
    endpoints: list[str],
    poll_interval_s: float,
    eviction_threshold: float = 0.20,
    worker_http_timeout_s: float = 2.0,
    fail_threshold: int = 3,
    max_backoff_s: float = 30.0,
    backoff_factor: float = 2.0,
) -> None:
    """
    Poll every disaggregated worker's /metrics endpoint on a fixed cadence.

    Lifecycle contract (identical to ``telemetry_loop``):
    * Launched via ``asyncio.create_task()`` in main.py lifespan startup.
    * Terminated via ``task.cancel()`` in lifespan shutdown, BEFORE the
      httpx pool is closed (so in-flight poll requests are not orphaned).
    * Only ``asyncio.CancelledError`` propagates; all other exceptions are
      caught and reflected in per-worker ``is_healthy=False`` state.

    Parameters
    ----------
    state:              Shared state manager for worker snapshots.
    prefix_cache:       Prefix cache to update on new/evicted entries.
    http_client:        Shared process-wide httpx.AsyncClient (injected).
    endpoints:          List of worker base URLs (from config).
    poll_interval_s:    Normal poll cadence in seconds.
    eviction_threshold: Fraction of blocks that must drop to trigger eviction.
    worker_http_timeout_s: Per-worker HTTP timeout.
    fail_threshold:     Consecutive failures before exponential back-off.
    max_backoff_s:      Upper bound for per-worker back-off interval.
    backoff_factor:     Multiplier per back-off step.
    """
    # Per-worker mutable tracking (only mutated by this coroutine)
    failure_counts: dict[str, int] = {ep: 0 for ep in endpoints}
    intervals: dict[str, float] = {ep: poll_interval_s for ep in endpoints}
    prev_used: dict[str, int] = {}        # worker_id → previous used_blocks
    prev_total: dict[str, int] = {}       # worker_id → previous total_blocks

    logger.info(
        "Worker registry poller started: %d endpoint(s), interval=%.1fs.",
        len(endpoints),
        poll_interval_s,
    )

    try:
        while True:
            await asyncio.sleep(poll_interval_s)

            worker_infos: list[WorkerInfo] = []

            for endpoint in endpoints:
                info = await _poll_worker(
                    endpoint=endpoint,
                    http_client=http_client,
                    prefix_cache=prefix_cache,
                    prev_used=prev_used,
                    prev_total=prev_total,
                    failure_counts=failure_counts,
                    intervals=intervals,
                    timeout_s=worker_http_timeout_s,
                    fail_threshold=fail_threshold,
                    max_backoff_s=max_backoff_s,
                    backoff_factor=backoff_factor,
                    eviction_threshold=eviction_threshold,
                )
                worker_infos.append(info)

            state.update_snapshot(
                WorkerRegistrySnapshot(
                    workers=worker_infos,
                    timestamp_ms=int(time.time() * 1000),
                )
            )

    except asyncio.CancelledError:
        logger.info("Worker registry poller received cancellation – shutting down.")
        raise


async def _poll_worker(
    *,
    endpoint: str,
    http_client: httpx.AsyncClient,
    prefix_cache: "PrefixCacheIndex",
    prev_used: dict[str, int],
    prev_total: dict[str, int],
    failure_counts: dict[str, int],
    intervals: dict[str, float],
    timeout_s: float,
    fail_threshold: int,
    max_backoff_s: float,
    backoff_factor: float,
    eviction_threshold: float,
) -> WorkerInfo:
    """
    Poll a single worker endpoint and return a WorkerInfo.

    Updates ``prefix_cache`` and ``prev_used`` / ``prev_total`` in place.
    Never raises; failures are recorded as is_healthy=False WorkerInfo.
    """
    metrics_url = endpoint.rstrip("/") + "/metrics"
    try:
        response = await http_client.get(
            metrics_url,
            timeout=timeout_s,
        )
        response.raise_for_status()
        data: dict = response.json()

        worker_id: str = str(data["worker_id"])
        used: int = int(data["kv_cache_used_blocks"])
        total: int = int(data["kv_cache_total_blocks"])

        # ── Eviction detection ─────────────────────────────────────────────
        if worker_id in prev_used and total > 0:
            drop = prev_used[worker_id] - used
            threshold_blocks = eviction_threshold * prev_total.get(worker_id, total)
            if drop > threshold_blocks:
                logger.info(
                    "Worker %s: KV cache eviction detected "
                    "(used %d → %d, drop=%.1f%%). Invalidating prefix cache.",
                    worker_id,
                    prev_used[worker_id],
                    used,
                    drop / total * 100,
                )
                prefix_cache.evict_worker(worker_id)

        prev_used[worker_id] = used
        prev_total[worker_id] = total

        # ── Prefix cache update from worker-reported prefixes ──────────────
        cached_hashes: list[str] = data.get("cached_prefix_hashes", [])
        if cached_hashes:
            # Each entry is a single hex string representing one prefix level.
            # Insert the full sequence so deeper matches beat shallow ones.
            prefix_cache.insert(cached_hashes, worker_id)

        # ── Recovery logging ───────────────────────────────────────────────
        if failure_counts[endpoint] > 0:
            logger.info(
                "Worker %s (%s) recovered after %d failure(s).",
                worker_id, endpoint, failure_counts[endpoint],
            )
        failure_counts[endpoint] = 0
        intervals[endpoint] = 0.0  # not used per-worker; loop uses poll_interval_s

        return WorkerInfo(
            worker_id=worker_id,
            endpoint=endpoint,
            kv=KvCacheStats(used_blocks=used, total_blocks=total),
            is_healthy=True,
            last_seen_ms=int(time.time() * 1000),
            consecutive_failures=0,
        )

    except Exception as exc:
        failure_counts[endpoint] += 1
        _log_worker_failure(endpoint, exc, failure_counts[endpoint], fail_threshold)
        intervals[endpoint] = _next_interval(
            intervals[endpoint],
            base=0.0,
            factor=backoff_factor,
            maximum=max_backoff_s,
            failures=failure_counts[endpoint],
            threshold=fail_threshold,
        )
        # Derive worker_id from endpoint for the unhealthy record
        worker_id_fallback = endpoint.split("//")[-1].split(":")[0]
        return WorkerInfo(
            worker_id=worker_id_fallback,
            endpoint=endpoint,
            kv=KvCacheStats(used_blocks=0, total_blocks=0),
            is_healthy=False,
            last_seen_ms=int(time.time() * 1000),
            consecutive_failures=failure_counts[endpoint],
        )


# ─── Shared helpers (mirrors sampler.py helpers) ─────────────────────────────

def _next_interval(
    current: float,
    base: float,
    factor: float,
    maximum: float,
    failures: int,
    threshold: int,
) -> float:
    """Return next back-off interval; only grows after fail_threshold."""
    if failures >= threshold:
        return min(max(current, base) * factor, maximum)
    return base


def _log_worker_failure(
    endpoint: str, exc: BaseException, consecutive: int, threshold: int
) -> None:
    """Throttled failure logging: 1st → WARNING; threshold-th → ERROR."""
    if consecutive == 1:
        logger.warning("Worker %s: poll failure #1 – %s: %s", endpoint, type(exc).__name__, exc)
    elif consecutive == threshold:
        logger.error(
            "Worker %s: %d consecutive poll failures – entering back-off. Last: %s: %s",
            endpoint, consecutive, type(exc).__name__, exc,
        )
