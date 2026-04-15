"""
EntropyRouter — the dual-routing decision engine.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Routing decision logic (precedence order)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ``telemetry_available is False``
   GPU telemetry is in degrade mode.  Without reliable hardware data we
   cannot safely route to the local edge.
   Decision: FORCE Cloud.

2. ``vram_utilization_ratio is None``
   Telemetry available but all per-GPU memory reads failed (partial device
   fault).  Cannot determine KV-cache headroom.
   Decision: Conservative → FORCE Cloud.

3. ``vram_utilization_ratio >= vram_threshold (0.85)``
   Local VRAM is dangerously full.  Risk of OOM in PagedAttention allocator.
   Decision: FORCE Cloud.

4. ``entropy_score >= entropy_threshold (0.4)``
   High semantic uncertainty → deep multi-step reasoning required.
   Decision: Cloud for quality.

5. All conditions clear → Local Edge (zero API cost, sub-second TTFT).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sprint 3 additions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

* ``CircuitBreakerOpenError`` is now caught in ``_execute()`` and mapped to
  HTTP 503 Service Unavailable with a ``Retry-After`` header.

* ``cost_saved_usd`` is computed per-request (positive when routed locally,
  zero when routed to cloud) and included in ``InferResponse``.

* Every completed request is logged to the ``RequestLogger`` for Parquet-based
  FinOps analysis.  Logging is **non-blocking** (``logger.log()`` is sync and
  never awaits); a failed log never affects the response.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.models.infer import InferRequest, InferResponse, RoutingDecision
from app.resilience.circuit_breaker import CircuitBreakerOpenError
from app.routing.entropy import SemanticEntropyProbe
from app.routing.strategies import (
    CloudInferenceError,
    CloudInferenceTimeoutError,
    InferenceBackend,
    LocalEdgeBackend,
)
from app.telemetry.state import TelemetrySnapshot, TelemetryState

if TYPE_CHECKING:
    from app.observability.parquet_logger import RequestLogger, RequestLogRecord
    from app.routing.kv_router import KVAwareRouter
    from app.routing.worker_registry import WorkerInfo

logger = logging.getLogger(__name__)


class EntropyRouter:
    """
    Dual-routing engine integrating semantic entropy and hardware telemetry.

    All dependencies are injected at construction time so the class is fully
    testable without a running FastAPI application.

    ``request_logger`` is optional for backward compatibility with Sprint 2
    tests; when ``None``, FinOps logging is silently skipped.

    Phase 2 addition
    ────────────────
    ``kv_router`` is an optional ``KVAwareRouter``.  When present and the
    Stage 1 decision is ``LOCAL_EDGE``, the KVAwareRouter performs Stage 2
    worker selection.  When ``None`` (default, Sprint 3 behaviour), the
    existing single-backend local path is used unchanged.
    """

    def __init__(
        self,
        telemetry_state: TelemetryState,
        entropy_probe: SemanticEntropyProbe,
        local_backend: InferenceBackend,
        cloud_backend: InferenceBackend,
        settings: Settings,
        request_logger: "RequestLogger | None" = None,
        kv_router: "KVAwareRouter | None" = None,
    ) -> None:
        self._telemetry = telemetry_state
        self._probe = entropy_probe
        self._local = local_backend
        self._cloud = cloud_backend
        self._settings = settings
        self._request_logger = request_logger
        self._kv_router = kv_router

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(self, request: InferRequest) -> InferResponse:
        """
        Evaluate the prompt, make a routing decision, execute inference,
        and return a fully-annotated ``InferResponse``.
        """
        t0 = time.monotonic()

        # Step 1 — Read telemetry snapshot (O(1), one Lock acquire)
        snapshot: TelemetrySnapshot = self._telemetry.get_snapshot()

        # Step 2 — Compute semantic entropy (< 1 ms, pure Python, safe on loop)
        entropy_score: float = self._probe.calculate(request.prompt)

        # Step 3 — Pure routing decision
        decision: RoutingDecision = self._decide(snapshot, entropy_score)

        # Step 4 — Capture VRAM ratio + cost estimate for response metadata
        vram_ratio: Optional[float] = self._get_aggregate_vram(snapshot)
        cost_saved_usd: float = self._compute_cost_saved(decision, request.prompt)

        logger.debug(
            "request_id=%s entropy=%.4f vram=%s telemetry=%s → %s",
            request.request_id,
            entropy_score,
            f"{vram_ratio:.3f}" if vram_ratio is not None else "None",
            snapshot.telemetry_available,
            decision.value,
        )

        # Step 5 — Execute inference on chosen backend
        # Phase 2: _execute returns (response_text, selected_worker_id, kv_hit)
        response_text, selected_worker_id, kv_prefix_hit = await self._execute(
            decision, request
        )

        latency_ms = (time.monotonic() - t0) * 1000.0

        response = InferResponse(
            request_id=request.request_id,
            routed_to=decision,
            response_text=response_text,
            entropy_score=entropy_score,
            vram_utilization_ratio=vram_ratio,
            telemetry_available=snapshot.telemetry_available,
            cost_saved_usd=round(cost_saved_usd, 8),
            latency_ms=round(latency_ms, 3),
            selected_worker_id=selected_worker_id,
            kv_prefix_hit=kv_prefix_hit,
        )

        # Step 6 — Non-blocking FinOps log (never raises; never delays response)
        self._emit_log(response)

        return response

    # ------------------------------------------------------------------
    # Pure decision function (synchronous, no I/O, fully unit-testable)
    # ------------------------------------------------------------------

    def _decide(
        self,
        snapshot: TelemetrySnapshot,
        entropy_score: float,
    ) -> RoutingDecision:
        """
        Map (snapshot, entropy_score) → RoutingDecision.

        Pure function: reads only its arguments, no side effects.
        """
        if not snapshot.telemetry_available:
            return RoutingDecision.CLOUD_GEMINI

        vram_ratio = self._get_aggregate_vram(snapshot)
        if vram_ratio is None or vram_ratio >= self._settings.vram_threshold:
            return RoutingDecision.CLOUD_GEMINI

        if entropy_score >= self._settings.entropy_threshold:
            return RoutingDecision.CLOUD_GEMINI

        return RoutingDecision.LOCAL_EDGE

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _execute(
        self, decision: RoutingDecision, request: InferRequest
    ) -> tuple[str, Optional[str], bool]:
        """
        Dispatch to the chosen backend; map domain exceptions to HTTP errors.

        Returns
        -------
        tuple[response_text, selected_worker_id, kv_prefix_hit]
            * ``response_text``      — model output string.
            * ``selected_worker_id`` — the Phase 2 worker used, or ``None``.
            * ``kv_prefix_hit``      — True when a prefix cache hit drove
                                       Phase 2 worker selection.
        """
        # ── Phase 2: KV-aware worker selection ────────────────────────────────
        if decision == RoutingDecision.LOCAL_EDGE and self._kv_router is not None:
            result = await self._kv_router.select_worker(
                request.prompt, request.request_id
            )
            if result is None:
                # No healthy workers → cloud fallback (uses existing exception
                # handling below via the cloud backend branch).
                logger.warning(
                    "request_id=%s KVAwareRouter returned no healthy workers "
                    "— falling back to cloud backend.",
                    request.request_id,
                )
                try:
                    text = await self._cloud.infer(
                        prompt=request.prompt,
                        request_id=request.request_id,
                    )
                    return text, None, False
                except (
                    CircuitBreakerOpenError,
                    CloudInferenceTimeoutError,
                    CloudInferenceError,
                ) as exc:
                    self._handle_backend_exception(exc, request.request_id)

            worker, kv_prefix_hit = result
            assert isinstance(self._local, LocalEdgeBackend), (
                "Phase 2 KV-aware routing requires local_backend to be "
                "LocalEdgeBackend, not a bare Protocol implementation."
            )
            try:
                text = await self._local.infer(
                    prompt=request.prompt,
                    request_id=request.request_id,
                    worker=worker,
                )
                return text, worker.worker_id, kv_prefix_hit
            except Exception as exc:
                # Unexpected error from local worker — treat as non-fatal,
                # re-raise so the outer handler returns 500.
                raise

        # ── Sprint 3 path (Phase 2 disabled or cloud decision) ────────────────
        backend = (
            self._local
            if decision == RoutingDecision.LOCAL_EDGE
            else self._cloud
        )
        try:
            text = await backend.infer(
                prompt=request.prompt,
                request_id=request.request_id,
            )
            return text, None, False
        except CircuitBreakerOpenError as exc:
            # Circuit breaker is OPEN: fast-fail with 503 + Retry-After hint.
            logger.warning(
                "request_id=%s circuit breaker OPEN (retry in %.1fs): %s",
                request.request_id,
                exc.retry_after_s,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "circuit_breaker_open",
                    "message": str(exc),
                    "retry_after_s": round(exc.retry_after_s, 1),
                    "request_id": request.request_id,
                },
                headers={"Retry-After": str(int(exc.retry_after_s) + 1)},
            ) from exc
        except CloudInferenceTimeoutError as exc:
            logger.warning(
                "request_id=%s cloud timeout: %s", request.request_id, exc
            )
            raise HTTPException(
                status_code=504,
                detail={
                    "error": "cloud_timeout",
                    "message": str(exc),
                    "request_id": request.request_id,
                },
            ) from exc
        except CloudInferenceError as exc:
            status = exc.status_code or 502
            logger.error(
                "request_id=%s cloud error (HTTP %s): %s",
                request.request_id,
                status,
                exc,
            )
            raise HTTPException(
                status_code=status if 400 <= status < 600 else 502,
                detail={
                    "error": "cloud_inference_error",
                    "message": str(exc),
                    "request_id": request.request_id,
                },
            ) from exc

    def _handle_backend_exception(
        self, exc: Exception, request_id: str
    ) -> None:
        """
        Convert backend exceptions to HTTPException.  Shared helper used by
        both the Phase 2 KV-fallback cloud path and the Sprint 3 main path.
        Never returns; always raises HTTPException.
        """
        if isinstance(exc, CircuitBreakerOpenError):
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "circuit_breaker_open",
                    "message": str(exc),
                    "retry_after_s": round(exc.retry_after_s, 1),
                    "request_id": request_id,
                },
                headers={"Retry-After": str(int(exc.retry_after_s) + 1)},
            ) from exc
        if isinstance(exc, CloudInferenceTimeoutError):
            raise HTTPException(
                status_code=504,
                detail={
                    "error": "cloud_timeout",
                    "message": str(exc),
                    "request_id": request_id,
                },
            ) from exc
        if isinstance(exc, CloudInferenceError):
            status = exc.status_code or 502
            raise HTTPException(
                status_code=status if 400 <= status < 600 else 502,
                detail={
                    "error": "cloud_inference_error",
                    "message": str(exc),
                    "request_id": request_id,
                },
            ) from exc
        raise exc  # unexpected — re-raise as-is

    def _compute_cost_saved(
        self, decision: RoutingDecision, prompt: str
    ) -> float:
        """
        Estimate USD saved by routing to local_edge.

        Uses a per-word cost model calibrated to Gemini Pro pricing.
        The configurable ``finops_gemini_cost_per_word_usd`` lets operators
        update the model when Gemini pricing changes without a code deploy.

        Returns 0.0 when routed to cloud (no savings; API cost was incurred).
        """
        if decision != RoutingDecision.LOCAL_EDGE:
            return 0.0
        word_count = len(prompt.split())
        return word_count * self._settings.finops_gemini_cost_per_word_usd

    def _emit_log(self, response: InferResponse) -> None:
        """
        Emit a FinOps log record.  Never raises; never blocks.

        Called after the response is fully assembled so that latency_ms
        and cost_saved_usd are available as logged fields.
        """
        if self._request_logger is None:
            return
        try:
            from app.observability.parquet_logger import RequestLogRecord

            self._request_logger.log(
                RequestLogRecord(
                    timestamp_ms=int(time.time() * 1000),
                    request_id=response.request_id,
                    entropy_score=response.entropy_score,
                    routed_to=response.routed_to.value,
                    latency_ms=response.latency_ms,
                    cost_saved_usd=response.cost_saved_usd,
                    selected_worker_id=response.selected_worker_id,
                    kv_prefix_hit=response.kv_prefix_hit,
                )
            )
        except Exception:
            # Observability must never degrade inference quality.
            logger.debug("FinOps log emit failed (non-fatal).", exc_info=True)

    @staticmethod
    def _get_aggregate_vram(snapshot: TelemetrySnapshot) -> Optional[float]:
        """Return the MAX vram_utilization_ratio across all GPUs (most conservative)."""
        ratios = [
            g.vram_utilization_ratio
            for g in snapshot.per_gpu
            if g.vram_utilization_ratio is not None
        ]
        return max(ratios) if ratios else None
