"""
Unit tests for EntropyRouter._decide().

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All tests are SYNCHRONOUS — _decide() is a pure function with no I/O.
No async infrastructure, no mocking of HTTP clients, no event loops required.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Boundary cases covered
──────────────────────
#  telemetry_available  entropy_score  vram_ratio   expected
1  False                any            any           CLOUD_GEMINI
2  True                 0.0            0.0           LOCAL_EDGE
3  True                 0.399          0.849         LOCAL_EDGE
4  True                 0.4 (=thresh)  0.5           CLOUD_GEMINI
5  True                 0.3            0.85 (=thr.)  CLOUD_GEMINI
6  True                 any            None          CLOUD_GEMINI
7  True                 0.8            0.3           CLOUD_GEMINI
8  True                 0.3            per_gpu=[]    CLOUD_GEMINI
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.models.infer import RoutingDecision
from app.routing.entropy import SemanticEntropyProbe
from app.routing.router import EntropyRouter
from app.routing.strategies import InferenceBackend
from app.telemetry.state import GpuSnapshot, TelemetrySnapshot, TelemetryState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(
    entropy_threshold: float = 0.4,
    vram_threshold: float = 0.85,
) -> Settings:
    """Build a minimal Settings object for routing tests."""
    # Construct directly to avoid mutating the cached lru_cache singleton.
    return Settings(
        telemetry_poll_interval_s=1.0,
        telemetry_nvml_timeout_s=0.5,
        telemetry_max_backoff_s=60.0,
        telemetry_backoff_factor=2.0,
        telemetry_fail_threshold=3,
        entropy_threshold=entropy_threshold,
        vram_threshold=vram_threshold,
        local_edge_mock_delay_s=0.0,
        cloud_gemini_base_url="https://example.com",
        cloud_gemini_api_key="",
        httpx_max_connections=10,
        httpx_max_keepalive=5,
        httpx_connect_timeout_s=2.0,
        httpx_read_timeout_s=10.0,
        httpx_pool_timeout_s=5.0,
        # Sprint 3
        circuit_breaker_failure_threshold=3,
        circuit_breaker_cooldown_s=30.0,
        finops_log_dir="/tmp/aegis_test_finops",
        finops_flush_interval_s=9999.0,
        finops_buffer_max_size=1000,
        finops_gemini_cost_per_word_usd=0.000003,
        log_level="WARNING",
        rust_fast_model_path="models/minilm-v2-int8.onnx",
        rust_quality_model_path="",
        rust_tokenizer_path="models/tokenizer/tokenizer.json",
        rust_max_seq_len=64,
        rust_num_sessions=4,
        cascade_uncertainty_trigger=0.35,
        cascade_monarch_uncertainty=0.42,
        # Phase 2 defaults (disabled in tests)
        kv_worker_endpoints=[],
        kv_poll_interval_s=1.0,
        kv_prefix_match_depth=32,
        kv_min_free_ratio=0.15,
        kv_eviction_detection_threshold=0.20,
    )


def _make_snapshot(
    available: bool = True,
    vram_ratios: list[Optional[float]] | None = None,
) -> TelemetrySnapshot:
    """Build a TelemetrySnapshot for testing."""
    if not available:
        return TelemetrySnapshot(
            timestamp_ms=int(time.time() * 1000),
            telemetry_available=False,
            gpu_count=None,
            per_gpu=[],
            degrade_reason="test degrade",
        )

    per_gpu = []
    if vram_ratios is not None:
        per_gpu = [
            GpuSnapshot(gpu_index=i, vram_utilization_ratio=r)
            for i, r in enumerate(vram_ratios)
        ]
    else:
        # Default: single healthy GPU at 50%
        per_gpu = [GpuSnapshot(gpu_index=0, vram_utilization_ratio=0.5)]

    return TelemetrySnapshot(
        timestamp_ms=int(time.time() * 1000),
        telemetry_available=True,
        gpu_count=len(per_gpu),
        per_gpu=per_gpu,
    )


def _make_router(
    snapshot: TelemetrySnapshot,
    settings: Settings | None = None,
) -> EntropyRouter:
    """Build an EntropyRouter pre-loaded with a fixed snapshot."""
    state = TelemetryState()
    state.update_snapshot(snapshot)
    return EntropyRouter(
        telemetry_state=state,
        entropy_probe=SemanticEntropyProbe(),
        local_backend=MagicMock(spec=InferenceBackend),
        cloud_backend=MagicMock(spec=InferenceBackend),
        settings=settings or _make_settings(),
    )


# ── Boundary cases ────────────────────────────────────────────────────────────

class TestDecideBoundaryCases:
    """
    The 8 boundary cases from the Sprint 2 plan.
    All are synchronous — no async, no event loop.
    """

    def test_case_1_degrade_always_cloud(self) -> None:
        """#1 telemetry_available=False → CLOUD regardless of entropy/vram."""
        router = _make_router(_make_snapshot(available=False))
        assert router._decide(_make_snapshot(available=False), 0.0) == RoutingDecision.CLOUD_GEMINI
        assert router._decide(_make_snapshot(available=False), 0.9) == RoutingDecision.CLOUD_GEMINI

    def test_case_2_all_signals_green(self) -> None:
        """#2 entropy=0.0, vram=0.0 → LOCAL_EDGE (ideal conditions)."""
        snap = _make_snapshot(vram_ratios=[0.0])
        router = _make_router(snap)
        assert router._decide(snap, 0.0) == RoutingDecision.LOCAL_EDGE

    def test_case_3_just_below_both_thresholds(self) -> None:
        """#3 entropy=0.399, vram=0.849 → LOCAL_EDGE (strict less-than)."""
        snap = _make_snapshot(vram_ratios=[0.849])
        router = _make_router(snap)
        assert router._decide(snap, 0.399) == RoutingDecision.LOCAL_EDGE

    def test_case_4_entropy_at_boundary_is_cloud(self) -> None:
        """#4 entropy=0.4 (exactly equal to threshold) → CLOUD_GEMINI."""
        snap = _make_snapshot(vram_ratios=[0.5])
        router = _make_router(snap)
        # threshold is 0.4; condition is entropy < 0.4 (strict); 0.4 is NOT < 0.4
        assert router._decide(snap, 0.4) == RoutingDecision.CLOUD_GEMINI

    def test_case_5_vram_at_boundary_is_cloud(self) -> None:
        """#5 vram=0.85 (exactly equal to threshold) → CLOUD_GEMINI."""
        snap = _make_snapshot(vram_ratios=[0.85])
        router = _make_router(snap)
        # condition is vram < 0.85 (strict); 0.85 is NOT < 0.85
        assert router._decide(snap, 0.3) == RoutingDecision.CLOUD_GEMINI

    def test_case_6_vram_none_is_cloud(self) -> None:
        """#6 vram_utilization_ratio=None (partial GPU failure) → CLOUD_GEMINI."""
        snap = _make_snapshot(vram_ratios=[None])
        router = _make_router(snap)
        assert router._decide(snap, 0.1) == RoutingDecision.CLOUD_GEMINI

    def test_case_7_high_entropy_is_cloud(self) -> None:
        """#7 entropy=0.8, vram=0.3 → CLOUD_GEMINI (entropy dominates)."""
        snap = _make_snapshot(vram_ratios=[0.3])
        router = _make_router(snap)
        assert router._decide(snap, 0.8) == RoutingDecision.CLOUD_GEMINI

    def test_case_8_empty_per_gpu_is_cloud(self) -> None:
        """#8 telemetry=True but per_gpu=[] (no GPU devices) → CLOUD_GEMINI."""
        snap = _make_snapshot(vram_ratios=[])
        router = _make_router(snap)
        assert router._decide(snap, 0.1) == RoutingDecision.CLOUD_GEMINI


class TestGetAggregateVram:
    """Unit tests for the _get_aggregate_vram static helper."""

    def test_single_gpu(self) -> None:
        snap = _make_snapshot(vram_ratios=[0.6])
        assert EntropyRouter._get_aggregate_vram(snap) == pytest.approx(0.6)

    def test_multi_gpu_returns_max(self) -> None:
        """When multiple GPUs are present, we take the MAXIMUM (most conservative)."""
        snap = _make_snapshot(vram_ratios=[0.3, 0.7, 0.5])
        assert EntropyRouter._get_aggregate_vram(snap) == pytest.approx(0.7)

    def test_all_none_returns_none(self) -> None:
        snap = _make_snapshot(vram_ratios=[None, None])
        assert EntropyRouter._get_aggregate_vram(snap) is None

    def test_mixed_none_ignores_none(self) -> None:
        snap = _make_snapshot(vram_ratios=[None, 0.6, None])
        assert EntropyRouter._get_aggregate_vram(snap) == pytest.approx(0.6)

    def test_empty_per_gpu_returns_none(self) -> None:
        snap = _make_snapshot(vram_ratios=[])
        assert EntropyRouter._get_aggregate_vram(snap) is None


class TestThresholdConfiguration:
    """Verify that custom thresholds override defaults correctly."""

    def test_custom_entropy_threshold(self) -> None:
        settings = _make_settings(entropy_threshold=0.7)
        snap = _make_snapshot(vram_ratios=[0.3])
        router = _make_router(snap, settings=settings)
        # entropy=0.5 should now be LOCAL (0.5 < 0.7)
        assert router._decide(snap, 0.5) == RoutingDecision.LOCAL_EDGE

    def test_custom_vram_threshold(self) -> None:
        settings = _make_settings(vram_threshold=0.5)
        snap = _make_snapshot(vram_ratios=[0.4])
        router = _make_router(snap, settings=settings)
        # vram=0.4 < 0.5 and entropy=0.1 < 0.4 → LOCAL
        assert router._decide(snap, 0.1) == RoutingDecision.LOCAL_EDGE
        # vram=0.5 >= 0.5 → CLOUD (strict boundary)
        snap_full = _make_snapshot(vram_ratios=[0.5])
        assert router._decide(snap_full, 0.1) == RoutingDecision.CLOUD_GEMINI
