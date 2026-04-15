"""
Unit tests for CircuitBreaker state machine.

All tests use ``asyncio_mode = auto`` (configured in pytest.ini).

Test matrix
───────────
1.  Initial state is CLOSED
2.  Non-qualifying failures (4xx) do NOT increment the counter
3.  Qualifying failures (5xx, timeout) increment the counter
4.  CLOSED → OPEN after failure_threshold consecutive qualifying failures
5.  OPEN fast-fails immediately with CircuitBreakerOpenError
6.  OPEN → HALF-OPEN after cooldown_s has elapsed
7.  HALF-OPEN + success → CLOSED (counter reset)
8.  HALF-OPEN + qualifying failure → OPEN (timer reset)
9.  HALF-OPEN + non-qualifying failure → CLOSED (backend is responding)
10. Concurrent requests in HALF-OPEN: second request is fast-failed
11. Success in CLOSED state resets the failure counter
12. remaining_cooldown_s() returns correct values
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerBackend,
    CircuitBreakerOpenError,
    CircuitState,
)
from app.routing.strategies import CloudInferenceError, CloudInferenceTimeoutError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fast_breaker(threshold: int = 3, cooldown_s: float = 0.05) -> CircuitBreaker:
    """Circuit breaker with fast settings for test speed."""
    return CircuitBreaker(failure_threshold=threshold, cooldown_s=cooldown_s)


async def _ok_coro() -> str:
    return "ok"


async def _fail_coro(exc: Exception) -> str:
    raise exc


async def _trigger_failures(
    breaker: CircuitBreaker, count: int, exc: Exception | None = None
) -> None:
    """Trigger ``count`` qualifying failures on the breaker."""
    error = exc or CloudInferenceError("5xx", status_code=503)
    for _ in range(count):
        with pytest.raises(type(error)):
            await breaker.call(_fail_coro(error))


# ── State: CLOSED ─────────────────────────────────────────────────────────────

class TestClosedState:
    async def test_initial_state_is_closed(self) -> None:
        breaker = _fast_breaker()
        assert breaker.state == CircuitState.CLOSED

    async def test_initial_consecutive_failures_is_zero(self) -> None:
        breaker = _fast_breaker()
        assert breaker.consecutive_failures == 0

    async def test_successful_call_passes_through(self) -> None:
        breaker = _fast_breaker()
        result = await breaker.call(_ok_coro())
        assert result == "ok"

    async def test_non_qualifying_4xx_does_not_increment_counter(self) -> None:
        breaker = _fast_breaker(threshold=3)
        exc = CloudInferenceError("Bad request", status_code=400)
        for _ in range(5):  # more than threshold
            with pytest.raises(CloudInferenceError):
                await breaker.call(_fail_coro(exc))
        assert breaker.state == CircuitState.CLOSED
        assert breaker.consecutive_failures == 0

    async def test_qualifying_5xx_increments_counter(self) -> None:
        breaker = _fast_breaker(threshold=3)
        exc = CloudInferenceError("Server error", status_code=503)
        with pytest.raises(CloudInferenceError):
            await breaker.call(_fail_coro(exc))
        assert breaker.consecutive_failures == 1
        assert breaker.state == CircuitState.CLOSED

    async def test_timeout_error_is_qualifying(self) -> None:
        breaker = _fast_breaker(threshold=3)
        with pytest.raises(CloudInferenceTimeoutError):
            await breaker.call(_fail_coro(CloudInferenceTimeoutError()))
        assert breaker.consecutive_failures == 1

    async def test_success_resets_counter_in_closed(self) -> None:
        breaker = _fast_breaker(threshold=3)
        exc = CloudInferenceError("err", status_code=500)
        with pytest.raises(CloudInferenceError):
            await breaker.call(_fail_coro(exc))
        assert breaker.consecutive_failures == 1
        # A successful call resets
        await breaker.call(_ok_coro())
        assert breaker.consecutive_failures == 0


# ── Transition: CLOSED → OPEN ─────────────────────────────────────────────────

class TestClosedToOpenTransition:
    async def test_opens_after_threshold_failures(self) -> None:
        breaker = _fast_breaker(threshold=3)
        await _trigger_failures(breaker, 3)
        assert breaker.state == CircuitState.OPEN

    async def test_does_not_open_before_threshold(self) -> None:
        breaker = _fast_breaker(threshold=3)
        await _trigger_failures(breaker, 2)
        assert breaker.state == CircuitState.CLOSED

    async def test_consecutive_required(self) -> None:
        """A success between failures resets the counter."""
        breaker = _fast_breaker(threshold=3)
        exc = CloudInferenceError("5xx", status_code=503)
        with pytest.raises(CloudInferenceError):
            await breaker.call(_fail_coro(exc))
        await breaker.call(_ok_coro())  # resets counter
        with pytest.raises(CloudInferenceError):
            await breaker.call(_fail_coro(exc))
        assert breaker.consecutive_failures == 1  # not 2
        assert breaker.state == CircuitState.CLOSED


# ── State: OPEN ───────────────────────────────────────────────────────────────

class TestOpenState:
    async def test_open_fast_fails_immediately(self) -> None:
        breaker = _fast_breaker(threshold=1, cooldown_s=10.0)
        await _trigger_failures(breaker, 1)
        assert breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(_ok_coro())

    async def test_open_error_contains_retry_hint(self) -> None:
        breaker = _fast_breaker(threshold=1, cooldown_s=10.0)
        await _trigger_failures(breaker, 1)
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await breaker.call(_ok_coro())
        assert exc_info.value.retry_after_s > 0

    async def test_remaining_cooldown_positive_when_open(self) -> None:
        breaker = _fast_breaker(threshold=1, cooldown_s=10.0)
        await _trigger_failures(breaker, 1)
        assert breaker.remaining_cooldown_s() > 0

    async def test_remaining_cooldown_zero_when_closed(self) -> None:
        breaker = _fast_breaker()
        assert breaker.remaining_cooldown_s() == 0.0


# ── Transition: OPEN → HALF-OPEN ──────────────────────────────────────────────

class TestOpenToHalfOpenTransition:
    async def test_half_open_after_cooldown(self) -> None:
        breaker = _fast_breaker(threshold=1, cooldown_s=0.03)
        await _trigger_failures(breaker, 1)
        assert breaker.state == CircuitState.OPEN
        await asyncio.sleep(0.05)  # exceed cooldown
        # Next call should probe in HALF-OPEN
        result = await breaker.call(_ok_coro())
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    async def test_still_open_before_cooldown_expires(self) -> None:
        breaker = _fast_breaker(threshold=1, cooldown_s=10.0)
        await _trigger_failures(breaker, 1)
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(_ok_coro())
        assert breaker.state == CircuitState.OPEN


# ── State: HALF-OPEN ──────────────────────────────────────────────────────────

class TestHalfOpenState:
    async def _get_half_open_breaker(self) -> CircuitBreaker:
        breaker = _fast_breaker(threshold=1, cooldown_s=0.03)
        await _trigger_failures(breaker, 1)
        await asyncio.sleep(0.05)
        return breaker

    async def test_half_open_success_closes_circuit(self) -> None:
        breaker = await self._get_half_open_breaker()
        await breaker.call(_ok_coro())
        assert breaker.state == CircuitState.CLOSED
        assert breaker.consecutive_failures == 0

    async def test_half_open_qualifying_failure_reopens(self) -> None:
        breaker = await self._get_half_open_breaker()
        exc = CloudInferenceError("5xx", status_code=500)
        with pytest.raises(CloudInferenceError):
            await breaker.call(_fail_coro(exc))
        assert breaker.state == CircuitState.OPEN

    async def test_half_open_non_qualifying_failure_closes(self) -> None:
        """A 4xx probe response means backend is alive → close the circuit."""
        breaker = await self._get_half_open_breaker()
        exc = CloudInferenceError("Bad Request", status_code=400)
        with pytest.raises(CloudInferenceError):
            await breaker.call(_fail_coro(exc))
        assert breaker.state == CircuitState.CLOSED

    async def test_half_open_concurrent_second_request_fast_fails(self) -> None:
        """
        While a probe is in-flight, a second concurrent request must be
        fast-failed rather than queued as another probe.
        """
        breaker = _fast_breaker(threshold=1, cooldown_s=0.02)
        await _trigger_failures(breaker, 1)
        await asyncio.sleep(0.04)  # enter HALF-OPEN on next call

        slow_probe_started = asyncio.Event()

        async def slow_probe() -> str:
            slow_probe_started.set()
            await asyncio.sleep(0.5)  # holds probe slot open
            return "probe_result"

        # Schedule probe and a concurrent second request
        probe_task = asyncio.create_task(breaker.call(slow_probe()))
        # Wait until probe has started (probe_in_flight = True)
        await slow_probe_started.wait()

        # Second request should be fast-failed while probe is in-flight
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(_ok_coro())

        probe_task.cancel()
        try:
            await probe_task
        except (asyncio.CancelledError, Exception):
            pass


# ── CircuitBreakerBackend ─────────────────────────────────────────────────────

class TestCircuitBreakerBackend:
    async def test_delegates_to_wrapped_backend(self) -> None:
        mock_backend = AsyncMock()
        mock_backend.infer.return_value = "response"
        breaker = _fast_breaker()
        wrapped = CircuitBreakerBackend(backend=mock_backend, breaker=breaker)
        result = await wrapped.infer(prompt="hello", request_id="req-1")
        assert result == "response"
        mock_backend.infer.assert_called_once_with(prompt="hello", request_id="req-1")

    async def test_circuit_open_error_propagates(self) -> None:
        mock_backend = AsyncMock()
        mock_backend.infer.side_effect = CloudInferenceError("5xx", status_code=503)
        breaker = _fast_breaker(threshold=1)
        wrapped = CircuitBreakerBackend(backend=mock_backend, breaker=breaker)

        with pytest.raises(CloudInferenceError):
            await wrapped.infer(prompt="hello", request_id="req-1")

        # Circuit is now OPEN
        with pytest.raises(CircuitBreakerOpenError):
            await wrapped.infer(prompt="hello", request_id="req-2")
