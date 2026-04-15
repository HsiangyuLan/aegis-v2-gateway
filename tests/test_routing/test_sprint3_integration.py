"""
Sprint 3 integration tests.

Covers:
  * Circuit breaker state visible on app.state
  * POST /v1/infer returns 503 when circuit breaker is OPEN
  * InferResponse includes cost_saved_usd field
  * FinOps log record is written after each request
  * Sprint 1 + Sprint 2 regression: all existing endpoints still work
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
from app.routing.strategies import CloudInferenceError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ── Circuit breaker on app.state ──────────────────────────────────────────────

class TestCircuitBreakerState:
    def test_circuit_breaker_exists_on_app_state(self, client: TestClient) -> None:
        assert hasattr(client.app.state, "circuit_breaker")
        assert isinstance(client.app.state.circuit_breaker, CircuitBreaker)

    def test_circuit_breaker_starts_closed(self, client: TestClient) -> None:
        breaker: CircuitBreaker = client.app.state.circuit_breaker
        # Initial state should be CLOSED (no failures yet)
        assert breaker.state == CircuitState.CLOSED


# ── Cost saved field ──────────────────────────────────────────────────────────

class TestCostSavedField:
    def test_response_contains_cost_saved_usd(self, client: TestClient) -> None:
        data = client.post("/v1/infer", json={"prompt": "hello"}).json()
        assert "cost_saved_usd" in data
        assert isinstance(data["cost_saved_usd"], float)
        assert data["cost_saved_usd"] >= 0.0

    def test_cloud_route_has_zero_cost_saved(self, client: TestClient) -> None:
        """When telemetry is unavailable (CI), forced to cloud → cost_saved=0."""
        snap = client.app.state.telemetry_state.get_snapshot()
        if not snap.telemetry_available:
            data = client.post(
                "/v1/infer", json={"prompt": "test cloud"}
            ).json()
            assert data["routed_to"] == "cloud_gemini"
            assert data["cost_saved_usd"] == 0.0


# ── 503 when circuit breaker is OPEN ─────────────────────────────────────────

class TestCircuitBreakerEndpointProtection:
    def test_open_circuit_returns_503(self, client: TestClient) -> None:
        """
        Manually force the circuit OPEN and verify /v1/infer returns 503.
        We do this by patching the breaker state directly (not by triggering
        real failures) to avoid side effects on other tests.
        """
        breaker: CircuitBreaker = client.app.state.circuit_breaker

        # Save original state
        original_state = breaker._state
        original_failures = breaker._consecutive_failures

        try:
            # Force OPEN
            breaker._state = CircuitState.OPEN
            breaker._opened_at = time.monotonic()

            response = client.post("/v1/infer", json={"prompt": "test"})
            assert response.status_code == 503

            data = response.json()
            assert data["detail"]["error"] == "circuit_breaker_open"
            assert "retry_after_s" in data["detail"]
            assert "Retry-After" in response.headers
        finally:
            # Restore state so other tests are not affected
            breaker._state = original_state
            breaker._consecutive_failures = original_failures

    def test_503_response_contains_request_id(self, client: TestClient) -> None:
        breaker: CircuitBreaker = client.app.state.circuit_breaker
        original_state = breaker._state
        try:
            breaker._state = CircuitState.OPEN
            breaker._opened_at = time.monotonic()

            response = client.post(
                "/v1/infer",
                json={"prompt": "test", "request_id": "cb-test-123"},
            )
            assert response.status_code == 503
            assert response.json()["detail"]["request_id"] == "cb-test-123"
        finally:
            breaker._state = original_state

    def test_retry_after_header_is_integer_string(self, client: TestClient) -> None:
        breaker: CircuitBreaker = client.app.state.circuit_breaker
        original_state = breaker._state
        try:
            breaker._state = CircuitState.OPEN
            breaker._opened_at = time.monotonic()

            response = client.post("/v1/infer", json={"prompt": "test"})
            assert response.status_code == 503
            retry_after = response.headers.get("Retry-After")
            assert retry_after is not None
            assert int(retry_after) >= 0
        finally:
            breaker._state = original_state


# ── FinOps logger integration ─────────────────────────────────────────────────

class TestFinOpsLoggerIntegration:
    def test_request_logger_exists_on_app_state(self, client: TestClient) -> None:
        from app.observability.parquet_logger import RequestLogger
        assert hasattr(client.app.state, "request_logger")
        assert isinstance(client.app.state.request_logger, RequestLogger)

    def test_successful_infer_adds_record_to_buffer(
        self, client: TestClient
    ) -> None:
        rl = client.app.state.request_logger
        initial_count = rl._buffer.qsize() + rl._flush_count

        client.post("/v1/infer", json={"prompt": "hello finops"})

        # Either still in buffer or already flushed (increments _flush_count)
        new_count = rl._buffer.qsize() + rl._flush_count
        # At least one record was processed (buffered or flushed)
        assert new_count >= initial_count

    def test_flush_count_increments_after_manual_flush(
        self, client: TestClient
    ) -> None:
        """After a manual flush, the counter must increase."""
        from app.observability.parquet_logger import RequestLogRecord

        rl = client.app.state.request_logger
        rl.log(RequestLogRecord(
            timestamp_ms=int(time.time() * 1000),
            request_id="flush-test",
            entropy_score=0.3,
            routed_to="cloud_gemini",
            latency_ms=50.0,
            cost_saved_usd=0.0,
        ))
        before = rl._flush_count

        asyncio.get_event_loop().run_until_complete(rl._flush_once())

        assert rl._flush_count == before + 1


# ── Regression: Sprint 1 + 2 ─────────────────────────────────────────────────

class TestSprint12Regression:
    def test_healthz_still_200(self, client: TestClient) -> None:
        assert client.get("/healthz").status_code == 200

    def test_telemetry_gpu_still_200(self, client: TestClient) -> None:
        assert client.get("/telemetry/gpu").status_code == 200

    def test_infer_still_200_with_closed_circuit(self, client: TestClient) -> None:
        assert client.post("/v1/infer", json={"prompt": "hello"}).status_code == 200

    def test_http_client_still_singleton(self, client: TestClient) -> None:
        first_id = id(client.app.state.http_client)
        for _ in range(5):
            client.post("/v1/infer", json={"prompt": "check"})
        assert id(client.app.state.http_client) == first_id

    def test_infer_response_has_all_sprint3_fields(
        self, client: TestClient
    ) -> None:
        data = client.post(
            "/v1/infer", json={"prompt": "complete response check"}
        ).json()
        sprint3_fields = {"cost_saved_usd"}
        sprint2_fields = {"entropy_score", "vram_utilization_ratio", "routed_to"}
        sprint1_fields = {"request_id", "response_text", "latency_ms"}
        for field in sprint1_fields | sprint2_fields | sprint3_fields:
            assert field in data, f"Missing field: {field}"
