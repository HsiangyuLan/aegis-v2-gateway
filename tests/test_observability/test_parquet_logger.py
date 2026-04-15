"""
Unit tests for RequestLogger.

Tests cover:
  * ``log()`` is non-blocking (sync put_nowait)
  * Buffer accumulates records; flush drains it
  * Written Parquet files have the correct schema and values
  * Final flush on ``stop()`` preserves records
  * Buffer-full records are dropped with a warning (not blocking)
  * FinOps analysis script reads the files correctly
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import polars as pl
import pytest

from app.core.config import Settings
from app.observability.parquet_logger import RequestLogRecord, RequestLogger


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(tmp_path: Path, **overrides) -> Settings:
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
        circuit_breaker_failure_threshold=3,
        circuit_breaker_cooldown_s=30.0,
        finops_log_dir=str(tmp_path / "finops"),
        finops_flush_interval_s=9999.0,  # manual flush only during tests
        finops_buffer_max_size=100,
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


def _record(
    request_id: str = "req-1",
    routed_to: str = "cloud_gemini",
    entropy: float = 0.5,
    latency: float = 100.0,
    cost: float = 0.0,
) -> RequestLogRecord:
    return RequestLogRecord(
        timestamp_ms=int(time.time() * 1000),
        request_id=request_id,
        entropy_score=entropy,
        routed_to=routed_to,
        latency_ms=latency,
        cost_saved_usd=cost,
    )


# ── Basic buffering ───────────────────────────────────────────────────────────

class TestBuffering:
    def test_log_is_synchronous(self, tmp_path: Path) -> None:
        """log() must never await; calling it without an event loop must not raise."""
        settings = _make_settings(tmp_path)
        # Create logger in an async context but test log() is sync
        loop = asyncio.new_event_loop()

        async def _inner():
            rl = RequestLogger(settings)
            # log() is sync - no need to await
            rl.log(_record())
            assert rl._buffer.qsize() == 1

        loop.run_until_complete(_inner())
        loop.close()

    async def test_multiple_records_queued(self, tmp_path: Path) -> None:
        rl = RequestLogger(_make_settings(tmp_path))
        for i in range(5):
            rl.log(_record(request_id=f"req-{i}"))
        assert rl._buffer.qsize() == 5

    async def test_buffer_full_drops_record(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path, finops_buffer_max_size=2)
        rl = RequestLogger(settings)
        rl.log(_record(request_id="r1"))
        rl.log(_record(request_id="r2"))
        rl.log(_record(request_id="r3"))  # should be dropped
        assert rl._buffer.qsize() == 2  # max size respected


# ── Parquet flush ─────────────────────────────────────────────────────────────

class TestParquetFlush:
    async def test_flush_drains_buffer(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        for i in range(3):
            rl.log(_record(request_id=f"req-{i}"))
        await rl._flush_once()
        assert rl._buffer.qsize() == 0

    async def test_flush_writes_parquet_file(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        rl.log(_record(request_id="req-x"))
        await rl._flush_once()
        log_dir = Path(settings.finops_log_dir)
        files = list(log_dir.glob("requests_*.parquet"))
        assert len(files) == 1

    async def test_written_file_has_correct_schema(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        rl.log(_record())
        await rl._flush_once()
        log_dir = Path(settings.finops_log_dir)
        files = list(log_dir.glob("requests_*.parquet"))
        df = pl.read_parquet(files[0])
        expected_cols = {
            "timestamp_ms",
            "request_id",
            "entropy_score",
            "routed_to",
            "latency_ms",
            "cost_saved_usd",
            # Phase 2 additions
            "selected_worker_id",
            "kv_prefix_hit",
        }
        assert set(df.columns) == expected_cols

    async def test_written_values_are_correct(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        rec = _record(
            request_id="my-id",
            routed_to="local_edge",
            entropy=0.123,
            latency=55.5,
            cost=0.000015,
        )
        rl.log(rec)
        await rl._flush_once()
        log_dir = Path(settings.finops_log_dir)
        df = pl.read_parquet(list(log_dir.glob("*.parquet"))[0])
        row = df.row(0, named=True)
        assert row["request_id"] == "my-id"
        assert row["routed_to"] == "local_edge"
        assert abs(row["entropy_score"] - 0.123) < 1e-9
        assert abs(row["latency_ms"] - 55.5) < 1e-9
        assert abs(row["cost_saved_usd"] - 0.000015) < 1e-12

    async def test_multiple_flushes_create_separate_files(
        self, tmp_path: Path
    ) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        rl.log(_record(request_id="r1"))
        await rl._flush_once()
        rl.log(_record(request_id="r2"))
        await rl._flush_once()
        log_dir = Path(settings.finops_log_dir)
        files = list(log_dir.glob("requests_*.parquet"))
        assert len(files) == 2

    async def test_empty_flush_creates_no_file(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        await rl._flush_once()  # nothing in buffer
        log_dir = Path(settings.finops_log_dir)
        assert len(list(log_dir.glob("*.parquet"))) == 0


# ── Lifecycle ─────────────────────────────────────────────────────────────────

class TestLifecycle:
    async def test_start_creates_background_task(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        await rl.start()
        assert rl._flush_task is not None
        assert not rl._flush_task.done()
        await rl.stop()

    async def test_stop_performs_final_flush(self, tmp_path: Path) -> None:
        """Records logged before stop() must appear in Parquet files."""
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        await rl.start()
        rl.log(_record(request_id="last-record"))
        await rl.stop()
        log_dir = Path(settings.finops_log_dir)
        files = list(log_dir.glob("*.parquet"))
        assert len(files) >= 1
        all_ids = []
        for f in files:
            df = pl.read_parquet(f)
            all_ids.extend(df["request_id"].to_list())
        assert "last-record" in all_ids

    async def test_stop_cancels_background_task(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)
        await rl.start()
        task = rl._flush_task
        await rl.stop()
        assert task.done()


# ── FinOps analysis script integration ───────────────────────────────────────

class TestFinopsAnalysisScript:
    async def test_analyze_reads_parquet_correctly(self, tmp_path: Path) -> None:
        """Verify that finops_analysis.analyze() reads our logger output."""
        from scripts.finops_analysis import analyze

        settings = _make_settings(tmp_path)
        rl = RequestLogger(settings)

        # Write 3 local_edge + 2 cloud_gemini records
        for i in range(3):
            rl.log(_record(
                request_id=f"local-{i}",
                routed_to="local_edge",
                latency=50.0 + i,
                cost=0.000006,
            ))
        for i in range(2):
            rl.log(_record(
                request_id=f"cloud-{i}",
                routed_to="cloud_gemini",
                latency=200.0 + i,
                cost=0.0,
            ))
        await rl._flush_once()

        log_dir = Path(settings.finops_log_dir)
        result = analyze(log_dir)

        assert "routed_to" in result.columns
        assert "total_requests" in result.columns
        assert "total_cost_saved_usd" in result.columns
        assert "avg_latency_ms" in result.columns

        total = result["total_requests"].sum()
        assert total == 5

        local_row = result.filter(pl.col("routed_to") == "local_edge")
        assert local_row["total_requests"].item() == 3
        assert local_row["total_cost_saved_usd"].item() == pytest.approx(0.000018)

    async def test_analyze_raises_when_no_files(self, tmp_path: Path) -> None:
        from scripts.finops_analysis import analyze

        with pytest.raises(FileNotFoundError):
            analyze(tmp_path / "empty_dir")
