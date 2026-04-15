"""
Tests for LocalEdgeBackend and CloudGeminiBackend.

CloudGeminiBackend tests use mock mode (empty API key) to avoid any real
network calls.  Timeout and error paths are tested by injecting a mock
httpx.AsyncClient that raises on demand.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.routing.strategies import (
    CloudGeminiBackend,
    CloudInferenceError,
    CloudInferenceTimeoutError,
    InferenceBackend,
    LocalEdgeBackend,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings(**overrides) -> Settings:
    base = dict(
        telemetry_poll_interval_s=1.0,
        telemetry_nvml_timeout_s=0.5,
        telemetry_max_backoff_s=60.0,
        telemetry_backoff_factor=2.0,
        telemetry_fail_threshold=3,
        entropy_threshold=0.4,
        vram_threshold=0.85,
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
    base.update(overrides)
    return Settings(**base)


# ── Protocol conformance ──────────────────────────────────────────────────────

class TestProtocolConformance:
    def test_local_edge_satisfies_protocol(self) -> None:
        backend = LocalEdgeBackend(settings=_settings())
        assert isinstance(backend, InferenceBackend)

    def test_cloud_gemini_satisfies_protocol(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        backend = CloudGeminiBackend(client=mock_client, settings=_settings())
        assert isinstance(backend, InferenceBackend)


# ── LocalEdgeBackend ──────────────────────────────────────────────────────────

class TestLocalEdgeBackend:
    async def test_returns_string(self) -> None:
        backend = LocalEdgeBackend(settings=_settings(local_edge_mock_delay_s=0.0))
        result = await backend.infer(prompt="hello", request_id="req-1")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_response_contains_local_edge_marker(self) -> None:
        backend = LocalEdgeBackend(settings=_settings(local_edge_mock_delay_s=0.0))
        result = await backend.infer(prompt="test prompt", request_id="req-1")
        assert "[LOCAL_EDGE]" in result

    async def test_prompt_preview_in_response(self) -> None:
        backend = LocalEdgeBackend(settings=_settings(local_edge_mock_delay_s=0.0))
        result = await backend.infer(prompt="hello world", request_id="req-1")
        assert "hello world" in result

    async def test_zero_delay_completes_quickly(self) -> None:
        import time
        backend = LocalEdgeBackend(settings=_settings(local_edge_mock_delay_s=0.0))
        t0 = time.monotonic()
        await backend.infer(prompt="test", request_id="req-1")
        assert (time.monotonic() - t0) < 0.5


# ── CloudGeminiBackend ────────────────────────────────────────────────────────

class TestCloudGeminiBackendMockMode:
    """Tests for mock mode (empty API key — no real HTTP requests)."""

    def _backend(self) -> CloudGeminiBackend:
        return CloudGeminiBackend(
            client=MagicMock(spec=httpx.AsyncClient),
            settings=_settings(cloud_gemini_api_key=""),
        )

    async def test_mock_mode_does_not_call_http_client(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock()
        backend = CloudGeminiBackend(
            client=mock_client,
            settings=_settings(cloud_gemini_api_key=""),
        )
        await backend.infer(prompt="hello", request_id="req-1")
        mock_client.post.assert_not_called()

    async def test_mock_returns_string(self) -> None:
        result = await self._backend().infer(prompt="test", request_id="req-1")
        assert isinstance(result, str)

    async def test_mock_response_contains_cloud_marker(self) -> None:
        result = await self._backend().infer(prompt="test", request_id="req-1")
        assert "[CLOUD_GEMINI_MOCK]" in result

    async def test_mock_mode_activated_when_api_key_empty(self) -> None:
        backend = CloudGeminiBackend(
            client=MagicMock(spec=httpx.AsyncClient),
            settings=_settings(cloud_gemini_api_key=""),
        )
        assert backend._mock_mode is True

    async def test_real_mode_activated_when_api_key_set(self) -> None:
        backend = CloudGeminiBackend(
            client=MagicMock(spec=httpx.AsyncClient),
            settings=_settings(cloud_gemini_api_key="my-key"),
        )
        assert backend._mock_mode is False


class TestCloudGeminiBackendErrorHandling:
    """Test that httpx exceptions are mapped to domain exceptions."""

    def _real_backend(
        self, mock_client: MagicMock
    ) -> CloudGeminiBackend:
        return CloudGeminiBackend(
            client=mock_client,
            settings=_settings(cloud_gemini_api_key="test-key"),
        )

    async def test_timeout_raises_cloud_inference_timeout_error(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ReadTimeout("timed out", request=MagicMock())
        )
        backend = self._real_backend(mock_client)
        with pytest.raises(CloudInferenceTimeoutError):
            await backend.infer(prompt="hello", request_id="req-1")

    async def test_connect_timeout_raises_cloud_inference_timeout_error(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectTimeout("connect timed out", request=MagicMock())
        )
        backend = self._real_backend(mock_client)
        with pytest.raises(CloudInferenceTimeoutError):
            await backend.infer(prompt="hello", request_id="req-1")

    async def test_http_5xx_raises_cloud_inference_error(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "503", request=MagicMock(), response=mock_response
            )
        )
        backend = self._real_backend(mock_client)
        with pytest.raises(CloudInferenceError) as exc_info:
            await backend.infer(prompt="hello", request_id="req-1")
        assert exc_info.value.status_code == 503

    async def test_connection_error_raises_cloud_inference_error(self) -> None:
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused", request=MagicMock())
        )
        backend = self._real_backend(mock_client)
        with pytest.raises(CloudInferenceError):
            await backend.infer(prompt="hello", request_id="req-1")
