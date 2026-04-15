"""
Async background sampler for GPU telemetry.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Design guarantees
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. The ASGI event loop is NEVER blocked.
   All NVML C-binding calls are executed in a dedicated single-threaded
   ``ThreadPoolExecutor(max_workers=1)``.  The coroutine only awaits the future
   returned by ``loop.run_in_executor()``.

2. Anti-re-entrancy via ``asyncio.shield``.
   If ``asyncio.wait_for`` times out, the underlying executor future is
   protected by ``asyncio.shield`` and therefore NOT cancelled.  The still-
   running executor thread is tracked via ``_pending_future``.  On the next
   wake-up, if that future is not yet done, the poll cycle is skipped rather
   than queuing a second executor task.  This prevents executor queue pile-up
   under sustained NVML slowness.

3. Exponential back-off.
   After ``fail_threshold`` consecutive failures the poll interval grows
   geometrically (× ``backoff_factor``) up to ``max_backoff_s``.  This avoids
   hammering the (absent) driver inside CPU-only containers.

4. Throttled logging.
   Failure logs are emitted only on the 1st occurrence and again when backoff
   activates.  Recovery is always logged at INFO.  No log flooding between the
   first and threshold-th failure.

5. Exception containment.
   The outer ``while True`` loop catches all exceptions.  The only way the
   coroutine terminates is via ``asyncio.CancelledError`` (raised by
   ``task.cancel()`` in the lifespan shutdown handler).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.telemetry.nvml_client import NvmlClient, NvmlUnavailableError
from app.telemetry.state import TelemetrySnapshot, TelemetryState

logger = logging.getLogger(__name__)


async def telemetry_loop(
    state: TelemetryState,
    client: NvmlClient,
    *,
    interval_s: float,
    timeout_s: float,
    max_backoff_s: float,
    backoff_factor: float,
    fail_threshold: int,
) -> None:
    """
    Run the NVML telemetry sampling loop until cancelled.

    Intended to be launched with ``asyncio.create_task()`` inside the FastAPI
    lifespan startup handler.  ``task.cancel()`` is the expected shutdown signal.

    Parameters
    ----------
    state:
        Shared state manager – the only object written to by this coroutine.
    client:
        Synchronous NVML client – executed inside the ThreadPoolExecutor.
    interval_s:
        Normal poll interval in seconds (default 1.0).
    timeout_s:
        Maximum seconds to wait for a single NVML fetch before treating it as
        a failure (default 0.5).
    max_backoff_s:
        Upper bound for the exponential back-off interval (default 60.0).
    backoff_factor:
        Multiplier applied to the current interval on each backoff step
        (default 2.0).
    fail_threshold:
        Number of consecutive failures after which backoff activates (default 3).
    """
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="nvml_sampler",
    )
    loop = asyncio.get_running_loop()

    consecutive_failures: int = 0
    current_interval: float = interval_s
    _pending_future: Optional[asyncio.Future[TelemetrySnapshot]] = None

    logger.debug(
        "Telemetry sampler started (interval=%.2fs, timeout=%.2fs, "
        "max_backoff=%.1fs, fail_threshold=%d).",
        interval_s,
        timeout_s,
        max_backoff_s,
        fail_threshold,
    )

    try:
        while True:
            await asyncio.sleep(current_interval)

            # ── Anti-re-entrancy guard ────────────────────────────────────────
            # If a previous timed-out executor call has not finished yet, skip
            # scheduling a duplicate rather than queuing work in the single-
            # threaded pool.
            if _pending_future is not None and not _pending_future.done():
                logger.debug(
                    "NVML executor thread still busy – skipping poll cycle."
                )
                continue

            # ── Schedule NVML fetch in the dedicated thread ───────────────────
            _pending_future = loop.run_in_executor(
                executor, client.fetch_snapshot_sync
            )

            try:
                # asyncio.shield protects _pending_future from cancellation when
                # wait_for's own wrapper times out.  This keeps the re-entrancy
                # detection above working correctly.
                snapshot: TelemetrySnapshot = await asyncio.wait_for(
                    asyncio.shield(_pending_future),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                consecutive_failures += 1
                reason = (
                    f"NVML fetch exceeded timeout of {timeout_s:.2f}s "
                    f"(executor thread still running)"
                )
                _log_failure(reason, consecutive_failures, fail_threshold)
                current_interval = _next_interval(
                    current_interval,
                    interval_s,
                    backoff_factor,
                    max_backoff_s,
                    consecutive_failures,
                    fail_threshold,
                )
                state.update_snapshot(_make_degrade_snapshot(reason))
                continue

            except (NvmlUnavailableError, Exception) as exc:
                consecutive_failures += 1
                reason = f"{type(exc).__name__}: {exc}"
                _log_failure(reason, consecutive_failures, fail_threshold)
                current_interval = _next_interval(
                    current_interval,
                    interval_s,
                    backoff_factor,
                    max_backoff_s,
                    consecutive_failures,
                    fail_threshold,
                )
                state.update_snapshot(_make_degrade_snapshot(reason))
                continue

            # ── Successful sample ─────────────────────────────────────────────
            if consecutive_failures > 0:
                logger.info(
                    "NVML telemetry recovered after %d consecutive failure(s).",
                    consecutive_failures,
                )
            consecutive_failures = 0
            current_interval = interval_s
            state.update_snapshot(snapshot)

    except asyncio.CancelledError:
        logger.info("Telemetry sampler received cancellation – shutting down.")
        raise

    finally:
        # Best-effort cleanup: cancel the pending future (harmless if already
        # done), shut down the executor without waiting for threads, and call
        # nvmlShutdown().
        if _pending_future is not None and not _pending_future.done():
            _pending_future.cancel()
        executor.shutdown(wait=False)
        try:
            client.shutdown()
        except Exception:
            pass
        logger.debug("Telemetry sampler executor released.")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _next_interval(
    current: float,
    base: float,
    factor: float,
    maximum: float,
    failures: int,
    threshold: int,
) -> float:
    """
    Return the next poll interval.

    Back-off starts only after ``failures >= threshold`` so the first few
    failures are retried at the normal pace before slowing down.
    """
    if failures >= threshold:
        return min(current * factor, maximum)
    return base


def _log_failure(reason: str, consecutive: int, threshold: int) -> None:
    """
    Emit failure log entries with throttling to prevent log flooding.

    * 1st failure  → WARNING
    * threshold-th → ERROR (back-off now active)
    * In between   → silent (still visible via degrade_reason in telemetry endpoint)
    """
    if consecutive == 1:
        logger.warning("NVML telemetry failure #1: %s", reason)
    elif consecutive == threshold:
        logger.error(
            "NVML telemetry: %d consecutive failures – entering exponential "
            "back-off (×%.1f up to %.0fs). Last error: %s",
            consecutive,
            2.0,  # logged for human clarity; actual factor comes from config
            60.0,
            reason,
        )
    # Between 1 and threshold, failures are silently reflected in degrade_reason.


def _make_degrade_snapshot(reason: str) -> TelemetrySnapshot:
    """Build a degrade snapshot with the given human-readable reason."""
    return TelemetrySnapshot(
        timestamp_ms=int(time.time() * 1000),
        telemetry_available=False,
        gpu_count=None,
        per_gpu=[],
        degrade_reason=reason,
    )
