"""
Aegis V2 Gateway – Phase 5: FinOps API Bridge

Entry point.  The lifespan handler now manages seven singletons:

  1. TelemetryState + NVML sampler          (Sprint 1)
  2. httpx.AsyncClient connection pool      (Sprint 2)
  3. CircuitBreaker + CircuitBreakerBackend (Sprint 3)
  4. RequestLogger + Parquet flush task     (Sprint 3)
  5. WorkerRegistryState + PrefixCacheIndex (Phase 2)
  6. KVAwareRouter + worker_registry_loop   (Phase 2)
  7. FinOpsAnalyticsEngine                  (Phase 5 — NEW)

Shutdown order (CRITICAL — do not reorder)
──────────────────────────────────────────
1. Cancel NVML sampler      → releases NVML C-bindings
2. Cancel worker poll task  → (Phase 2) uses httpx; must stop before pool closes
3. Stop RequestLogger       → final Parquet flush (no data loss on restart)
4. Close httpx pool         → drains in-flight cloud requests

Phase 2 is opt-in: when ``AEGIS_KV_WORKER_ENDPOINTS`` is empty (the default),
``kv_router`` is ``None`` and the system behaves identically to Sprint 3.
"""
from __future__ import annotations

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import uvicorn
from fastapi import FastAPI

from app.core.config import get_settings
from app.observability.analytics import FinOpsAnalyticsEngine
from app.observability.parquet_logger import RequestLogger
from app.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerBackend
from app.routing.entropy import SemanticEntropyProbe, build_rust_entropy_engine
from app.routing.kv_router import KVAwareRouter
from app.routing.prefix_cache import PrefixCacheIndex
from app.routing.router import EntropyRouter
from app.routing.strategies import CloudGeminiBackend, LocalEdgeBackend
from app.routing.worker_registry import WorkerRegistryState, worker_registry_loop
from app.telemetry.nvml_client import NvmlClient
from app.telemetry.sampler import telemetry_loop
from app.telemetry.state import TelemetryState


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan context manager.

    Startup (in order)
    ──────────────────
    1. Logging.
    2. TelemetryState + NvmlClient; launch NVML sampler task.
    3. httpx.AsyncClient singleton connection pool.
    4. CircuitBreaker + CircuitBreakerBackend wrapping CloudGeminiBackend.
    5. RequestLogger; launch Parquet flush background task.
    6. [Phase 2] WorkerRegistryState + PrefixCacheIndex singletons.
       Launch worker_registry_loop task (only when kv_worker_endpoints ≠ []).
    7. KVAwareRouter (or None when Phase 2 disabled).
    8. EntropyRouter wired with all dependencies.
    9. Yield — serve requests.

    Shutdown (in fixed order — do NOT change)
    ──────────────────────────────────────────
    1. Cancel NVML sampler     (NVML C-bindings first)
    2. Cancel worker poll task (uses httpx; must stop before pool closes)
    3. Stop RequestLogger      (final Parquet flush — preserves last batch)
    4. Close httpx pool        (wait for in-flight cloud requests)
    """
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    # ── Sprint 1: NVML Telemetry ──────────────────────────────────────────────
    telemetry_state = TelemetryState()
    nvml_client = NvmlClient()
    app.state.telemetry_state = telemetry_state

    sampler_task = asyncio.create_task(
        telemetry_loop(
            state=telemetry_state,
            client=nvml_client,
            interval_s=settings.telemetry_poll_interval_s,
            timeout_s=settings.telemetry_nvml_timeout_s,
            max_backoff_s=settings.telemetry_max_backoff_s,
            backoff_factor=settings.telemetry_backoff_factor,
            fail_threshold=settings.telemetry_fail_threshold,
        ),
        name="nvml_telemetry_sampler",
    )

    # ── Sprint 2: httpx connection pool ───────────────────────────────────────
    limits = httpx.Limits(
        max_connections=settings.httpx_max_connections,
        max_keepalive_connections=settings.httpx_max_keepalive,
        keepalive_expiry=30.0,
    )
    timeout = httpx.Timeout(
        settings.httpx_read_timeout_s,
        connect=settings.httpx_connect_timeout_s,
        pool=settings.httpx_pool_timeout_s,
    )
    http_client = httpx.AsyncClient(limits=limits, timeout=timeout, http2=True)
    app.state.http_client = http_client

    # ── Sprint 3: Circuit breaker ─────────────────────────────────────────────
    circuit_breaker = CircuitBreaker(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        cooldown_s=settings.circuit_breaker_cooldown_s,
    )
    app.state.circuit_breaker = circuit_breaker

    raw_cloud_backend = CloudGeminiBackend(client=http_client, settings=settings)
    protected_cloud_backend = CircuitBreakerBackend(
        backend=raw_cloud_backend,
        breaker=circuit_breaker,
    )

    # ── Sprint 3: FinOps request logger ───────────────────────────────────────
    request_logger = RequestLogger(settings=settings)
    app.state.request_logger = request_logger
    await request_logger.start()

    # ── Phase 5: FinOps analytics engine ──────────────────────────────────────
    # Stateless computation engine — no start()/stop() lifecycle needed.
    # All Polars work runs in asyncio.to_thread() to keep the event loop free.
    analytics_engine = FinOpsAnalyticsEngine(settings=settings)
    app.state.analytics_engine = analytics_engine

    # ── Phase 2: Worker Registry + KV-Aware Router ────────────────────────────
    worker_registry_state = WorkerRegistryState()
    prefix_cache = PrefixCacheIndex()
    app.state.worker_registry = worker_registry_state
    app.state.prefix_cache = prefix_cache

    worker_poll_task: asyncio.Task | None = None
    kv_router: KVAwareRouter | None = None

    if settings.kv_worker_endpoints:
        kv_router = KVAwareRouter(
            registry=worker_registry_state,
            prefix_cache=prefix_cache,
            settings=settings,
        )
        worker_poll_task = asyncio.create_task(
            worker_registry_loop(
                state=worker_registry_state,
                prefix_cache=prefix_cache,
                http_client=http_client,       # reuse the shared pool
                endpoints=settings.kv_worker_endpoints,
                poll_interval_s=settings.kv_poll_interval_s,
                eviction_threshold=settings.kv_eviction_detection_threshold,
            ),
            name="kv_worker_registry_poller",
        )
        logger.info(
            "Phase 2 KV-aware routing ENABLED — %d worker endpoint(s), "
            "poll_interval=%.1fs, prefix_depth=%d, min_free_ratio=%.2f.",
            len(settings.kv_worker_endpoints),
            settings.kv_poll_interval_s,
            settings.kv_prefix_match_depth,
            settings.kv_min_free_ratio,
        )
    else:
        logger.info(
            "Phase 2 KV-aware routing DISABLED "
            "(AEGIS_KV_WORKER_ENDPOINTS not set — Sprint 3 behaviour)."
        )

    app.state.kv_router = kv_router

    # ── Sprint 2+3+Phase2: EntropyRouter ──────────────────────────────────────
    rust_engine = build_rust_entropy_engine(settings)
    entropy_probe = SemanticEntropyProbe(rust_engine=rust_engine)

    app.state.router = EntropyRouter(
        telemetry_state=telemetry_state,
        entropy_probe=entropy_probe,
        local_backend=LocalEdgeBackend(settings=settings),
        cloud_backend=protected_cloud_backend,
        settings=settings,
        request_logger=request_logger,
        kv_router=kv_router,             # None → Phase 2 disabled transparently
    )

    logger.info(
        "Aegis V2 started – "
        "telemetry (poll=%.1fs), "
        "httpx (max_conn=%d), "
        "circuit_breaker (threshold=%d, cooldown=%.0fs), "
        "finops_logger (flush=%.1fs → %s), "
        "analytics_engine (glob=%s), "
        "kv_workers=%d.",
        settings.telemetry_poll_interval_s,
        settings.httpx_max_connections,
        settings.circuit_breaker_failure_threshold,
        settings.circuit_breaker_cooldown_s,
        settings.finops_flush_interval_s,
        settings.finops_log_dir,
        analytics_engine._glob_pattern,
        len(settings.kv_worker_endpoints),
    )

    try:
        yield  # serve requests
    finally:
        # ── Shutdown step 1: NVML sampler (C-bindings must release first) ─────
        logger.info("Aegis V2 shutting down – cancelling telemetry sampler.")
        sampler_task.cancel()
        try:
            await sampler_task
        except asyncio.CancelledError:
            pass
        logger.info("Telemetry sampler stopped.")

        # ── Shutdown step 2: Worker registry poller (uses httpx — before pool) ─
        if worker_poll_task is not None:
            logger.info("Cancelling worker registry poller.")
            worker_poll_task.cancel()
            try:
                await worker_poll_task
            except asyncio.CancelledError:
                pass
            logger.info("Worker registry poller stopped.")

        # ── Shutdown step 3: FinOps logger (final Parquet flush) ──────────────
        await request_logger.stop()

        # ── Shutdown step 4: httpx pool (drain in-flight cloud requests last) ──
        await http_client.aclose()
        logger.info("HTTP connection pool closed.")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Aegis V2 – Hardware-Aware Edge-Cloud Gateway",
    description=(
        "Phase 2: Disaggregated Serving + KV Cache-Aware Routing.  "
        "Includes Sprint 3 circuit breaker + async Parquet FinOps pipeline."
    ),
    version="0.4.0-phase2",
    lifespan=lifespan,
)

# Import after ``app`` is created to avoid circular imports.
from app.api.routes import router  # noqa: E402

app.include_router(router)


# ── Dev-mode entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        loop="uvloop",
        http="httptools",
        log_level="info",
        access_log=True,
        reload=False,
    )
