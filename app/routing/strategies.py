"""
Inference backend strategies.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy Design Pattern implementation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

``InferenceBackend`` is a ``typing.Protocol`` (structural subtyping) rather
than an ABC.  This means:

  * Sprint 3 can replace ``LocalEdgeBackend`` with a real vLLM client without
    any inheritance changes — it just needs to implement the same interface.
  * Test doubles only need to implement the protocol methods; no ``super()``
    calls required.

httpx.AsyncClient lifecycle contract
─────────────────────────────────────
``CloudGeminiBackend`` accepts the ``httpx.AsyncClient`` as a constructor
argument and NEVER creates its own.  The single shared client instance lives
on ``app.state.http_client`` (created in lifespan startup, closed in lifespan
shutdown).  This is the only correct pattern:

  CORRECT:  CloudGeminiBackend(client=app.state.http_client, ...)
  WRONG:    async with httpx.AsyncClient() as c: ...  # inside a request handler

Creating a new AsyncClient per-request would:
  1. Open a new TCP connection for every request (no pool reuse).
  2. Leave sockets in CLOSE_WAIT until the OS reclaims them.
  3. Exhaust the OS file-descriptor limit under moderate concurrency.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

import httpx

from app.core.config import Settings

if TYPE_CHECKING:
    # Imported only for type annotations; avoids circular import at runtime.
    from app.routing.worker_registry import WorkerInfo

logger = logging.getLogger(__name__)


# ── Custom exceptions ─────────────────────────────────────────────────────────

class CloudInferenceError(RuntimeError):
    """Raised when the cloud backend returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CloudInferenceTimeoutError(CloudInferenceError):
    """Raised when the cloud backend exceeds the configured timeout."""

    def __init__(self) -> None:
        super().__init__(
            "Cloud inference request timed out (connect or read timeout exceeded)."
        )


# ── Protocol (Strategy interface) ────────────────────────────────────────────

@runtime_checkable
class InferenceBackend(Protocol):
    """
    Structural interface for inference backends.

    Any object that implements ``async def infer(...)`` satisfies this protocol
    without needing to inherit from it.
    """

    async def infer(self, prompt: str, request_id: str) -> str:
        """
        Run inference and return the model response text.

        Args:
            prompt:     The user's input text.
            request_id: Unique identifier for distributed tracing.

        Returns:
            Response text string from the model.

        Raises:
            CloudInferenceTimeoutError: on connect/read timeout (cloud only).
            CloudInferenceError:        on HTTP 4xx/5xx or connection failure.
        """
        ...


# ── Local edge strategy ───────────────────────────────────────────────────────

class LocalEdgeBackend:
    """
    Mock local-edge inference backend.

    Simulates routing to a quantized model (Llama.cpp / vLLM) hosted on the
    same node.  In Sprint 2 this is a ``asyncio.sleep`` placeholder.

    Sprint 3+: Replace the sleep with a real HTTP call to the local vLLM
    OpenAI-compatible endpoint (``POST http://localhost:8000/v1/chat/completions``).
    That call will need its own httpx.AsyncClient with a localhost-scoped
    connection pool.

    Phase 2 addition
    ────────────────
    The optional ``worker`` parameter enables KV cache-aware routing.  When a
    ``WorkerInfo`` is supplied, the backend targets ``worker.endpoint`` instead
    of the default node-local endpoint.  This is the hook that lets
    ``KVAwareRouter`` direct requests to the specific disaggregated worker with
    the highest prefix cache hit probability.

    When ``worker=None`` (default), behaviour is identical to Sprint 3 — the
    mock delay simulates the single-node local path.
    """

    def __init__(self, settings: Settings) -> None:
        self._delay = settings.local_edge_mock_delay_s

    async def infer(
        self,
        prompt: str,
        request_id: str,
        worker: "Optional[WorkerInfo]" = None,
    ) -> str:
        """
        Run inference against the local edge node (or a specific worker).

        Args:
            prompt:      User prompt string.
            request_id:  Unique request identifier for distributed tracing.
            worker:      Phase 2 — the specific disaggregated worker selected
                         by KVAwareRouter.  When supplied, ``worker.endpoint``
                         is the routing target.  When ``None``, the default
                         node-local endpoint is used.

        Returns:
            Response text string from the model.
        """
        await asyncio.sleep(self._delay)
        preview = prompt[:60].replace("\n", " ")
        if worker is not None:
            return (
                f"[LOCAL_EDGE/{worker.worker_id}] "
                f"Mock response for: {preview!r} "
                f"(endpoint={worker.endpoint})"
            )
        return f"[LOCAL_EDGE] Mock response for: {preview!r}"


# ── Cloud Gemini strategy ─────────────────────────────────────────────────────

class CloudGeminiBackend:
    """
    Cloud inference backend using the Gemini generative language API.

    ── Dependency injection ────────────────────────────────────────────────────
    The ``httpx.AsyncClient`` is injected at construction time, NOT created
    here.  The single process-wide client is built in ``app/main.py``'s
    lifespan handler and stored on ``app.state.http_client``.

    ── Mock mode ───────────────────────────────────────────────────────────────
    When ``settings.cloud_gemini_api_key == ""``, the backend enters mock mode:
    no real HTTP request is made; a fake response is returned after a short
    delay.  This keeps CI pipelines and local development working without a
    real API key.

    ── Error handling ──────────────────────────────────────────────────────────
    All httpx exceptions are caught and re-raised as domain-specific errors so
    that the route handler can map them to appropriate HTTP status codes without
    leaking transport-layer details to callers.
    """

    _GENERATE_PATH = "/v1beta/models/gemini-pro:generateContent"
    _MOCK_DELAY_S = 0.10

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._mock_mode = not bool(settings.cloud_gemini_api_key)
        if self._mock_mode:
            logger.info(
                "CloudGeminiBackend: AEGIS_CLOUD_GEMINI_API_KEY is not set – "
                "running in mock mode (no real HTTP requests will be made)."
            )

    async def infer(self, prompt: str, request_id: str) -> str:
        if self._mock_mode:
            return await self._mock_infer(prompt)
        return await self._real_infer(prompt, request_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _mock_infer(self, prompt: str) -> str:
        await asyncio.sleep(self._MOCK_DELAY_S)
        preview = prompt[:60].replace("\n", " ")
        return f"[CLOUD_GEMINI_MOCK] Mock response for: {preview!r}"

    async def _real_infer(self, prompt: str, request_id: str) -> str:
        url = self._settings.cloud_gemini_base_url.rstrip("/") + self._GENERATE_PATH
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        headers = {
            "X-Goog-Api-Key": self._settings.cloud_gemini_api_key,
            "X-Request-Id": request_id,
        }

        try:
            response = await self._client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise CloudInferenceTimeoutError() from exc
        except httpx.HTTPStatusError as exc:
            raise CloudInferenceError(
                f"Gemini API returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise CloudInferenceError(
                f"Network error communicating with Gemini API: {exc}"
            ) from exc

        try:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise CloudInferenceError(
                f"Unexpected Gemini API response shape: {response.text[:200]}"
            ) from exc
