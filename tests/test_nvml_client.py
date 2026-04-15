"""
Unit tests for NvmlClient.

All NVML calls are mocked; no real GPU hardware is required.

Patching strategy
─────────────────
``nvml_client.py`` stores module-level references:

  ``_pynvml``          – the pynvml module (or None when not installed)
  ``PYNVML_AVAILABLE`` – bool flag set at import time
  ``_NVMLError``       – the NVMLError class (or Exception as sentinel)

We patch these directly so each test can simulate any failure mode without
reloading the module.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.telemetry.nvml_client import NvmlClient, NvmlUnavailableError


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeNVMLError(Exception):
    """Stand-in for pynvml.NVMLError in tests."""


def _make_mock_pynvml(
    *,
    device_count: int = 1,
    mem_used: int = 2 * 1024 ** 3,
    mem_free: int = 6 * 1024 ** 3,
    mem_total: int = 8 * 1024 ** 3,
    sm_util: int = 42,
    mem_bw_util: int = 20,
) -> MagicMock:
    """Return a MagicMock that behaves like a healthy pynvml module."""
    m = MagicMock()
    m.NVMLError = _FakeNVMLError
    m.nvmlInit.return_value = None
    m.nvmlShutdown.return_value = None
    m.nvmlDeviceGetCount.return_value = device_count

    handle = MagicMock()
    m.nvmlDeviceGetHandleByIndex.return_value = handle

    mem_info = MagicMock()
    mem_info.used = mem_used
    mem_info.free = mem_free
    mem_info.total = mem_total
    m.nvmlDeviceGetMemoryInfo.return_value = mem_info

    util_rates = MagicMock()
    util_rates.gpu = sm_util
    util_rates.memory = mem_bw_util
    m.nvmlDeviceGetUtilizationRates.return_value = util_rates

    return m


def _patched(mock_nvml: MagicMock, available: bool = True):
    """Context manager: patch all three module-level names at once."""
    return (
        patch("app.telemetry.nvml_client.PYNVML_AVAILABLE", available),
        patch("app.telemetry.nvml_client._pynvml", mock_nvml),
        patch("app.telemetry.nvml_client._NVMLError", _FakeNVMLError),
    )


# ── Package-not-installed cases ───────────────────────────────────────────────

class TestNvmlPackageMissing:
    def test_raises_nvml_unavailable_error(self) -> None:
        with (
            patch("app.telemetry.nvml_client.PYNVML_AVAILABLE", False),
            patch(
                "app.telemetry.nvml_client._PYNVML_IMPORT_ERROR",
                "No module named 'pynvml'",
            ),
        ):
            client = NvmlClient()
            with pytest.raises(NvmlUnavailableError, match="nvidia-ml-py3"):
                client.fetch_snapshot_sync()

    def test_shutdown_is_safe_when_not_available(self) -> None:
        with patch("app.telemetry.nvml_client.PYNVML_AVAILABLE", False):
            client = NvmlClient()
            client.shutdown()  # must not raise


# ── nvmlInit failure cases ────────────────────────────────────────────────────

class TestNvmlInitFailure:
    def test_nvml_error_wrapped_as_unavailable(self) -> None:
        mock_nvml = _make_mock_pynvml()
        mock_nvml.nvmlInit.side_effect = _FakeNVMLError("Driver not loaded")
        with patch("app.telemetry.nvml_client.PYNVML_AVAILABLE", True), \
             patch("app.telemetry.nvml_client._pynvml", mock_nvml), \
             patch("app.telemetry.nvml_client._NVMLError", _FakeNVMLError):
            client = NvmlClient()
            with pytest.raises(NvmlUnavailableError, match="nvmlInit"):
                client.fetch_snapshot_sync()

    def test_os_error_wrapped_as_unavailable(self) -> None:
        mock_nvml = _make_mock_pynvml()
        mock_nvml.nvmlInit.side_effect = OSError("libnvidia-ml.so not found")
        with patch("app.telemetry.nvml_client.PYNVML_AVAILABLE", True), \
             patch("app.telemetry.nvml_client._pynvml", mock_nvml), \
             patch("app.telemetry.nvml_client._NVMLError", _FakeNVMLError):
            client = NvmlClient()
            with pytest.raises(NvmlUnavailableError, match="OS error"):
                client.fetch_snapshot_sync()

    def test_initialized_flag_stays_false_after_init_failure(self) -> None:
        mock_nvml = _make_mock_pynvml()
        mock_nvml.nvmlInit.side_effect = _FakeNVMLError("no driver")
        with patch("app.telemetry.nvml_client.PYNVML_AVAILABLE", True), \
             patch("app.telemetry.nvml_client._pynvml", mock_nvml), \
             patch("app.telemetry.nvml_client._NVMLError", _FakeNVMLError):
            client = NvmlClient()
            try:
                client.fetch_snapshot_sync()
            except NvmlUnavailableError:
                pass
            assert client._initialized is False


# ── Happy path ────────────────────────────────────────────────────────────────

class TestSuccessfulFetch:
    def test_single_gpu_snapshot_shape(self) -> None:
        mock_nvml = _make_mock_pynvml(
            device_count=1, mem_used=2 * 1024 ** 3, mem_total=8 * 1024 ** 3
        )
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        assert snap.telemetry_available is True
        assert snap.gpu_count == 1
        assert len(snap.per_gpu) == 1

    def test_single_gpu_memory_values(self) -> None:
        mock_nvml = _make_mock_pynvml(
            mem_used=2 * 1024 ** 3, mem_free=6 * 1024 ** 3, mem_total=8 * 1024 ** 3
        )
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        gpu = snap.per_gpu[0]
        assert gpu.memory_used_bytes == 2 * 1024 ** 3
        assert gpu.memory_free_bytes == 6 * 1024 ** 3
        assert gpu.memory_total_bytes == 8 * 1024 ** 3

    def test_vram_utilization_ratio_is_used_over_total(self) -> None:
        mock_nvml = _make_mock_pynvml(
            mem_used=2 * 1024 ** 3, mem_total=8 * 1024 ** 3
        )
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        assert snap.per_gpu[0].vram_utilization_ratio == pytest.approx(0.25, abs=1e-5)

    def test_sm_utilization_percent(self) -> None:
        mock_nvml = _make_mock_pynvml(sm_util=75)
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        assert snap.per_gpu[0].sm_utilization_percent == 75

    def test_multi_gpu_returns_all_devices(self) -> None:
        mock_nvml = _make_mock_pynvml(device_count=4)
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        assert snap.gpu_count == 4
        assert len(snap.per_gpu) == 4
        assert [g.gpu_index for g in snap.per_gpu] == [0, 1, 2, 3]

    def test_nvml_init_called_once_on_repeated_fetches(self) -> None:
        mock_nvml = _make_mock_pynvml()
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            client.fetch_snapshot_sync()
            client.fetch_snapshot_sync()
            client.fetch_snapshot_sync()

        assert mock_nvml.nvmlInit.call_count == 1


# ── Zero-device degrade ───────────────────────────────────────────────────────

class TestZeroDevices:
    def test_returns_degrade_snapshot(self) -> None:
        mock_nvml = _make_mock_pynvml(device_count=0)
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        assert snap.telemetry_available is False
        assert snap.gpu_count == 0
        assert snap.per_gpu == []
        assert snap.degrade_reason is not None

    def test_does_not_raise(self) -> None:
        mock_nvml = _make_mock_pynvml(device_count=0)
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            # Must not raise
            snap = client.fetch_snapshot_sync()
        assert snap is not None


# ── Partial per-device failure ────────────────────────────────────────────────

class TestPartialDeviceFailure:
    def test_memory_info_failure_sets_none_fields(self) -> None:
        mock_nvml = _make_mock_pynvml(device_count=1)
        mock_nvml.nvmlDeviceGetMemoryInfo.side_effect = _FakeNVMLError(
            "device not available"
        )
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        assert snap.telemetry_available is True  # overall snapshot still valid
        gpu = snap.per_gpu[0]
        assert gpu.memory_used_bytes is None
        assert gpu.vram_utilization_ratio is None
        # Utilization should still be present
        assert gpu.sm_utilization_percent == 42

    def test_utilization_failure_sets_none_fields(self) -> None:
        mock_nvml = _make_mock_pynvml(device_count=1)
        mock_nvml.nvmlDeviceGetUtilizationRates.side_effect = _FakeNVMLError(
            "util error"
        )
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        gpu = snap.per_gpu[0]
        assert gpu.sm_utilization_percent is None
        assert gpu.memory_bandwidth_utilization_percent is None
        # Memory should still be present
        assert gpu.memory_used_bytes is not None

    def test_handle_failure_returns_empty_gpu_snapshot(self) -> None:
        mock_nvml = _make_mock_pynvml(device_count=1)
        mock_nvml.nvmlDeviceGetHandleByIndex.side_effect = _FakeNVMLError(
            "handle error"
        )
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            snap = client.fetch_snapshot_sync()

        # Snapshot is still returned; GPU entry has all-None metrics
        assert len(snap.per_gpu) == 1
        gpu = snap.per_gpu[0]
        assert gpu.memory_used_bytes is None
        assert gpu.vram_utilization_ratio is None


# ── nvmlDeviceGetCount failure after successful init ──────────────────────────

class TestDeviceCountFailureAfterInit:
    def test_resets_initialized_flag(self) -> None:
        mock_nvml = _make_mock_pynvml()
        mock_nvml.nvmlDeviceGetCount.side_effect = _FakeNVMLError("driver reset")
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            with pytest.raises(_FakeNVMLError):
                client.fetch_snapshot_sync()
            assert client._initialized is False

    def test_next_call_retries_init(self) -> None:
        """After a reset, the next fetch should call nvmlInit() again."""
        mock_nvml = _make_mock_pynvml()
        # Fail on first device count, succeed on second
        mock_nvml.nvmlDeviceGetCount.side_effect = [
            _FakeNVMLError("transient"),
            1,
        ]
        patches = _patched(mock_nvml)
        with patches[0], patches[1], patches[2]:
            client = NvmlClient()
            with pytest.raises(_FakeNVMLError):
                client.fetch_snapshot_sync()
            # Second call should re-init and succeed
            snap = client.fetch_snapshot_sync()

        assert snap.telemetry_available is True
        assert mock_nvml.nvmlInit.call_count == 2  # once per init attempt
