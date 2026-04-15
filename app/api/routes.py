"""
HTTP endpoints.

Sprint 1: GET /healthz, GET /telemetry/gpu
Sprint 2: POST /v1/infer
Phase 2:  GET /v1/workers  (NEW)
Phase 5:  GET /v1/analytics/finops  (NEW)

All business logic lives in domain classes; endpoints are intentionally thin
(≤3 lines of logic each) to respect the Single Responsibility Principle.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.models.infer import InferRequest, InferResponse
from app.observability.analytics import FinOpsReport
from app.routing.worker_registry import WorkerRegistrySnapshot
from app.telemetry.state import TelemetrySnapshot

router = APIRouter()


# ── Sprint 1 ──────────────────────────────────────────────────────────────────

@router.get("/healthz", summary="Liveness + telemetry availability probe")
async def healthz(request: Request) -> dict:
    """
    Liveness endpoint.

    Returns HTTP 200 regardless of GPU state so that Kubernetes liveness
    probes do not restart the pod when NVML is unavailable.  Callers should
    inspect ``telemetry_available`` to decide routing behaviour.
    """
    snapshot: TelemetrySnapshot = request.app.state.telemetry_state.get_snapshot()
    return {
        "status": "ok",
        "telemetry_available": snapshot.telemetry_available,
        "timestamp_ms": snapshot.timestamp_ms,
        "degrade_reason": snapshot.degrade_reason,
    }


@router.get(
    "/telemetry/gpu",
    response_model=TelemetrySnapshot,
    summary="Latest GPU telemetry snapshot",
)
async def telemetry_gpu(request: Request) -> TelemetrySnapshot:
    """
    Return the most recent GPU telemetry snapshot collected by the background
    sampler task.

    This endpoint **never** triggers NVML calls – it only reads an immutable
    object reference from the in-memory state manager.  Latency is bounded by
    a single ``threading.Lock`` acquire/release (nanosecond range).
    """
    return request.app.state.telemetry_state.get_snapshot()


# ── Sprint 2 ──────────────────────────────────────────────────────────────────

@router.post(
    "/v1/infer",
    response_model=InferResponse,
    summary="Dual-route LLM inference (entropy + VRAM aware)",
)
async def infer(body: InferRequest, request: Request) -> InferResponse:
    """
    Route the prompt to the Local Edge model or Cloud Gemini based on:

      * Semantic entropy score from the SEP probe (< 0.4 → candidate for local)
      * Real-time VRAM utilization from Sprint 1 telemetry (< 85% → safe for local)
      * ``telemetry_available`` flag (False → always force cloud)

    The endpoint is intentionally thin; all decision logic lives in
    ``EntropyRouter`` and is independently unit-testable.
    """
    return await request.app.state.router.route(body)


# ── Phase 2 ───────────────────────────────────────────────────────────────────

@router.get(
    "/v1/workers",
    response_model=WorkerRegistrySnapshot,
    summary="Latest disaggregated worker registry snapshot",
)
async def workers(request: Request) -> WorkerRegistrySnapshot:
    """
    Return the most recent snapshot of all registered disaggregated workers.

    Includes per-worker KV cache occupancy (used_blocks / total_blocks /
    free_ratio), health status, and the timestamp of the last successful poll.

    When Phase 2 is disabled (``AEGIS_KV_WORKER_ENDPOINTS`` not set), returns
    an empty snapshot rather than 404 — callers can detect Phase 2 availability
    by checking ``snapshot.workers == []``.

    This endpoint never triggers HTTP calls to worker nodes — it only reads the
    immutable snapshot reference from ``WorkerRegistryState.get_snapshot()``.
    Latency is bounded by one ``threading.Lock`` acquire/release.
    """
    return request.app.state.worker_registry.get_snapshot()


# ── Phase 5 ───────────────────────────────────────────────────────────────────

@router.get(
    "/v1/analytics/finops",
    response_model=FinOpsReport,
    summary="Streaming FinOps aggregation from Parquet pipeline",
)
async def finops_analytics(request: Request) -> FinOpsReport:
    """
    Return aggregated FinOps metrics computed from all Parquet log files
    written by the Sprint 3 ``RequestLogger``.

    Metrics returned:
      * ``total_requests``        — total number of logged inference requests
      * ``routing_distribution``  — per-destination request counts (local_edge / cloud_gemini)
      * ``total_cost_saved_usd``  — cumulative USD savings from local edge routing
      * ``p99_latency_ms``        — 99th-percentile end-to-end latency across all requests
      * ``data_available``        — ``False`` when no Parquet files exist yet

    ASGI safety: all Polars CPU work runs inside ``asyncio.to_thread()``
    inside ``FinOpsAnalyticsEngine.compute()``, so the uvloop event loop
    is never blocked by data processing.
    """
    return await request.app.state.analytics_engine.compute()
