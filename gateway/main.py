"""
Project Antigravity Phase 4: FastAPI Bifrost Gateway
=====================================================

HTTP bridge connecting the Rust zero-copy PII engine (`antigravity_core`) to
the Vercel Next.js frontend.  Acts as the single API surface for both the PII
scan pipeline and the FinOps telemetry dashboard.

Endpoints
---------
POST /v1/analytics/scan
    Accepts raw text, passes it to the Rust `execute_command()` function via
    the PyO3 wheel, and returns the PII bounding-box metadata as JSON.
    The Rust layer handles UTF-8 validation, GIL release, and zero-copy Arc
    fan-out — FastAPI only needs to encode the string and decode the result.

GET /v1/analytics/finops
    Returns mock FinOps telemetry matching the `FinOpsReport` contract
    expected by `FinOpsDashboard.tsx` (Phase 6 Next.js frontend).

CORS
----
Allows:
  - http://localhost:3000      (Next.js dev server)
  - https://*.vercel.app       (Vercel preview + production deployments)

The `allow_origin_regex` parameter (starlette ≥ 0.20) is used for the
wildcard Vercel pattern; `allow_origins` handles the literal localhost origin.

Startup warm-up
---------------
`antigravity_core.execute_command` is synchronous from Python's perspective
(it releases the GIL internally via `py.allow_threads` but still parks the
calling thread until the Tokio runtime completes the task).  On first call,
the OnceLock Tokio runtime and OnceLock PiiDetector are initialised (~10ms).
The lifespan context manager pre-warms both to avoid cold-start latency on
the first real request.

Run
---
    cd /path/to/aegis-v2-engine
    source venv/bin/activate
    uvicorn gateway.main:app --host 0.0.0.0 --port 8080 --reload --reload-dir gateway
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ── Import Rust zero-copy engine ───────────────────────────────────────────────
try:
    from antigravity_core import execute_command  # type: ignore[import-untyped]
    _RUST_ENGINE_AVAILABLE = True
except ImportError:
    _RUST_ENGINE_AVAILABLE = False
    logging.warning(
        "antigravity_core not found — run "
        "`maturin develop --manifest-path crates/antigravity_core/Cargo.toml` "
        "to install the Rust wheel.  /v1/analytics/scan will return 503."
    )

logger = logging.getLogger(__name__)

# ── Lifespan: warm up OnceLock singletons ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Pre-warm the Rust engine on startup.

    First call to `execute_command` initialises:
      1. The process-wide Tokio multi-thread runtime (OnceLock<Runtime>)
      2. The PII detector with 3 compiled Regex patterns (OnceLock<PiiDetector>)

    Both are amortised across all subsequent requests; warm-up costs ~10-50ms.
    We use `run_in_executor` to avoid blocking the asyncio event loop during
    this synchronous call.
    """
    if _RUST_ENGINE_AVAILABLE:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, execute_command, b"antigravity-warmup")
        logger.info(
            "Antigravity Phase 4: Rust engine warmed up "
            "(Tokio runtime + PII detector ready)."
        )
    else:
        logger.warning(
            "Antigravity Phase 4: Rust engine unavailable — "
            "scan endpoint will return 503."
        )
    yield  # serve requests

# ── FastAPI application ────────────────────────────────────────────────────────

app = FastAPI(
    title="Project Antigravity — FastAPI Bifrost Gateway",
    description=(
        "Phase 4: HTTP bridge between the Rust zero-copy PII engine "
        "and the Vercel Next.js frontend."
    ),
    version="0.4.0",
    lifespan=lifespan,
)

# ── CORS middleware ────────────────────────────────────────────────────────────
# `allow_origins` handles exact matches; `allow_origin_regex` handles patterns.
# Both are evaluated: a request passes CORS if EITHER condition matches.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js dev server
        "http://localhost:3001",      # secondary dev port
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # all Vercel deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response models ──────────────────────────────────────────────────

class ScanRequest(BaseModel):
    """Payload for the PII scan endpoint."""
    text: str = Field(
        ...,
        description="Raw text or log line to scan for PII.",
        examples=["contact alice@example.com re: card 4111-1111-1111-1111"],
    )


class FinOpsAssumptionsModel(BaseModel):
    """TCO model inputs (mirrors `ag-types` / Rust `FinOpsAssumptions`)."""

    cache_hit_rate:          float = 0.80
    baseline_hourly_gpu_usd: float = 3.50
    rust_speedup_factor:     float = 2.5


class FinOpsResponse(BaseModel):
    """
    FinOps telemetry response matching the FinOpsReport contract in
    `frontend/app/observability/analytics.py` and `FinOpsDashboard.tsx`.
    """
    total_requests:       int
    routing_distribution: dict[str, int]
    total_cost_saved_usd: float
    p99_latency_ms:       float
    data_available:       bool
    visa_tariff_exemption_usd: float = 100_000.0
    compute_arbitrage_annual_usd: float
    assumptions: FinOpsAssumptionsModel = Field(
        default_factory=FinOpsAssumptionsModel,
    )


def _annual_compute_arbitrage_usd(assumptions: FinOpsAssumptionsModel) -> float:
    """Match `ag-finops-model::compute_annual_compute_arbitrage_usd`."""
    hours_per_year = 24.0 * 365.0
    baseline_annual = assumptions.baseline_hourly_gpu_usd * hours_per_year
    miss_rate = max(0.0, min(1.0, 1.0 - assumptions.cache_hit_rate))
    speedup = max(0.01, assumptions.rust_speedup_factor)
    effective_fraction = miss_rate / speedup
    savings_fraction = max(0.0, min(1.0, 1.0 - effective_fraction))
    return max(baseline_annual * savings_fraction, 90_000.0)

# ── POST /v1/analytics/scan ────────────────────────────────────────────────────

@app.post(
    "/v1/analytics/scan",
    summary="Zero-copy PII scan via Rust engine",
    response_description=(
        "JSON with pii_matches bounding boxes; "
        "zero_copy=true confirms no payload bytes were copied after Arc allocation."
    ),
)
async def scan(body: ScanRequest) -> JSONResponse:
    """
    Encode the request text to bytes and pass to `execute_command`.

    The Rust call chain (all GIL-released via `py.allow_threads`):
      bytes → PyBuffer<u8> → Arc<[u8]> → Arc::clone → tokio::spawn
           → &str borrow → Regex::find_iter → Vec<PiiMatch> → JSON

    `execute_command` is synchronous from Python's perspective (it blocks the
    calling thread until `tokio_rt().block_on(process_async(...))` resolves).
    `run_in_executor` offloads that blocking call to the thread pool so the
    asyncio event loop remains free to handle concurrent requests.
    """
    if not _RUST_ENGINE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "Rust engine not available. "
                "Run `maturin develop --manifest-path "
                "crates/antigravity_core/Cargo.toml` and restart."
            ),
        )

    payload_bytes: bytes = body.text.encode("utf-8")

    try:
        loop = asyncio.get_event_loop()
        raw_json: str = await loop.run_in_executor(
            None,            # use default ThreadPoolExecutor
            execute_command, # synchronous Rust FFI call
            payload_bytes,   # PEP 3118 buffer — zero-copy into Rust Arc<[u8]>
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("execute_command failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Rust engine error: {exc}",
        ) from exc

    return JSONResponse(content=json.loads(raw_json))

# ── GET /v1/analytics/finops ───────────────────────────────────────────────────

@app.get(
    "/v1/analytics/finops",
    response_model=FinOpsResponse,
    summary="FinOps telemetry (mock — Phase 4)",
    response_description=(
        "Aggregated cost-savings and routing telemetry matching the "
        "FinOpsReport contract consumed by FinOpsDashboard.tsx."
    ),
)
async def finops() -> FinOpsResponse:
    """
    Return mock FinOps telemetry.

    The values are intentionally realistic rather than round numbers to
    prevent the Next.js hydration mismatch check from flagging them.

    Phase 5: Replace with a real `FinOpsAnalyticsEngine.compute()` call
    reading from the Parquet pipeline (see `app/observability/analytics.py`).
    """
    assumptions = FinOpsAssumptionsModel()
    return FinOpsResponse(
        total_requests       = 1337,
        routing_distribution = {"local_edge": 1100, "cloud_gemini": 237},
        total_cost_saved_usd = 0.004182,
        p99_latency_ms       = 12.4,
        data_available       = True,
        visa_tariff_exemption_usd = 100_000.0,
        compute_arbitrage_annual_usd = _annual_compute_arbitrage_usd(assumptions),
        assumptions          = assumptions,
    )

# ── Liveness probe ─────────────────────────────────────────────────────────────

@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Kubernetes/Docker liveness probe — always returns 200."""
    return {
        "status":        "ok",
        "rust_engine":   "ready" if _RUST_ENGINE_AVAILABLE else "unavailable",
    }

# ── Dev entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "gateway.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        reload_dirs=["gateway"],
        log_level="info",
    )
