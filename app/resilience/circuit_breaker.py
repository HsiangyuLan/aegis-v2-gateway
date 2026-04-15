"""
Circuit Breaker — pure asyncio implementation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
State machine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CLOSED ──(N consecutive qualifying failures)──► OPEN
    ▲                                               │
    │  (probe succeeds)            (cooldown_s elapses)
    │                                               ▼
    └──────────────────────────── HALF-OPEN ◄───────┘
                                      │
                          (probe fails with qualifying error)
                                      │
                                      ▼
                                    OPEN (timer reset)

Qualifying failures
───────────────────
Only failures that signal backend degradation open the circuit:
  * ``CloudInferenceTimeoutError``  — connect or read timeout
  * ``CloudInferenceError`` with ``status_code >= 500``  — 5xx server error

4xx client errors (bad request, auth failure) are NOT qualifying: they prove
the backend is alive and responding, so the circuit stays CLOSED.

HALF-OPEN behaviour
───────────────────
Exactly ONE probe request is allowed through at a time.  Concurrent requests
arriving while a probe is in-flight are fast-failed (treated as OPEN) to
prevent a cascade of probes hitting a still-recovering backend.

asyncio.Lock usage
──────────────────
All state reads that may trigger a transition (OPEN → HALF-OPEN after
cooldown) and all state writes are performed under a single ``asyncio.Lock``.
The lock is held only for the brief evaluation / mutation; the inner awaitable
(the actual HTTP call) runs outside the lock so it does not block other
coroutines from checking state.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Awaitable, Callable, TypeVar

from app.routing.strategies import CloudInferenceError, CloudInferenceTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── State enum ────────────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ── Exceptions ────────────────────────────────────────────────────────────────

class CircuitBreakerOpenError(RuntimeError):
    """
    Raised when a request arrives while the circuit is OPEN (or while a
    HALF-OPEN probe is already in-flight).

    The ``retry_after_s`` attribute gives the caller a hint about when to
    retry.  ``EntropyRouter._execute()`` maps this to HTTP 503.
    """

    def __init__(self, message: str, retry_after_s: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


# ── Qualifying failure predicate ──────────────────────────────────────────────

def _is_qualifying_failure(exc: Exception) -> bool:
    """
    Return True only for failures that indicate genuine backend degradation.

    * Timeouts (connect or read) → backend is slow / overloaded
    * HTTP 5xx → backend returned a server-side error

    HTTP 4xx errors are explicitly excluded: a 400 or 401 means the backend
    is alive and responding; opening the circuit would be counterproductive.
    """
    if isinstance(exc, CloudInferenceTimeoutError):
        return True
    if isinstance(exc, CloudInferenceError) and exc.status_code is not None:
        return exc.status_code >= 500
    return False


# ── Core circuit breaker ──────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Asyncio-native circuit breaker.

    Usage::

        breaker = CircuitBreaker(failure_threshold=3, cooldown_s=30.0)
        result = await breaker.call(some_coroutine())

    The same instance must be shared across all callers that talk to the same
    downstream backend.  In Aegis V2, one ``CircuitBreaker`` wraps the
    ``CloudGeminiBackend`` and is stored on ``app.state.circuit_breaker``.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_s: float = 30.0,
        is_qualifying_failure: Callable[[Exception], bool] | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._is_qualifying = is_qualifying_failure or _is_qualifying_failure

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._opened_at: float = 0.0
        self._probe_in_flight: bool = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current circuit state (read-only snapshot; may be stale)."""
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def remaining_cooldown_s(self) -> float:
        """Seconds until the circuit enters HALF-OPEN.  0.0 when already past."""
        if self._state != CircuitState.OPEN:
            return 0.0
        return max(0.0, self._cooldown_s - (time.monotonic() - self._opened_at))

    async def call(self, coro: Awaitable[T]) -> T:
        """
        Execute ``coro`` if the circuit permits; fast-fail otherwise.

        Raises:
            CircuitBreakerOpenError: when OPEN or when HALF-OPEN probe slot
                is already occupied by another in-flight request.
            Any exception raised by ``coro``: re-raised transparently after
                recording the failure if it is a qualifying error.
        """
        # ── Check state under lock (may transition OPEN → HALF-OPEN) ──────────
        async with self._lock:
            effective_state = self._evaluate_and_maybe_transition()

        if effective_state == CircuitState.OPEN:
            # Close the coroutine so the event loop does not emit
            # "RuntimeWarning: coroutine was never awaited".
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]
            retry = self.remaining_cooldown_s()
            raise CircuitBreakerOpenError(
                f"Circuit breaker OPEN – Gemini API is unavailable. "
                f"Retry in {retry:.1f}s.",
                retry_after_s=retry,
            )

        # ── CLOSED or HALF-OPEN probe: execute the coroutine ──────────────────
        try:
            result = await coro
        except Exception as exc:
            async with self._lock:
                self._on_failure(effective_state, exc)
            raise

        async with self._lock:
            self._on_success(effective_state)
        return result

    # ------------------------------------------------------------------
    # State evaluation and mutation (all called under self._lock)
    # ------------------------------------------------------------------

    def _evaluate_and_maybe_transition(self) -> CircuitState:
        """
        Evaluate the current state, applying OPEN → HALF-OPEN transition if the
        cooldown has elapsed.  Returns the effective state for this request.
        """
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self._cooldown_s:
                # Cooldown elapsed: enter HALF-OPEN and claim the probe slot
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                logger.info(
                    "Circuit breaker: cooldown elapsed → HALF-OPEN "
                    "(probe request allowed)."
                )
                return CircuitState.HALF_OPEN
            # Still cooling down
            return CircuitState.OPEN

        if self._state == CircuitState.HALF_OPEN:
            if self._probe_in_flight:
                # Concurrent request arrived while probe is in-flight: treat as OPEN
                return CircuitState.OPEN
            # This request becomes the probe
            self._probe_in_flight = True
            return CircuitState.HALF_OPEN

        # CLOSED: normal operation
        return CircuitState.CLOSED

    def _on_success(self, from_state: CircuitState) -> None:
        """Record a successful call.  Resets failure counter; closes if half-open."""
        if from_state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._probe_in_flight = False
            self._consecutive_failures = 0
            logger.info(
                "Circuit breaker: HALF-OPEN probe succeeded → CLOSED."
            )
        elif from_state == CircuitState.CLOSED:
            self._consecutive_failures = 0

    def _on_failure(self, from_state: CircuitState, exc: Exception) -> None:
        """
        Record a failed call.

        HALF-OPEN failures always re-open the circuit (qualifying or not),
        because a failed probe means we cannot confirm backend recovery.

        CLOSED failures only count when they are qualifying (5xx or timeout).
        """
        if from_state == CircuitState.HALF_OPEN:
            self._probe_in_flight = False
            if self._is_qualifying(exc):
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "Circuit breaker: HALF-OPEN probe failed (%s) → OPEN "
                    "(cooldown reset).",
                    type(exc).__name__,
                )
            else:
                # Non-qualifying failure (e.g. 4xx): backend is responding
                # → close the circuit anyway.
                self._state = CircuitState.CLOSED
                self._consecutive_failures = 0
                logger.info(
                    "Circuit breaker: HALF-OPEN probe returned non-qualifying "
                    "error (%s) → CLOSED (backend is responding).",
                    type(exc).__name__,
                )
            return

        if from_state == CircuitState.CLOSED and self._is_qualifying(exc):
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.error(
                    "Circuit breaker: %d consecutive qualifying failures → OPEN "
                    "(cooldown=%.0fs). Last error: %s: %s",
                    self._consecutive_failures,
                    self._cooldown_s,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.warning(
                    "Circuit breaker: qualifying failure %d/%d (%s).",
                    self._consecutive_failures,
                    self._failure_threshold,
                    type(exc).__name__,
                )


# ── Decorator backend ─────────────────────────────────────────────────────────

class CircuitBreakerBackend:
    """
    Wraps any ``InferenceBackend`` with a ``CircuitBreaker``.

    Placing the circuit breaker here (as a wrapper) rather than inside
    ``CloudGeminiBackend`` keeps the two concerns separate and makes
    the breaker independently testable.
    """

    def __init__(self, backend, breaker: CircuitBreaker) -> None:
        self._backend = backend
        self._breaker = breaker

    async def infer(self, prompt: str, request_id: str) -> str:
        """
        Delegate to the wrapped backend; the circuit breaker intercepts failures
        and may fast-fail with ``CircuitBreakerOpenError``.
        """
        return await self._breaker.call(
            self._backend.infer(prompt=prompt, request_id=request_id)
        )
