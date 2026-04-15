"""
Async FinOps request logger.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Design contract
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

* ``RequestLogger.log()`` is **synchronous and non-blocking**.  It calls
  ``asyncio.Queue.put_nowait()`` which returns immediately without ever
  entering an ``await`` point.  The request handler is never delayed by
  logging.

* A background asyncio task (the "flush loop") wakes up every
  ``finops_flush_interval_s`` seconds, drains the queue, and calls
  ``asyncio.to_thread(write_parquet_sync)`` so the blocking disk I/O runs
  in a thread pool without stalling the ASGI event loop.

* The queue has a configurable maximum size (``finops_buffer_max_size``).
  When full, new records are silently dropped with a WARNING log — a
  deliberate trade-off: observability must never degrade inference quality.

* Each flush writes a **separate Parquet file** named by wall-clock
  microseconds.  This means:
  - Process restarts never overwrite previous data.
  - The FinOps analysis script can glob ``requests_*.parquet`` to cover all
    sessions out-of-core (more data than RAM), which is the whole point of
    the Polars streaming engine.

* On graceful shutdown (SIGTERM), ``stop()`` cancels the flush task and
  immediately flushes any remaining buffered records before the process exits
  — no data loss on planned restarts.

Parquet schema (columns in every file)
───────────────────────────────────────
  timestamp_ms          Int64   Wall-clock ms since epoch
  request_id            Utf8    UUID for distributed tracing
  entropy_score         Float64 SEP uncertainty (0.0 – 1.0)
  routed_to             Utf8    "local_edge" | "cloud_gemini"
  latency_ms            Float64 End-to-end request latency
  cost_saved_usd        Float64 Estimated USD saved vs always-cloud routing
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from app.core.config import Settings

logger = logging.getLogger(__name__)


# ── Log record ────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class RequestLogRecord:
    """One row in the FinOps Parquet log.

    Phase 2 additions
    -----------------
    ``selected_worker_id`` and ``kv_prefix_hit`` are new optional columns.
    Old Parquet files (Sprint 3 and earlier) do not contain these columns.
    When mixing old and new files with ``pl.scan_parquet(glob=True)``, pass
    ``allow_missing_columns=True`` so the streaming engine fills missing
    columns with null / false rather than raising a schema error.
    """

    timestamp_ms: int
    request_id: str
    entropy_score: float
    routed_to: str          # "local_edge" | "cloud_gemini"
    latency_ms: float
    cost_saved_usd: float
    # Phase 2 — KV-aware routing metadata (None / False when Phase 2 inactive)
    selected_worker_id: str | None = None
    kv_prefix_hit: bool = False


# ── Logger ────────────────────────────────────────────────────────────────────

class RequestLogger:
    """
    Non-blocking FinOps request logger.

    Lifecycle (mirrors the NVML sampler pattern from Sprint 1):
      ``start()``  → creates background flush task
      ``log()``    → called on every request path (sync, O(1))
      ``stop()``   → cancels task + final flush (called in lifespan shutdown)
    """

    def __init__(self, settings: Settings) -> None:
        self._log_dir = Path(settings.finops_log_dir)
        self._flush_interval_s = settings.finops_flush_interval_s
        self._buffer: asyncio.Queue[RequestLogRecord] = asyncio.Queue(
            maxsize=settings.finops_buffer_max_size
        )
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_count: int = 0
        self._startup_ts = int(time.time() * 1_000_000)  # µs; unique per process

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the background flush task.  Call once during lifespan startup."""
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="finops_parquet_flusher"
        )
        logger.info(
            "FinOps logger started (flush_interval=%.1fs, log_dir=%s).",
            self._flush_interval_s,
            self._log_dir,
        )

    async def stop(self) -> None:
        """
        Cancel the flush task and perform a final flush to ensure no records
        are lost on graceful shutdown.  Call in lifespan shutdown's finally block.
        """
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Best-effort final flush
        await self._flush_once()
        logger.info("FinOps logger stopped (final flush complete).")

    # ------------------------------------------------------------------
    # Hot path — called on every request
    # ------------------------------------------------------------------

    def log(self, record: RequestLogRecord) -> None:
        """
        Buffer a log record.

        This method is intentionally **synchronous** — it never ``await``s.
        If the buffer is full, the record is dropped with a WARNING rather
        than blocking the request handler.
        """
        try:
            self._buffer.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning(
                "FinOps log buffer full (max=%d) — dropping record for %s.",
                self._buffer.maxsize,
                record.request_id,
            )

    # ------------------------------------------------------------------
    # Background flush loop
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._flush_interval_s)
                await self._flush_once()
        except asyncio.CancelledError:
            logger.debug("FinOps flush loop cancelled.")
            raise

    async def _flush_once(self) -> None:
        """
        Drain the in-memory queue and write a Parquet file.

        The actual I/O runs in a thread pool via ``asyncio.to_thread()`` to
        avoid blocking the ASGI event loop during disk writes.
        """
        records: list[RequestLogRecord] = []
        try:
            while True:
                records.append(self._buffer.get_nowait())
        except asyncio.QueueEmpty:
            pass

        if not records:
            return

        flush_id = self._flush_count
        self._flush_count += 1

        await asyncio.to_thread(self._write_parquet_sync, records, flush_id)

    # ------------------------------------------------------------------
    # Synchronous Parquet writer (runs inside ThreadPoolExecutor)
    # ------------------------------------------------------------------

    def _write_parquet_sync(
        self, records: list[RequestLogRecord], flush_id: int
    ) -> None:
        """
        Write ``records`` to a Parquet file.

        File naming: ``requests_{startup_µs}_{flush_id:010d}.parquet``
        The startup timestamp makes filenames unique across process restarts.
        The flush_id provides monotonic ordering within a single run.
        """
        self._log_dir.mkdir(parents=True, exist_ok=True)

        df = pl.DataFrame(
            {
                "timestamp_ms":      [r.timestamp_ms for r in records],
                "request_id":        [r.request_id for r in records],
                "entropy_score":     [r.entropy_score for r in records],
                "routed_to":         [r.routed_to for r in records],
                "latency_ms":        [r.latency_ms for r in records],
                "cost_saved_usd":    [r.cost_saved_usd for r in records],
                # Phase 2 columns — present in all new files; missing in old files
                "selected_worker_id": [r.selected_worker_id for r in records],
                "kv_prefix_hit":      [r.kv_prefix_hit for r in records],
            },
            schema={
                "timestamp_ms":      pl.Int64,
                "request_id":        pl.Utf8,
                "entropy_score":     pl.Float64,
                "routed_to":         pl.Utf8,
                "latency_ms":        pl.Float64,
                "cost_saved_usd":    pl.Float64,
                "selected_worker_id": pl.Utf8,
                "kv_prefix_hit":     pl.Boolean,
            },
        )

        filename = f"requests_{self._startup_ts}_{flush_id:010d}.parquet"
        out_path = self._log_dir / filename
        df.write_parquet(out_path)

        logger.debug(
            "FinOps flush: wrote %d records → %s",
            len(records),
            out_path,
        )
