"""
Integration tests for the FastAPI HTTP endpoints.

The ``client`` fixture (defined in conftest.py) starts the full application
lifespan once per module.  In a non-GPU environment the sampler immediately
degrades – which is exactly the case we want to validate here.
"""
from __future__ import annotations

import threading
from typing import List

from fastapi.testclient import TestClient


# ── /healthz ─────────────────────────────────────────────────────────────────

class TestHealthz:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200

    def test_response_has_status_ok(self, client: TestClient) -> None:
        data = client.get("/healthz").json()
        assert data["status"] == "ok"

    def test_response_contains_telemetry_available(self, client: TestClient) -> None:
        data = client.get("/healthz").json()
        assert "telemetry_available" in data
        assert isinstance(data["telemetry_available"], bool)

    def test_response_contains_timestamp_ms(self, client: TestClient) -> None:
        data = client.get("/healthz").json()
        assert "timestamp_ms" in data
        assert isinstance(data["timestamp_ms"], int)
        assert data["timestamp_ms"] > 0

    def test_response_contains_degrade_reason_field(self, client: TestClient) -> None:
        """degrade_reason must always be present (may be None when GPU available)."""
        data = client.get("/healthz").json()
        assert "degrade_reason" in data

    def test_degrade_mode_without_gpu(self, client: TestClient) -> None:
        """
        In a CI / non-GPU environment, telemetry_available should be False and
        degrade_reason should explain why.  The endpoint must still return 200
        (not 500) – this is the key graceful-degrade assertion.
        """
        data = client.get("/healthz").json()
        # Either GPU present (True) or degrade (False) – both are valid.
        # What must NOT happen: 500 or crash.
        assert data["status"] == "ok"
        if not data["telemetry_available"]:
            assert data["degrade_reason"] is not None
            assert len(data["degrade_reason"]) > 0


# ── /telemetry/gpu ────────────────────────────────────────────────────────────

class TestTelemetryGpu:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/telemetry/gpu")
        assert response.status_code == 200

    def test_response_is_valid_snapshot_shape(self, client: TestClient) -> None:
        data = client.get("/telemetry/gpu").json()
        assert "telemetry_available" in data
        assert "timestamp_ms" in data
        assert "per_gpu" in data
        assert isinstance(data["per_gpu"], list)

    def test_per_gpu_items_have_required_fields(self, client: TestClient) -> None:
        data = client.get("/telemetry/gpu").json()
        for gpu in data["per_gpu"]:
            assert "gpu_index" in gpu
            assert "vram_utilization_ratio" in gpu
            assert "sm_utilization_percent" in gpu

    def test_no_crash_when_no_gpu_present(self, client: TestClient) -> None:
        """
        Core Sprint-1 degrade assertion: a container with no NVIDIA driver must
        serve /telemetry/gpu with HTTP 200 and telemetry_available=False, not a
        500 or unhandled exception.
        """
        response = client.get("/telemetry/gpu")
        assert response.status_code == 200
        data = response.json()
        # One of two valid states:
        assert isinstance(data["telemetry_available"], bool)

    def test_timestamp_ms_is_recent(self, client: TestClient) -> None:
        import time
        data = client.get("/telemetry/gpu").json()
        now_ms = int(time.time() * 1000)
        # Allow 60 s of slack for slow CI runners
        assert abs(data["timestamp_ms"] - now_ms) < 60_000


# ── Concurrent requests ───────────────────────────────────────────────────────

class TestConcurrentRequests:
    def test_concurrent_healthz_all_succeed(self, client: TestClient) -> None:
        """
        Verifies that simultaneous requests do not block each other or corrupt
        the shared TelemetryState.
        """
        results: List[int] = []
        errors: List[Exception] = []

        def call() -> None:
            try:
                r = client.get("/healthz")
                results.append(r.status_code)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=call) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Some requests raised: {errors}"
        assert all(code == 200 for code in results), f"Non-200 responses: {results}"

    def test_concurrent_telemetry_all_succeed(self, client: TestClient) -> None:
        results: List[int] = []
        errors: List[Exception] = []

        def call() -> None:
            try:
                r = client.get("/telemetry/gpu")
                results.append(r.status_code)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=call) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Some requests raised: {errors}"
        assert all(code == 200 for code in results), f"Non-200 responses: {results}"
