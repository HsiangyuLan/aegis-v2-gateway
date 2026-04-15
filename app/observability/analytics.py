"""
FinOps Analytics Engine — Phase 5: API Bridge

Provides ``FinOpsAnalyticsEngine``, a stateless computation class that reads
all Parquet files produced by ``RequestLogger`` and returns aggregated FinOps
metrics as a Pydantic-serialisable ``FinOpsReport``.

ASGI event-loop safety
──────────────────────
Polars ``scan_parquet`` and ``collect(engine="streaming")`` are CPU-bound
operations that execute synchronously.  Calling them directly inside an
``async def`` endpoint would block the uvloop event loop and starve all
concurrent requests.

This module enforces the invariant by routing every Polars call through
``asyncio.to_thread()``, which hands the work off to Python's
``ThreadPoolExecutor``.  The event loop is free to handle other coroutines
while the computation runs on a separate OS thread.

Edge case handling
──────────────────
When no Parquet files have been written yet (freshly started gateway, or an
empty log directory), ``compute()`` returns a zeroed ``FinOpsReport`` with
``data_available=False`` instead of raising an exception.  This lets the
frontend render a "no data yet" placeholder without a 500-class error.
"""
from __future__ import annotations

import asyncio
import glob as _glob
import logging
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel

from app.core.config import Settings

logger = logging.getLogger(__name__)


# ── Response model ─────────────────────────────────────────────────────────────

class FinOpsReport(BaseModel):
    """
    Aggregated FinOps metrics derived from the Parquet request log pipeline.

    When ``data_available`` is ``False`` all numeric fields are zero and
    ``routing_distribution`` is empty — the gateway has not yet written any
    log files.
    """

    total_requests: int
    routing_distribution: dict[str, int]
    total_cost_saved_usd: float
    p99_latency_ms: float
    data_available: bool

    @classmethod
    def empty(cls) -> "FinOpsReport":
        """Return a zeroed report for the 'no data yet' state."""
        return cls(
            total_requests=0,
            routing_distribution={},
            total_cost_saved_usd=0.0,
            p99_latency_ms=0.0,
            data_available=False,
        )


# ── Engine ─────────────────────────────────────────────────────────────────────

class FinOpsAnalyticsEngine:
    """
    Stateless analytics engine that wraps Polars streaming queries.

    Lifecycle
    ─────────
    No ``start()`` / ``stop()`` required.  The engine holds only the glob
    pattern string computed once at construction time.  Each call to
    ``compute()`` spawns a fresh thread-pool task via ``asyncio.to_thread``.

    Usage::

        engine = FinOpsAnalyticsEngine(settings=settings)
        report: FinOpsReport = await engine.compute()
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialise the engine.

        Args:
            settings: Frozen ``Settings`` dataclass.  Only
                      ``finops_log_dir`` is consumed.
        """
        log_dir = Path(settings.finops_log_dir)
        self._glob_pattern: str = str(log_dir / "requests_*.parquet")

    # ── Public async API ───────────────────────────────────────────────────────

    async def compute(self) -> FinOpsReport:
        """
        Compute FinOps aggregates from all Parquet log files.

        The Polars work runs inside ``asyncio.to_thread()`` so the ASGI
        event loop is never blocked.

        Returns:
            ``FinOpsReport`` with aggregated metrics.  If no log files exist
            yet, returns ``FinOpsReport.empty()`` (``data_available=False``).
        """
        return await asyncio.to_thread(self._compute_sync)

    # ── Private sync implementation (runs in thread pool) ─────────────────────

    def _compute_sync(self) -> FinOpsReport:
        """
        Execute Polars streaming aggregations synchronously.

        This method is intentionally synchronous — it must only be called
        via ``asyncio.to_thread()``, never awaited directly from an async
        context.

        Returns:
            A populated or zeroed ``FinOpsReport``.
        """
        try:
            return self._run_polars()
        except Exception as exc:
            logger.error(
                "FinOpsAnalyticsEngine._compute_sync failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return FinOpsReport.empty()

    def _run_polars(self) -> FinOpsReport:
        """
        Core Polars logic: glob → scan_parquet → streaming collect.

        Raises:
            Any Polars or I/O exception (caught by ``_compute_sync``).
        """
        # Fast path: skip scan_parquet entirely if no files exist.
        files = _glob.glob(self._glob_pattern)
        if not files:
            logger.debug(
                "FinOpsAnalyticsEngine: no Parquet files found at %s — "
                "returning empty report.",
                self._glob_pattern,
            )
            return FinOpsReport.empty()

        lf: pl.LazyFrame = pl.scan_parquet(self._glob_pattern)

        # ── Global aggregates (single streaming pass) ─────────────────────────
        global_df: pl.DataFrame = (
            lf.select(
                [
                    pl.len().alias("total_requests"),
                    pl.sum("cost_saved_usd").alias("total_cost_saved_usd"),
                    pl.quantile("latency_ms", 0.99).alias("p99_latency_ms"),
                ]
            )
            .collect(engine="streaming")
        )

        total_requests: int = int(global_df["total_requests"][0])
        total_cost_saved_usd: float = float(global_df["total_cost_saved_usd"][0])
        p99_latency_ms: float = float(global_df["p99_latency_ms"][0])

        # ── Routing distribution (second streaming pass) ───────────────────────
        routing_df: pl.DataFrame = (
            lf.group_by("routed_to")
            .agg(pl.len().alias("count"))
            .collect(engine="streaming")
        )

        routing_distribution: dict[str, int] = {
            row["routed_to"]: int(row["count"])
            for row in routing_df.iter_rows(named=True)
        }

        logger.debug(
            "FinOpsAnalyticsEngine: computed report — "
            "total=%d, routing=%s, cost_saved=%.6f, p99=%.1fms.",
            total_requests,
            routing_distribution,
            total_cost_saved_usd,
            p99_latency_ms,
        )

        return FinOpsReport(
            total_requests=total_requests,
            routing_distribution=routing_distribution,
            total_cost_saved_usd=total_cost_saved_usd,
            p99_latency_ms=p99_latency_ms,
            data_available=True,
        )
