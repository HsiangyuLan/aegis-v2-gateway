"""
Runtime configuration loaded from environment variables.

All settings are prefixed with ``AEGIS_`` to avoid collisions.  No
external dependency (e.g. pydantic-settings) is required; values are read
directly from ``os.environ`` with typed conversion and sensible defaults.

Usage::

    from app.core.config import get_settings
    s = get_settings()
    print(s.telemetry_poll_interval_s)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    # ── Telemetry sampler ────────────────────────────────────────────────────
    # How often (seconds) the background task polls NVML.
    telemetry_poll_interval_s: float

    # Maximum wall-clock time (seconds) allowed for a single NVML fetch before
    # it is considered timed out and the state is degraded.
    telemetry_nvml_timeout_s: float

    # Ceiling for the exponential back-off interval when NVML calls keep failing.
    telemetry_max_backoff_s: float

    # Multiplier applied to the current interval on each backoff step.
    telemetry_backoff_factor: float

    # Number of consecutive failures before exponential backoff is activated.
    telemetry_fail_threshold: int

    # ── Routing decision thresholds ──────────────────────────────────────────
    # Semantic entropy score below which a prompt is considered "low uncertainty"
    # and may be routed to the local edge model.  Strictly less-than comparison.
    entropy_threshold: float

    # VRAM utilization ratio (0.0–1.0) above which the local node is considered
    # too full and all traffic is forced to the cloud.  Strictly less-than.
    vram_threshold: float

    # Simulated latency (seconds) for the mock LocalEdgeBackend.  Represents
    # the ~50ms inference time of a quantized model on the edge node.
    local_edge_mock_delay_s: float

    # ── Cloud Gemini backend ─────────────────────────────────────────────────
    # Base URL for the Gemini generative language API.
    cloud_gemini_base_url: str

    # API key for Gemini.  Empty string activates mock mode: no real HTTP
    # request is made; a fake response is returned after a short delay.
    cloud_gemini_api_key: str

    # ── httpx connection pool ────────────────────────────────────────────────
    # Hard cap on total open TCP connections in the shared AsyncClient pool.
    httpx_max_connections: int

    # Number of keep-alive connections to maintain for connection reuse.
    httpx_max_keepalive: int

    # Seconds to wait for a TCP handshake to complete.
    httpx_connect_timeout_s: float

    # Seconds to wait for the full response body to arrive.
    httpx_read_timeout_s: float

    # Seconds to wait when all connections are busy before raising PoolTimeout.
    httpx_pool_timeout_s: float

    # ── Circuit breaker ───────────────────────────────────────────────────────
    # Number of consecutive qualifying failures (5xx or timeout) before the
    # circuit transitions from CLOSED → OPEN.
    circuit_breaker_failure_threshold: int

    # Seconds the circuit stays OPEN before allowing one probe (HALF-OPEN).
    circuit_breaker_cooldown_s: float

    # ── FinOps logging ────────────────────────────────────────────────────────
    # Directory where per-flush Parquet files are written.
    finops_log_dir: str

    # Seconds between automatic buffer flushes to disk.
    finops_flush_interval_s: float

    # Maximum number of log records held in the asyncio.Queue before new
    # records are dropped with a warning (prevents unbounded memory growth).
    finops_buffer_max_size: int

    # Estimated Gemini API cost per prompt word (USD).  Used to compute the
    # ``cost_saved_usd`` field when a request is handled by the local edge.
    # ~$3 per million words is a rough Gemini Pro approximation.
    finops_gemini_cost_per_word_usd: float

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str

    # ── Rust ONNX / cascading SEP ─────────────────────────────────────────────
    # Fast (sentinel) INT8 MiniLM — primary ONNX for entropy scoring.
    rust_fast_model_path: str

    # Optional quality (scholar/monarch) ONNX; empty = fast-only cascade.
    rust_quality_model_path: str

    # tokenizer.json for WordPiece alignment with MiniLM-family models.
    rust_tokenizer_path: str

    rust_max_seq_len: int
    rust_num_sessions: int

    # Ambiguity on fast path ≥ this ⇒ run quality ONNX (if configured).
    cascade_uncertainty_trigger: float

    # After quality: ambiguity ≥ this ⇒ Monarch tier (else Scholar).
    cascade_monarch_uncertainty: float

    # ── Phase 2: Disaggregated Worker Registry ────────────────────────────────
    # Comma-separated list of disaggregated worker base URLs.
    # Empty list (default) disables Phase 2; the system falls back to Sprint 3
    # single-backend local routing.
    # Example: "http://worker-0:8000,http://worker-1:8000"
    kv_worker_endpoints: list[str]

    # How often (seconds) the background worker registry poller polls each
    # worker's /metrics endpoint.
    kv_poll_interval_s: float

    # Maximum number of whitespace-split words to hash when computing the
    # prompt prefix fingerprint for radix-tree lookup.  Higher values give
    # more precise prefix matching at the cost of slightly more hashing work
    # (still O(k), bounded constant).
    kv_prefix_match_depth: int

    # Minimum KV cache free_ratio a worker must have to be eligible for
    # selection.  Workers at or below this ratio are treated as full and
    # skipped during Stage 2 routing.
    kv_min_free_ratio: float

    # Fraction of total_blocks that must DROP between two consecutive polls to
    # trigger a KV cache eviction event.  Eviction invalidates that worker's
    # prefix cache entries to prevent stale hits.
    kv_eviction_detection_threshold: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings(
        # Telemetry
        telemetry_poll_interval_s=float(
            os.environ.get("AEGIS_TELEMETRY_POLL_INTERVAL_S", "1.0")
        ),
        telemetry_nvml_timeout_s=float(
            os.environ.get("AEGIS_TELEMETRY_NVML_TIMEOUT_S", "0.5")
        ),
        telemetry_max_backoff_s=float(
            os.environ.get("AEGIS_TELEMETRY_MAX_BACKOFF_S", "60.0")
        ),
        telemetry_backoff_factor=float(
            os.environ.get("AEGIS_TELEMETRY_BACKOFF_FACTOR", "2.0")
        ),
        telemetry_fail_threshold=int(
            os.environ.get("AEGIS_TELEMETRY_FAIL_THRESHOLD", "3")
        ),
        # Routing
        entropy_threshold=float(
            os.environ.get("AEGIS_ENTROPY_THRESHOLD", "0.4")
        ),
        vram_threshold=float(
            os.environ.get("AEGIS_VRAM_THRESHOLD", "0.85")
        ),
        local_edge_mock_delay_s=float(
            os.environ.get("AEGIS_LOCAL_EDGE_MOCK_DELAY_S", "0.05")
        ),
        # Cloud backend
        cloud_gemini_base_url=os.environ.get(
            "AEGIS_CLOUD_GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com",
        ),
        cloud_gemini_api_key=os.environ.get("AEGIS_CLOUD_GEMINI_API_KEY", ""),
        # httpx pool
        httpx_max_connections=int(
            os.environ.get("AEGIS_HTTPX_MAX_CONNECTIONS", "100")
        ),
        httpx_max_keepalive=int(
            os.environ.get("AEGIS_HTTPX_MAX_KEEPALIVE", "20")
        ),
        httpx_connect_timeout_s=float(
            os.environ.get("AEGIS_HTTPX_CONNECT_TIMEOUT_S", "2.0")
        ),
        httpx_read_timeout_s=float(
            os.environ.get("AEGIS_HTTPX_READ_TIMEOUT_S", "10.0")
        ),
        httpx_pool_timeout_s=float(
            os.environ.get("AEGIS_HTTPX_POOL_TIMEOUT_S", "5.0")
        ),
        # Circuit breaker
        circuit_breaker_failure_threshold=int(
            os.environ.get("AEGIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")
        ),
        circuit_breaker_cooldown_s=float(
            os.environ.get("AEGIS_CIRCUIT_BREAKER_COOLDOWN_S", "30.0")
        ),
        # FinOps logging
        finops_log_dir=os.environ.get("AEGIS_FINOPS_LOG_DIR", "./logs/finops"),
        finops_flush_interval_s=float(
            os.environ.get("AEGIS_FINOPS_FLUSH_INTERVAL_S", "5.0")
        ),
        finops_buffer_max_size=int(
            os.environ.get("AEGIS_FINOPS_BUFFER_MAX_SIZE", "10000")
        ),
        finops_gemini_cost_per_word_usd=float(
            os.environ.get("AEGIS_FINOPS_GEMINI_COST_PER_WORD_USD", "0.000003")
        ),
        log_level=os.environ.get("AEGIS_LOG_LEVEL", "INFO"),
        rust_fast_model_path=os.environ.get(
            "AEGIS_RUST_FAST_MODEL_PATH",
            "models/minilm-v2-int8.onnx",
        ),
        rust_quality_model_path=os.environ.get("AEGIS_RUST_QUALITY_MODEL_PATH", ""),
        rust_tokenizer_path=os.environ.get(
            "AEGIS_RUST_TOKENIZER_PATH",
            "models/tokenizer/tokenizer.json",
        ),
        rust_max_seq_len=int(os.environ.get("AEGIS_RUST_MAX_SEQ_LEN", "64")),
        rust_num_sessions=int(
            os.environ.get(
                "AEGIS_RUST_NUM_SESSIONS",
                str(os.cpu_count() or 4),
            )
        ),
        cascade_uncertainty_trigger=float(
            os.environ.get("AEGIS_CASCADE_UNCERTAINTY_TRIGGER", "0.35")
        ),
        cascade_monarch_uncertainty=float(
            os.environ.get("AEGIS_CASCADE_MONARCH_UNCERTAINTY", "0.42")
        ),
        # Phase 2: Disaggregated worker pool
        kv_worker_endpoints=[
            ep.strip()
            for ep in os.environ.get("AEGIS_KV_WORKER_ENDPOINTS", "").split(",")
            if ep.strip()
        ],
        kv_poll_interval_s=float(
            os.environ.get("AEGIS_KV_POLL_INTERVAL_S", "1.0")
        ),
        kv_prefix_match_depth=int(
            os.environ.get("AEGIS_KV_PREFIX_MATCH_DEPTH", "32")
        ),
        kv_min_free_ratio=float(
            os.environ.get("AEGIS_KV_MIN_FREE_RATIO", "0.15")
        ),
        kv_eviction_detection_threshold=float(
            os.environ.get("AEGIS_KV_EVICTION_DETECTION_THRESHOLD", "0.20")
        ),
    )
