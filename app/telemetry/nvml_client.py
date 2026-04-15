"""
Synchronous NVML client.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL CONTRACT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All public methods of ``NvmlClient`` MUST be invoked exclusively from a
``ThreadPoolExecutor`` with ``max_workers=1``.  Never call them:

  * Directly from an ``async`` coroutine (they are blocking C-bindings).
  * From multiple threads simultaneously (some NVML calls are not re-entrant).

The ``telemetry_loop`` coroutine in ``sampler.py`` enforces this contract.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Failure-mode taxonomy
─────────────────────
1. ``nvidia-ml-py3`` package not installed
   → ``import pynvml`` raises ``ImportError`` at module load time.
   → ``PYNVML_AVAILABLE = False``; ``fetch_snapshot_sync()`` immediately raises
     ``NvmlUnavailableError`` without attempting any C-binding call.

2. Package installed but driver / library missing at runtime
   → ``nvmlInit()`` raises ``NVMLError_LibraryNotFound``,
     ``NVMLError_DriverNotLoaded``, ``NVMLError_NoPermission``, or ``OSError``.
   → ``_do_init()`` converts these into ``NvmlUnavailableError`` and leaves
     ``_initialized=False`` so the next poll cycle retries.

3. Device count == 0 (container with no GPU device mounts)
   → Returns a degrade ``TelemetrySnapshot`` with ``telemetry_available=False``
     and ``gpu_count=0``; does NOT raise.

4. Per-device call failure (driver reset, device hot-unplug, etc.)
   → ``_fetch_single_gpu()`` catches ``NVMLError`` per field; unreadable fields
     are ``None`` in the snapshot rather than aborting the entire collection.

5. ``nvmlDeviceGetCount()`` raises after successful ``nvmlInit()``
   → ``_collect()`` calls ``_reset()`` (which invokes ``nvmlShutdown()`` and
     clears ``_initialized``) then re-raises, triggering backoff + re-init on
     the next sampler cycle.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from app.telemetry.state import GpuSnapshot, TelemetrySnapshot

logger = logging.getLogger(__name__)

# ── Library availability check ────────────────────────────────────────────────
# Initialise sentinel values before the try-block so they are always defined.
_PYNVML_IMPORT_ERROR: str = ""
_pynvml = None  # will be replaced with the real module on success
_NVMLError: type[BaseException] = Exception  # overridden below; safe fallback

try:
    import pynvml as _pynvml  # type: ignore[no-redef]

    PYNVML_AVAILABLE: bool = True
    _NVMLError = _pynvml.NVMLError  # type: ignore[assignment]
except (ImportError, OSError) as _exc:
    PYNVML_AVAILABLE = False
    _PYNVML_IMPORT_ERROR = str(_exc)
    # _pynvml remains None; _NVMLError remains Exception (never actually matched
    # because we bail out before reaching any pynvml.* call site).


# ── Public exception ──────────────────────────────────────────────────────────

class NvmlUnavailableError(RuntimeError):
    """Raised when NVML is structurally unavailable (missing library, no driver,
    no permission).  Transient per-device errors are NOT wrapped in this class."""


# ── Client ────────────────────────────────────────────────────────────────────

class NvmlClient:
    """
    Thin synchronous wrapper around pynvml.

    Lifecycle
    ─────────
    * Construction is cheap and never touches NVML.
    * ``nvmlInit()`` is called lazily on the first ``fetch_snapshot_sync()``
      invocation.  This keeps lifespan startup latency at zero and lets the
      sampler's backoff mechanism handle init failures transparently.
    * ``shutdown()`` releases NVML resources; called from the sampler's
      ``finally`` block during graceful shutdown.
    """

    def __init__(self) -> None:
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_snapshot_sync(self) -> TelemetrySnapshot:
        """
        Collect a full GPU telemetry snapshot synchronously.

        Must only be called from inside a ``ThreadPoolExecutor``.

        Returns:
            ``TelemetrySnapshot`` with ``telemetry_available=True`` when at
            least one GPU is present and readable; with ``telemetry_available=
            False`` and ``gpu_count=0`` when no devices exist.

        Raises:
            ``NvmlUnavailableError``: package missing, or ``nvmlInit()`` failed.
            ``pynvml.NVMLError``: mid-session driver fault (``_reset()`` is
                called first so the next poll will attempt re-init).
        """
        if not PYNVML_AVAILABLE:
            raise NvmlUnavailableError(
                f"nvidia-ml-py3 package not installed: {_PYNVML_IMPORT_ERROR}"
            )

        if not self._initialized:
            self._do_init()  # raises NvmlUnavailableError on failure

        return self._collect()

    def shutdown(self) -> None:
        """Release NVML resources.  Safe to call multiple times."""
        if self._initialized and _pynvml is not None:
            try:
                _pynvml.nvmlShutdown()
            except Exception:
                pass
            self._initialized = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _do_init(self) -> None:
        """
        Attempt ``nvmlInit()``.  Converts all known failure modes into
        ``NvmlUnavailableError`` so the sampler can handle them uniformly.
        """
        try:
            _pynvml.nvmlInit()  # type: ignore[union-attr]
            self._initialized = True
            logger.info("pynvml nvmlInit() succeeded.")
        except _NVMLError as exc:
            raise NvmlUnavailableError(
                f"nvmlInit() failed – NVML error: {exc}"
            ) from exc
        except OSError as exc:
            raise NvmlUnavailableError(
                f"nvmlInit() failed – OS error (driver / library missing?): {exc}"
            ) from exc

    def _reset(self) -> None:
        """
        Shutdown NVML and clear ``_initialized`` so the next
        ``fetch_snapshot_sync()`` call will attempt a fresh ``nvmlInit()``.
        """
        if self._initialized and _pynvml is not None:
            try:
                _pynvml.nvmlShutdown()
            except Exception:
                pass
        self._initialized = False

    def _collect(self) -> TelemetrySnapshot:
        """Collect metrics for all devices.  Resets and re-raises on fatal errors."""
        try:
            device_count: int = _pynvml.nvmlDeviceGetCount()  # type: ignore[union-attr]
        except _NVMLError as exc:
            self._reset()
            raise  # sampler catches this as Exception; backoff + re-init next cycle

        if device_count == 0:
            return TelemetrySnapshot(
                timestamp_ms=int(time.time() * 1000),
                telemetry_available=False,
                gpu_count=0,
                per_gpu=[],
                degrade_reason=(
                    "nvmlDeviceGetCount() returned 0 – no GPU devices visible "
                    "(container missing /dev/nvidia* device mounts?)"
                ),
            )

        per_gpu: List[GpuSnapshot] = [
            self._fetch_single_gpu(idx) for idx in range(device_count)
        ]

        return TelemetrySnapshot(
            timestamp_ms=int(time.time() * 1000),
            telemetry_available=True,
            gpu_count=device_count,
            per_gpu=per_gpu,
        )

    def _fetch_single_gpu(self, idx: int) -> GpuSnapshot:
        """
        Fetch metrics for one GPU.  Per-device errors are downgraded to
        ``None`` field values rather than propagating, so a single faulty GPU
        does not abort the entire snapshot collection.
        """
        assert _pynvml is not None  # guaranteed by caller

        try:
            handle = _pynvml.nvmlDeviceGetHandleByIndex(idx)
        except _NVMLError as exc:
            logger.warning("GPU %d: failed to obtain device handle – %s", idx, exc)
            return GpuSnapshot(gpu_index=idx)

        # ── Memory ────────────────────────────────────────────────────────────
        mem_used: Optional[int] = None
        mem_free: Optional[int] = None
        mem_total: Optional[int] = None
        vram_ratio: Optional[float] = None

        try:
            mem_info = _pynvml.nvmlDeviceGetMemoryInfo(handle)
            mem_used = int(mem_info.used)
            mem_free = int(mem_info.free)
            mem_total = int(mem_info.total)
            # TODO (Architecture): True fragmentation requires introspection into the CUDA
            # Caching Allocator (e.g., exposing vLLM internal metrics) and will be
            # integrated via an external metrics endpoint in Phase 2.  Keep this NVML
            # layer strictly for OS-level hardware limit telemetry.
            if mem_total and mem_total > 0:
                vram_ratio = round(mem_used / mem_total, 6)
        except _NVMLError as exc:
            logger.warning(
                "GPU %d: nvmlDeviceGetMemoryInfo failed – %s", idx, exc
            )

        # ── SM & memory-bandwidth utilization ─────────────────────────────────
        sm_util: Optional[int] = None
        mem_bw_util: Optional[int] = None

        try:
            util = _pynvml.nvmlDeviceGetUtilizationRates(handle)
            sm_util = int(util.gpu)
            mem_bw_util = int(util.memory)
        except _NVMLError as exc:
            logger.warning(
                "GPU %d: nvmlDeviceGetUtilizationRates failed – %s", idx, exc
            )

        return GpuSnapshot(
            gpu_index=idx,
            memory_used_bytes=mem_used,
            memory_free_bytes=mem_free,
            memory_total_bytes=mem_total,
            vram_utilization_ratio=vram_ratio,
            sm_utilization_percent=sm_util,
            memory_bandwidth_utilization_percent=mem_bw_util,
        )
