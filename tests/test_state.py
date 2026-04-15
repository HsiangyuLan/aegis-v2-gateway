"""
Tests for TelemetryState thread-safety and TelemetrySnapshot immutability.

These tests do NOT require NVML / GPU hardware.
"""
from __future__ import annotations

import threading
import time
from typing import List

import pytest

from app.telemetry.state import GpuSnapshot, TelemetrySnapshot, TelemetryState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gpu(idx: int = 0) -> GpuSnapshot:
    return GpuSnapshot(
        gpu_index=idx,
        memory_used_bytes=4 * 1024 ** 3,
        memory_free_bytes=4 * 1024 ** 3,
        memory_total_bytes=8 * 1024 ** 3,
        vram_utilization_ratio=0.5,
        sm_utilization_percent=30,
        memory_bandwidth_utilization_percent=20,
    )


def _snap(available: bool = True, ts: int | None = None) -> TelemetrySnapshot:
    return TelemetrySnapshot(
        timestamp_ms=ts or int(time.time() * 1000),
        telemetry_available=available,
        gpu_count=1 if available else None,
        per_gpu=[_gpu()] if available else [],
    )


# ── TelemetryState ────────────────────────────────────────────────────────────

class TestTelemetryStateInit:
    def test_initial_snapshot_is_degrade(self) -> None:
        state = TelemetryState()
        snap = state.get_snapshot()
        assert snap.telemetry_available is False

    def test_initial_degrade_reason_is_set(self) -> None:
        state = TelemetryState()
        snap = state.get_snapshot()
        assert snap.degrade_reason is not None
        assert len(snap.degrade_reason) > 0

    def test_initial_per_gpu_is_empty(self) -> None:
        state = TelemetryState()
        assert state.get_snapshot().per_gpu == []


class TestTelemetryStateUpdate:
    def test_update_replaces_snapshot(self) -> None:
        state = TelemetryState()
        new_snap = _snap(available=True)
        state.update_snapshot(new_snap)
        assert state.get_snapshot() is new_snap

    def test_update_reflects_new_values(self) -> None:
        state = TelemetryState()
        state.update_snapshot(_snap(available=True))
        snap = state.get_snapshot()
        assert snap.telemetry_available is True
        assert snap.gpu_count == 1

    def test_multiple_updates_returns_latest(self) -> None:
        state = TelemetryState()
        for i in range(5):
            state.update_snapshot(_snap(ts=i))
        assert state.get_snapshot().timestamp_ms == 4


class TestTelemetryStateThreadSafety:
    def test_concurrent_readers_never_raise(self) -> None:
        """Many reader threads must not observe partial / corrupt state."""
        state = TelemetryState()
        state.update_snapshot(_snap(available=True))
        errors: List[Exception] = []

        def reader() -> None:
            for _ in range(500):
                try:
                    snap = state.get_snapshot()
                    _ = snap.telemetry_available  # access a field
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread-safety violation: {errors}"

    def test_concurrent_readers_and_writer(self) -> None:
        """Readers and a single writer must not corrupt each other."""
        state = TelemetryState()
        errors: List[Exception] = []
        stop_flag = threading.Event()

        def reader() -> None:
            while not stop_flag.is_set():
                try:
                    snap = state.get_snapshot()
                    assert isinstance(snap.telemetry_available, bool)
                except Exception as exc:
                    errors.append(exc)

        def writer() -> None:
            for i in range(200):
                state.update_snapshot(_snap(ts=i))

        readers = [threading.Thread(target=reader) for _ in range(8)]
        w = threading.Thread(target=writer)

        for r in readers:
            r.start()
        w.start()
        w.join()
        stop_flag.set()
        for r in readers:
            r.join()

        assert not errors, f"Thread-safety violation: {errors}"


# ── TelemetrySnapshot immutability ────────────────────────────────────────────

class TestTelemetrySnapshotImmutability:
    def test_snapshot_fields_cannot_be_reassigned(self) -> None:
        snap = _snap(available=False)
        with pytest.raises(Exception):
            snap.telemetry_available = True  # type: ignore[misc]

    def test_gpu_snapshot_fields_cannot_be_reassigned(self) -> None:
        gpu = _gpu()
        with pytest.raises(Exception):
            gpu.gpu_index = 99  # type: ignore[misc]

    def test_vram_utilization_ratio_is_correct_proxy(self) -> None:
        gpu = GpuSnapshot(
            gpu_index=0,
            memory_used_bytes=2 * 1024 ** 3,
            memory_total_bytes=8 * 1024 ** 3,
            vram_utilization_ratio=round(2 / 8, 6),
        )
        assert gpu.vram_utilization_ratio == pytest.approx(0.25, abs=1e-6)

    def test_none_fields_are_allowed(self) -> None:
        """All optional fields should accept None without validation error."""
        gpu = GpuSnapshot(gpu_index=0)
        assert gpu.memory_used_bytes is None
        assert gpu.vram_utilization_ratio is None
        assert gpu.sm_utilization_percent is None
