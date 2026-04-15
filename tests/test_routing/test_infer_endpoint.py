"""
Integration tests for POST /v1/infer and the httpx singleton guarantee.

The module-scoped ``client`` fixture starts the full application lifespan
once — including the NVML sampler (which degrades gracefully in CI) and the
httpx.AsyncClient connection pool.
"""
from __future__ import annotations

import threading
from typing import List

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.infer import RoutingDecision


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ── httpx singleton guarantee ─────────────────────────────────────────────────

class TestHttpxSingleton:
    """
    The most critical Sprint 2 architectural guarantee:
    ONE httpx.AsyncClient instance for the entire process lifetime.
    """

    def test_http_client_exists_on_app_state(self, client: TestClient) -> None:
        import httpx
        assert hasattr(client.app.state, "http_client")
        assert isinstance(client.app.state.http_client, httpx.AsyncClient)

    def test_http_client_is_same_instance_across_requests(
        self, client: TestClient
    ) -> None:
        """Ten consecutive requests must see the exact same client object id."""
        first_id = id(client.app.state.http_client)
        for _ in range(10):
            client.post("/v1/infer", json={"prompt": "hello"})
        assert id(client.app.state.http_client) == first_id

    def test_router_exists_on_app_state(self, client: TestClient) -> None:
        from app.routing.router import EntropyRouter
        assert hasattr(client.app.state, "router")
        assert isinstance(client.app.state.router, EntropyRouter)


# ── Basic endpoint behaviour ──────────────────────────────────────────────────

class TestInferEndpoint:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.post("/v1/infer", json={"prompt": "What is 2+2?"})
        assert response.status_code == 200

    def test_response_contains_required_fields(self, client: TestClient) -> None:
        data = client.post("/v1/infer", json={"prompt": "hello"}).json()
        assert "request_id" in data
        assert "routed_to" in data
        assert "response_text" in data
        assert "entropy_score" in data
        assert "latency_ms" in data
        assert "telemetry_available" in data

    def test_routed_to_is_valid_enum_value(self, client: TestClient) -> None:
        data = client.post("/v1/infer", json={"prompt": "hello"}).json()
        assert data["routed_to"] in {
            RoutingDecision.LOCAL_EDGE.value,
            RoutingDecision.CLOUD_GEMINI.value,
        }

    def test_entropy_score_in_range(self, client: TestClient) -> None:
        data = client.post("/v1/infer", json={"prompt": "hello world"}).json()
        assert 0.0 <= data["entropy_score"] <= 1.0

    def test_latency_ms_is_positive(self, client: TestClient) -> None:
        data = client.post("/v1/infer", json={"prompt": "test"}).json()
        assert data["latency_ms"] > 0

    def test_request_id_echoed_back(self, client: TestClient) -> None:
        response = client.post(
            "/v1/infer", json={"prompt": "hello", "request_id": "test-123"}
        ).json()
        assert response["request_id"] == "test-123"

    def test_auto_request_id_assigned_when_not_provided(
        self, client: TestClient
    ) -> None:
        data = client.post("/v1/infer", json={"prompt": "hello"}).json()
        assert len(data["request_id"]) > 0

    def test_missing_prompt_returns_422(self, client: TestClient) -> None:
        response = client.post("/v1/infer", json={})
        assert response.status_code == 422


# ── Routing path coverage ─────────────────────────────────────────────────────

class TestRoutingPaths:
    def test_no_gpu_routes_to_cloud(self, client: TestClient) -> None:
        """
        In CI/non-GPU environment, telemetry_available=False.
        All requests must be routed to cloud (degrade-mode rule #1).
        """
        snap = client.app.state.telemetry_state.get_snapshot()
        if not snap.telemetry_available:
            data = client.post(
                "/v1/infer", json={"prompt": "What is the capital of France?"}
            ).json()
            assert data["routed_to"] == RoutingDecision.CLOUD_GEMINI.value

    def test_response_text_is_non_empty(self, client: TestClient) -> None:
        data = client.post("/v1/infer", json={"prompt": "hello"}).json()
        assert len(data["response_text"]) > 0

    def test_telemetry_available_field_reflects_state(
        self, client: TestClient
    ) -> None:
        actual_available = (
            client.app.state.telemetry_state.get_snapshot().telemetry_available
        )
        data = client.post("/v1/infer", json={"prompt": "hi"}).json()
        assert data["telemetry_available"] == actual_available


# ── Concurrency ───────────────────────────────────────────────────────────────

class TestConcurrentInfer:
    def test_concurrent_infer_all_succeed(self, client: TestClient) -> None:
        """20 concurrent /v1/infer requests must all return 200."""
        results: List[int] = []
        errors: List[Exception] = []

        def call() -> None:
            try:
                r = client.post("/v1/infer", json={"prompt": "concurrent test"})
                results.append(r.status_code)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=call) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Some requests raised: {errors}"
        assert all(code == 200 for code in results), (
            f"Non-200 responses: {results}"
        )

    def test_concurrent_requests_use_same_http_client(
        self, client: TestClient
    ) -> None:
        """Verify that concurrent requests don't create new client instances."""
        ids: List[int] = []

        def call() -> None:
            ids.append(id(client.app.state.http_client))
            client.post("/v1/infer", json={"prompt": "test"})

        threads = [threading.Thread(target=call) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(ids)) == 1, "Multiple http_client instances detected!"


# ── Sprint 1 regression ───────────────────────────────────────────────────────

class TestSprint1Regression:
    """Confirm Sprint 1 endpoints still work after Sprint 2 additions."""

    def test_healthz_still_returns_200(self, client: TestClient) -> None:
        assert client.get("/healthz").status_code == 200

    def test_telemetry_gpu_still_returns_200(self, client: TestClient) -> None:
        assert client.get("/telemetry/gpu").status_code == 200
