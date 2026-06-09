"""
HTTP endpoints.

Sprint 1: GET /healthz, GET /telemetry/gpu
Sprint 2: POST /v1/infer
Phase 2:  GET /v1/workers
Phase 5:  GET /v1/analytics/finops
Hackathon: POST /v1/secops/analyze  (SecOps Reasoning Agent)

All business logic lives in domain classes; endpoints are intentionally thin
(≤5 lines of logic each) to respect the Single Responsibility Principle.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

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


# ── Hackathon: SecOps Reasoning Agent ─────────────────────────────────────────

class SecOpsRequest(BaseModel):
    """入站可疑事件 payload。"""

    suspicious_ip:  str  = Field(default="", description="可疑來源 IP")
    event_type:     str  = Field(default="unknown", description="事件類型，如 brute_force")
    request_count:  int  = Field(default=0, ge=0, description="觀察期間請求次數")
    raw_log:        str  = Field(default="", description="原始日誌片段（已由 antigravity_core 遮蔽 PII）")
    extra:          dict = Field(default_factory=dict, description="其他自定欄位")


@router.post(
    "/v1/secops/analyze",
    summary="SecOps Reasoning Agent — 多步驟威脅分析與防禦決策",
    tags=["SecOps"],
)
async def secops_analyze(body: SecOpsRequest, request: Request) -> dict:
    """
    接收可疑 IP / Payload，呼叫 SecOpsReasoningAgent 執行最多 3 步推理，
    回傳 BLOCK / ALLOW / RATE_LIMIT 防禦決策與推理軌跡。

    完成後非同步寫入推理記錄（Token 消耗 + 決策）至 AgentInferenceLogger，
    供前端 TCO 儀表板讀取。

    Edge Cases
    ----------
    - 空白 payload 欄位：Agent 內部以預設值推理，不回傳 400。
    - API 超時 / Token 耗盡：Agent Fail-Closed，強制回傳 BLOCK。
    - 記錄寫入失敗：捕獲 OSError 於 AgentInferenceLogger 內，不影響主回應。
    """
    payload = {
        "suspicious_ip":  body.suspicious_ip,
        "event_type":     body.event_type,
        "request_count":  body.request_count,
        "raw_log":        body.raw_log,
        **body.extra,
    }

    result: dict = await request.app.state.secops_agent.analyze_threat(payload)

    # 非同步記錄推理結果（不 await 等待完成，確保回應不被磁碟 I/O 阻塞）
    agent_logger = request.app.state.agent_logger
    request.app.state  # keep reference alive
    import asyncio as _asyncio
    _asyncio.ensure_future(
        agent_logger.log_agent_inference(
            action=result.get("action", "BLOCK"),
            simulated_tokens=result.get("simulated_tokens", 0),
            confidence=result.get("confidence", 0.0),
            elapsed_ms=result.get("elapsed_ms", 0.0),
            status=result.get("status", "unknown"),
            reasoning_steps=result.get("reasoning_steps", []),
            extra={"suspicious_ip": body.suspicious_ip, "event_type": body.event_type},
        )
    )

    return result
