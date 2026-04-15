"""
Request and response models for the /v1/infer endpoint.

``RoutingDecision`` uses ``str`` as its mixin so that JSON serialization
produces ``"local_edge"`` / ``"cloud_gemini"`` strings directly — no extra
conversion needed in the FinOps log pipeline (Sprint 3).
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RoutingDecision(str, Enum):
    """Which backend handled this inference request."""

    LOCAL_EDGE = "local_edge"
    CLOUD_GEMINI = "cloud_gemini"


class InferRequest(BaseModel):
    """Incoming inference request payload."""

    prompt: str
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Caller-supplied or auto-generated UUID for request tracing.",
    )


class InferResponse(BaseModel):
    """Full response including routing metadata for observability."""

    request_id: str
    routed_to: RoutingDecision
    response_text: str

    # ── Routing signal values captured at decision time ───────────────────────
    entropy_score: float
    # None when telemetry is unavailable (degrade mode) or when all GPU
    # vram_utilization_ratio fields are None (partial device failure).
    vram_utilization_ratio: Optional[float] = None
    telemetry_available: bool

    # ── FinOps ────────────────────────────────────────────────────────────────
    # Estimated USD saved by routing to local_edge instead of cloud_gemini.
    # 0.0 when routed to cloud (no savings; cloud API cost was incurred).
    # Positive when routed locally (the avoided Gemini API call cost).
    cost_saved_usd: float = 0.0

    # ── Phase 2: KV Cache-Aware Routing ──────────────────────────────────────
    # ID of the specific disaggregated worker selected by KVAwareRouter.
    # None when Phase 2 is disabled or cloud was chosen.
    selected_worker_id: Optional[str] = None

    # True when the KVAwareRouter found a prefix cache hit on the selected
    # worker, meaning KV computation can be partially reused (lower TTFT).
    kv_prefix_hit: bool = False

    # ── Observability ─────────────────────────────────────────────────────────
    latency_ms: float
