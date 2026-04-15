"""
Aegis V2 — Frontend Data Gateway
=================================
Standalone FastAPI server (port 8001) that bridges simulation_results.parquet
to the Next.js dashboard. Intentionally separate from the main Aegis V2 gateway
(app/main.py on port 8080) to prevent coupling.

Parquet schema (written by scripts/run_production_demo.py):
  prompt_id        int32
  category         utf8
  entropy_score    int32
  ffi_overhead_ms  float64
  onnx_latency_ms  float64
  total_latency_ms float64
  tokens_generated int32
  cloud_cost_usd   float64
  local_cost_usd   float64
  aei              float64
  sla_breach       bool
  timestamp        float64  (Unix epoch seconds)

Endpoints
---------
  GET  /api/telemetry                → latest Parquet row as raw JSON
  GET  /api/stream                   → SSE stream of new rows (100ms poll)
  GET  /api/v1/metrics/live          → LiveMetrics (SWR 500ms)
  GET  /api/v1/assets/prices         → AssetPrice[] (SWR 1000ms)
  GET  /api/v1/sla/timeseries        → SlaTimeseries (SWR 1000ms)
  GET  /api/v1/transactions/stream   → SSE Transaction stream
  GET  /api/v1/telemetry/nodes       → TelemetryNodes (SWR 5000ms)
  GET  /api/v1/events/stream         → SSE TickerEvent stream

FileLock strategy
-----------------
The Rust/Python engine writes Parquet atomically (write → temp → rename).
We copy the file to a temp path before reading, so a concurrent write cannot
corrupt our read.  If the copy fails (mid-rename), we return the last cached
DataFrame.  asyncio.Lock serialises concurrent refresh calls.

Usage
-----
  python api_server.py                    # default port 8001
  AEGIS_GATEWAY_PORT=9000 python api_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import shutil
import statistics
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Iterator

import polars as pl
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ─── Configuration ────────────────────────────────────────────────────────────

PARQUET_PATH: Path = Path(
    os.environ.get("AEGIS_PARQUET_PATH", "output/simulation_results.parquet")
)
GATEWAY_PORT: int = int(os.environ.get("AEGIS_GATEWAY_PORT", "8001"))
REFRESH_INTERVAL_S: float = 0.1   # 100ms parquet poll interval
LOG_LEVEL: str = os.environ.get("AEGIS_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("aegis.gateway")

# ─── Pydantic Response Models (mirrors frontend/app/types/dashboard.ts) ───────

class LiveMetrics(BaseModel):
    capitalAllocation: float = Field(description="USD value of compute sovereignty fund")
    delta24h: float           = Field(description="24h percentage change in AEI")
    volatilityIndex: float    = Field(description="Latency coefficient of variation")
    nodesOnline: int          = Field(description="Active inference nodes (estimated)")
    latencyMs: float          = Field(description="Recent avg total latency ms")
    uptimePct: float          = Field(description="SLA compliance percentage")


class AssetPrice(BaseModel):
    symbol: str
    price: float
    spread: float
    trend: str   # "up" | "flat" | "down"


class SlaTimeseries(BaseModel):
    heights: list[float]  = Field(description="16 bar heights 0–100")
    slaPercent: float
    coreStatus: str       = Field(description="OPERATIONAL | DEGRADED | OFFLINE")
    memLeakPct: float


class Transaction(BaseModel):
    id: str
    timestamp: str
    action: str
    amount: str
    status: str       = Field(description="SUCCESS | PENDING | FAILED")
    isNegative: bool  = Field(default=False)


class TelemetryNodes(BaseModel):
    location: str
    latencyAsia: float
    latencyEu: float
    coordinates: list[float]  = Field(description="[lat, lon]")


class TickerEvent(BaseModel):
    id: str
    severity: str   = Field(description="info | warn | error")
    message: str


# ─── TOON Format v1.0 ─────────────────────────────────────────────────────────
# Transaction Object Output Notation — enriches each Transaction with canvas
# draw hints so ScrollyCanvas can render particles without additional processing.
#
# Hint derivation rules:
#   x, y    : golden-ratio position seeded by prompt_id (stable across re-renders)
#   r       : entropy_score / 10 * 8 + 2  → 2..10 px radius
#   color   : category-mapped brand colour
#   alpha   : 1.0 if SUCCESS, 0.55 if PENDING, 0.3 if FAILED/jailbreak
#   glow    : aei * 3_000_000 + 6  → 6..30 px glow radius
#   vx, vy  : micro-velocity derived from ffi/onnx ratio (for trail rendering)
#   layer   : 0=standard, 1=edge_case, 2=jailbreak, 3=breach

_TOON_CATEGORY_COLOR: dict[str, str] = {
    "standard":  "#38BDF8",   # cyan   — normal traffic
    "edge_case": "#FBBF24",   # amber  — boundary cases
    "jailbreak": "#F87171",   # red    — adversarial inputs
}


class ToonHints(BaseModel):
    """Canvas draw parameters consumed directly by ScrollyCanvas."""
    x:     float = Field(ge=0.0, le=1.0, description="Normalised x position 0–1")
    y:     float = Field(ge=0.0, le=1.0, description="Normalised y position 0–1")
    r:     float = Field(description="Particle radius px")
    color: str   = Field(description="Hex colour string")
    alpha: float = Field(ge=0.0, le=1.0, description="Opacity 0–1")
    glow:  float = Field(description="Glow radius px")
    vx:    float = Field(description="x velocity for trail rendering")
    vy:    float = Field(description="y velocity for trail rendering")
    layer: int   = Field(ge=0, le=3, description="z-layer 0=std 1=edge 2=jailbreak 3=breach")


class ToonFrame(BaseModel):
    """
    TOON/1.0 frame — wraps Transaction with canvas rendering metadata.
    Emitted by /api/v1/transactions/stream as SSE event type 'toon'.
    """
    v:     str         = Field(default="1.0",  description="TOON format version")
    f:     int         = Field(description="Monotonically increasing frame index")
    t:     int         = Field(description="Unix timestamp milliseconds")
    tx:    Transaction = Field(description="Transaction payload")
    hints: ToonHints   = Field(description="Canvas draw hints for ScrollyCanvas")


# ─── Safe Parquet Reader ──────────────────────────────────────────────────────

class ParquetGateway:
    """
    Thread-safe, copy-before-read Parquet cache.

    The Rust/Python simulation engine writes Parquet using PyArrow's atomic
    write-then-rename pattern.  We further protect our reads by:

      1. Copying the file to a sibling temp path under asyncio.Lock.
      2. Reading from the copy so the original can be overwritten mid-read.
      3. Deleting the temp copy immediately after.
      4. Falling back to the last cached DataFrame on any I/O exception.

    Attributes
    ----------
    _df          : Last successfully loaded DataFrame.
    _lock        : Serialises concurrent refresh calls.
    _last_row_count : Row count of _df at last successful read.
    _refresh_ms  : Wall-clock timestamp of last successful refresh.
    """

    def __init__(self, path: Path) -> None:
        self._path: Path = path
        self._tmp_path: Path = path.with_suffix(".gateway_tmp.parquet")
        self._df: pl.DataFrame = pl.DataFrame()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._last_row_count: int = 0
        self._refresh_ms: float = 0.0

    @property
    def row_count(self) -> int:
        return len(self._df)

    @property
    def df(self) -> pl.DataFrame:
        return self._df

    async def refresh(self) -> bool:
        """
        Attempt a safe copy-and-read of the Parquet file.

        Returns True if new rows were found, False otherwise.
        Silently swallows I/O errors and returns False (keeps cached data).
        """
        if not self._path.exists():
            return False

        async with self._lock:
            try:
                # Atomic copy — if the source is mid-rename, shutil.copy2
                # will raise FileNotFoundError / PermissionError, which we catch.
                await asyncio.to_thread(shutil.copy2, self._path, self._tmp_path)

                fresh: pl.DataFrame = await asyncio.to_thread(
                    pl.read_parquet, str(self._tmp_path)
                )

                # Always clean up temp file
                await asyncio.to_thread(self._tmp_path.unlink, True)

                if len(fresh) > self._last_row_count:
                    self._df = fresh
                    old_count = self._last_row_count
                    self._last_row_count = len(fresh)
                    self._refresh_ms = time.monotonic() * 1000
                    logger.debug(
                        "Parquet refreshed: %d → %d rows (+%d)",
                        old_count, len(fresh), len(fresh) - old_count
                    )
                    return True
                return False

            except Exception as exc:
                # Swallow — keep cached data; log at debug to avoid noise
                logger.debug("Parquet read skipped (%s): %s", type(exc).__name__, exc)
                try:
                    await asyncio.to_thread(self._tmp_path.unlink, True)
                except Exception:
                    pass
                return False

    def latest_rows(self, n: int = 1) -> list[dict[str, Any]]:
        """Return the last n rows as a list of plain dicts."""
        if self._df.is_empty():
            return []
        tail = self._df.tail(n)
        return tail.to_dicts()

    def all_rows(self) -> list[dict[str, Any]]:
        """Return all rows as a list of plain dicts."""
        return self._df.to_dicts() if not self._df.is_empty() else []

    def new_rows_since(self, last_seen_count: int) -> list[dict[str, Any]]:
        """Return rows added after last_seen_count."""
        if self._df.is_empty() or len(self._df) <= last_seen_count:
            return []
        return self._df.slice(last_seen_count).to_dicts()


# ─── SSE Broadcast Bus ────────────────────────────────────────────────────────

class SseBus:
    """
    Broadcast bus for SSE connections.

    Multiple concurrent SSE clients each receive an asyncio.Queue.
    The background refresh task calls `publish()` when new Parquet rows arrive;
    each queue entry is a pre-serialised SSE data line.
    """

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[str]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._queues.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            try:
                self._queues.remove(q)
            except ValueError:
                pass

    async def publish(self, payload: str) -> None:
        """Enqueue payload to all connected clients (drops if queue full)."""
        async with self._lock:
            for q in self._queues:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    # Slow consumer — drop silently rather than block
                    pass


# ─── Global singletons ────────────────────────────────────────────────────────

gateway = ParquetGateway(PARQUET_PATH)
raw_row_bus: SseBus = SseBus()       # /api/stream
tx_bus: SseBus = SseBus()            # /api/v1/transactions/stream  (TOON Format)
events_bus: SseBus = SseBus()        # /api/v1/events/stream

# Monotonic TOON frame counter — persists across parquet refreshes.
_toon_frame_counter: int = 0


# ─── Data Derivation Helpers ──────────────────────────────────────────────────

_CATEGORY_TO_ACTION: dict[str, str] = {
    "standard":   "INFERENCE_REQ",
    "edge_case":  "EDGE_CASE_PROC",
    "jailbreak":  "THREAT_BLOCKED",
}

# Static seed prices for AssetCard (drift applied from AEI data)
_ASSET_BASES: list[dict[str, Any]] = [
    {"symbol": "BTC/USD",  "basePrice": 64102.11, "spread": 0.0012},
    {"symbol": "ETH/USD",  "basePrice": 3421.90,  "spread": 0.0024},
    {"symbol": "SOL/USD",  "basePrice": 145.12,   "spread": 0.0041},
    {"symbol": "LINK/USD", "basePrice": 18.94,    "spread": 0.0008},
]


def _safe_mean(values: list[float]) -> float:
    """Return arithmetic mean, or 0.0 on empty list."""
    return statistics.mean(values) if values else 0.0


def _safe_stdev(values: list[float]) -> float:
    """Return population stdev, or 0.0 on fewer than 2 values."""
    return statistics.pstdev(values) if len(values) >= 2 else 0.0


def _compute_live_metrics(rows: list[dict[str, Any]]) -> LiveMetrics:
    """
    Derive LiveMetrics from the full simulation DataFrame rows.

    Capital allocation is modelled as a FinOps arbitrage accumulator:
        capital = Σ(cloud_cost − local_cost) × LEVERAGE_FACTOR + BASE_CAPITAL
    where LEVERAGE_FACTOR = 50,000 represents the multiplier of a fund that
    routes production traffic at this efficiency level.

    Delta 24h is derived from the AEI trend between the first and last decile
    of rows (simulates intra-day performance shift).
    """
    if not rows:
        return LiveMetrics(
            capitalAllocation=14892.44,
            delta24h=12.42,
            volatilityIndex=0.14,
            nodesOnline=1402,
            latencyMs=9.8,
            uptimePct=99.9,
        )

    LEVERAGE_FACTOR = 50_000.0
    BASE_CAPITAL = 9_800.0

    savings_list = [r["cloud_cost_usd"] - r["local_cost_usd"] for r in rows]
    total_savings = sum(savings_list)
    capital = total_savings * LEVERAGE_FACTOR + BASE_CAPITAL

    aei_list = [r["aei"] for r in rows]
    decile = max(1, len(aei_list) // 10)
    early_aei = _safe_mean(aei_list[:decile])
    late_aei  = _safe_mean(aei_list[-decile:])
    delta_24h = ((late_aei - early_aei) / early_aei * 100) if early_aei else 12.42

    latencies = [r["total_latency_ms"] for r in rows]
    mean_lat = _safe_mean(latencies)
    stdev_lat = _safe_stdev(latencies)
    volatility = (stdev_lat / mean_lat) if mean_lat else 0.0

    nodes_online = max(100, min(9999, len(rows) * 4 + 1000))

    recent_lat = [r["total_latency_ms"] for r in rows[-20:]]
    latest_ms = _safe_mean(recent_lat)

    breaches = sum(1 for r in rows if r["sla_breach"])
    uptime = (1.0 - breaches / len(rows)) * 100.0

    return LiveMetrics(
        capitalAllocation=round(capital, 2),
        delta24h=round(delta_24h, 2),
        volatilityIndex=round(volatility, 4),
        nodesOnline=nodes_online,
        latencyMs=round(latest_ms, 3),
        uptimePct=round(uptime, 3),
    )


def _compute_asset_prices(rows: list[dict[str, Any]]) -> list[AssetPrice]:
    """
    Derive asset prices by applying AEI-driven micro-drift to base prices.

    AEI fluctuation is mapped to a price drift multiplier, simulating the
    impact of on-chain compute efficiency on DeFi asset pricing.
    """
    if not rows:
        drift = 0.0
    else:
        recent = rows[-10:]
        drift = _safe_mean([r["aei"] for r in recent]) * 10_000  # normalise

    prices: list[AssetPrice] = []
    for i, asset in enumerate(_ASSET_BASES):
        # Each asset gets independent drift phase
        phase = drift * (1.0 + i * 0.17)
        price = asset["basePrice"] * (1.0 + math.sin(phase) * 0.002)

        # Trend derived from drift direction
        if abs(phase) < 0.001:
            trend = "flat"
        elif math.sin(phase) > 0.001:
            trend = "up"
        else:
            trend = "down"

        prices.append(AssetPrice(
            symbol=asset["symbol"],
            price=round(price, 2),
            spread=asset["spread"],
            trend=trend,
        ))

    return prices


def _compute_sla_timeseries(rows: list[dict[str, Any]]) -> SlaTimeseries:
    """
    Derive 16-bar SLA visualisation from the last 16 latency measurements.

    Bar height formula:
        height = clip(100 − (latency_ms − 5) / 30 × 100, lo=50, hi=100)
    Maps the "sweet-spot" 5–35ms range to the full 100–50% visual scale.
    """
    if not rows:
        default_h = [90, 85, 95, 80, 88, 92, 82, 75, 98, 90, 84, 86, 91, 88, 94, 78]
        return SlaTimeseries(
            heights=default_h,
            slaPercent=99.998,
            coreStatus="OPERATIONAL",
            memLeakPct=0.0,
        )

    tail16 = rows[-16:] if len(rows) >= 16 else rows
    # Pad to 16 entries if fewer rows available
    while len(tail16) < 16:
        tail16 = [tail16[-1]] + tail16  # type: ignore[list-item]

    heights: list[float] = []
    for r in tail16:
        lat = r["total_latency_ms"]
        h = 100.0 - (lat - 5.0) / 30.0 * 100.0
        heights.append(round(max(50.0, min(100.0, h)), 1))

    breach_count = sum(1 for r in rows if r["sla_breach"])
    breach_rate = breach_count / len(rows)
    sla_pct = (1.0 - breach_rate) * 100.0

    if breach_rate < 0.05:
        status = "OPERATIONAL"
    elif breach_rate < 0.15:
        status = "DEGRADED"
    else:
        status = "OFFLINE"

    return SlaTimeseries(
        heights=heights,
        slaPercent=round(sla_pct, 3),
        coreStatus=status,
        memLeakPct=0.0,
    )


def _row_to_transaction(row: dict[str, Any]) -> Transaction:
    """Convert a single Parquet row to a Transaction model."""
    ts_epoch: float = row.get("timestamp", time.time())
    ts_str = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).strftime("%H:%M:%S")

    category: str = row.get("category", "standard")
    action = _CATEGORY_TO_ACTION.get(category, "INFERENCE_REQ")
    tokens: int = row.get("tokens_generated", 0)
    latency: float = row.get("onnx_latency_ms", 0.0)
    amount_str = f"{tokens} TOKENS @ {latency:.2f}ms"
    is_breach: bool = row.get("sla_breach", False)
    status = "PENDING" if is_breach else "SUCCESS"
    is_negative = (category == "jailbreak")

    return Transaction(
        id=f"tx_{row.get('prompt_id', 0)}_{int(ts_epoch * 1000)}",
        timestamp=ts_str,
        action=action,
        amount=amount_str,
        status=status,
        isNegative=is_negative,
    )


def _row_to_toon_frame(row: dict[str, Any], frame_idx: int) -> ToonFrame:
    """
    Build a TOON/1.0 frame from a Parquet row.

    Canvas hint derivation
    ----------------------
    Position (x, y)
        Seeded from prompt_id via the golden-ratio sequence so that each node
        lands at a stable, well-distributed position on the canvas regardless
        of render order.

    Radius (r)
        Proportional to entropy_score (1–10 → 2–10px), reflecting the semantic
        complexity of the inference request.

    Glow (glow)
        Proportional to AEI — high-arbitrage captures emit a wider halo.

    Velocity (vx, vy)
        Derived from the FFI/ONNX latency ratio.  High FFI overhead → faster
        horizontal drift (cross-language pressure); high ONNX cost → vertical
        pull (compute gravity).
    """
    tx = _row_to_transaction(row)
    ts_epoch: float = row.get("timestamp", time.time())
    pid: int = row.get("prompt_id", 0)
    category: str = row.get("category", "standard")
    entropy: int = row.get("entropy_score", 5)
    aei: float = row.get("aei", 0.0)
    ffi_ms: float = row.get("ffi_overhead_ms", 0.5)
    onnx_ms: float = row.get("onnx_latency_ms", 8.0)
    is_breach: bool = row.get("sla_breach", False)

    # Golden-ratio position — deterministic per prompt_id
    PHI = 0.618033988749895
    x = (pid * PHI) % 1.0
    y = (pid * PHI * PHI) % 1.0

    # Radius: 2–10 px scaled by entropy
    r = 2.0 + (entropy / 10.0) * 8.0

    # Color: category-mapped
    color = _TOON_CATEGORY_COLOR.get(category, "#38BDF8")

    # Alpha: breach → dim; jailbreak → near-invisible
    if category == "jailbreak":
        alpha = 0.30
    elif is_breach:
        alpha = 0.55
    else:
        alpha = 0.90

    # Glow: AEI-driven, clamped 6–30 px
    glow = min(30.0, max(6.0, aei * 3_000_000.0 + 6.0))

    # Velocity: FFI/ONNX ratio → directional drift
    total_ms = ffi_ms + onnx_ms + 1e-9
    vx = round((ffi_ms / total_ms - 0.5) * 0.04, 5)   # [-0.02, +0.02]
    vy = round((onnx_ms / total_ms - 0.5) * 0.04, 5)

    # Layer: 0=std, 1=edge, 2=jailbreak, 3=breach
    if is_breach:
        layer = 3
    elif category == "jailbreak":
        layer = 2
    elif category == "edge_case":
        layer = 1
    else:
        layer = 0

    return ToonFrame(
        v="1.0",
        f=frame_idx,
        t=int(ts_epoch * 1000),
        tx=tx,
        hints=ToonHints(
            x=round(x, 5),
            y=round(y, 5),
            r=round(r, 2),
            color=color,
            alpha=round(alpha, 2),
            glow=round(glow, 2),
            vx=vx,
            vy=vy,
            layer=layer,
        ),
    )


def _row_to_ticker_events(row: dict[str, Any]) -> list[TickerEvent]:
    """Derive 0-3 TickerEvents from a single Parquet row."""
    events: list[TickerEvent] = []
    ts_ms = int(row.get("timestamp", time.time()) * 1000)
    pid: int = row.get("prompt_id", 0)
    category: str = row.get("category", "standard")
    aei: float = row.get("aei", 0.0)
    lat: float = row.get("total_latency_ms", 0.0)
    is_breach: bool = row.get("sla_breach", False)

    # Always emit block-verification event for standard traffic
    if category == "standard":
        events.append(TickerEvent(
            id=f"evt_blk_{pid}_{ts_ms}",
            severity="info",
            message=f"SYS_EVENT: BLOCK_{pid:08d}_VERIFIED",
        ))

    # Emit arbitrage capture event when AEI is above average
    if aei > 3e-6:
        events.append(TickerEvent(
            id=f"evt_arb_{pid}_{ts_ms}",
            severity="info",
            message=f"ARB_EXEC: AEI_CAPTURE_{aei:.6f}",
        ))

    # SLA breach → error event
    if is_breach:
        events.append(TickerEvent(
            id=f"evt_sla_{pid}_{ts_ms}",
            severity="error",
            message=f"SLA_BREACH: {category.upper()} exceeded {lat:.1f}ms",
        ))

    # Jailbreak threat → warn event
    if category == "jailbreak":
        events.append(TickerEvent(
            id=f"evt_thr_{pid}_{ts_ms}",
            severity="warn",
            message=f"THREAT_VECTOR: {category.upper()}_BLOCKED",
        ))

    return events


def _compute_telemetry_nodes(rows: list[dict[str, Any]]) -> TelemetryNodes:
    """
    Derive TelemetryNodes from recent simulation latency data.

    ASIA latency ≈ FFI overhead × 120 + base 32ms (simulates cross-region hop).
    EU   latency ≈ ONNX latency × 2  + base 14ms  (simulates CDN edge).
    """
    if not rows:
        return TelemetryNodes(
            location="40.7128° N, 74.0060° W",
            latencyAsia=142.0,
            latencyEu=28.0,
            coordinates=[40.7128, -74.006],
        )

    recent = rows[-5:]
    avg_ffi   = _safe_mean([r["ffi_overhead_ms"] for r in recent])
    avg_onnx  = _safe_mean([r["onnx_latency_ms"] for r in recent])

    asia_lat = round(avg_ffi * 120.0 + 32.0, 1)
    eu_lat   = round(avg_onnx * 2.0 + 14.0, 1)

    return TelemetryNodes(
        location="40.7128° N, 74.0060° W",
        latencyAsia=max(20.0, asia_lat),
        latencyEu=max(10.0, eu_lat),
        coordinates=[40.7128, -74.006],
    )


# ─── Background Refresh & Broadcast Task ─────────────────────────────────────

async def _background_refresh() -> None:
    """
    Poll the Parquet file every REFRESH_INTERVAL_S seconds.
    On new rows: broadcast to all SSE buses.
    Runs for the lifetime of the application.
    """
    global _toon_frame_counter
    last_broadcast_count: int = 0

    while True:
        try:
            await gateway.refresh()

            current_count = gateway.row_count
            if current_count > last_broadcast_count:
                new_rows = gateway.new_rows_since(last_broadcast_count)
                last_broadcast_count = current_count

                for row in new_rows:
                    # /api/stream — raw row JSON
                    raw_payload = f"data: {json.dumps(row)}\n\n"
                    await raw_row_bus.publish(raw_payload)

                    # /api/v1/transactions/stream — TOON Format v1.0
                    # SSE event type "toon" so clients can use es.addEventListener("toon", …)
                    toon = _row_to_toon_frame(row, _toon_frame_counter)
                    _toon_frame_counter += 1
                    toon_payload = f"event: toon\ndata: {toon.model_dump_json()}\n\n"
                    await tx_bus.publish(toon_payload)

                    # /api/v1/events/stream
                    for evt in _row_to_ticker_events(row):
                        evt_payload = f"data: {evt.model_dump_json()}\n\n"
                        await events_bus.publish(evt_payload)

        except Exception as exc:
            logger.warning("Background refresh error: %s", exc)

        await asyncio.sleep(REFRESH_INTERVAL_S)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background refresh on startup; cancel on shutdown."""
    if not PARQUET_PATH.exists():
        logger.warning(
            "Parquet file not found at %s. "
            "Run scripts/run_production_demo.py first. "
            "Serving demo data until file appears.",
            PARQUET_PATH,
        )

    task = asyncio.create_task(_background_refresh(), name="parquet_refresh")
    logger.info(
        "Aegis Gateway started — port %d, parquet=%s, poll=%.0fms",
        GATEWAY_PORT, PARQUET_PATH, REFRESH_INTERVAL_S * 1000,
    )
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Aegis Gateway shut down.")


# ─── Application ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Aegis V2 — Frontend Data Gateway",
    description=(
        "Bridges simulation_results.parquet to the Next.js dashboard. "
        "Provides REST snapshots and SSE streams for all dashboard components."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # Extend for staging / production domains as needed
    ],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# ─── SSE Helper ───────────────────────────────────────────────────────────────

async def _sse_generator(
    bus: SseBus,
    keepalive_interval_s: float = 15.0,
) -> AsyncGenerator[str, None]:
    """
    Yield SSE frames from a bus queue.
    Sends a keepalive comment every keepalive_interval_s to prevent proxy
    connection timeouts (nginx default: 60s).
    """
    queue = await bus.subscribe()
    last_keepalive = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            # Non-blocking check for next message
            try:
                msg = queue.get_nowait()
                yield msg
            except asyncio.QueueEmpty:
                # Send keepalive if no data arrived recently
                if now - last_keepalive >= keepalive_interval_s:
                    yield ": keepalive\n\n"
                    last_keepalive = now
                await asyncio.sleep(0.05)
    finally:
        await bus.unsubscribe(queue)


# ─── Endpoints ────────────────────────────────────────────────────────────────

# ── Liveness ──────────────────────────────────────────────────────────────────

@app.get("/healthz", tags=["system"])
async def healthz() -> dict[str, Any]:
    """Liveness probe — always returns 200."""
    return {
        "status": "ok",
        "parquet_exists": PARQUET_PATH.exists(),
        "cached_rows": gateway.row_count,
        "refresh_interval_ms": REFRESH_INTERVAL_S * 1000,
        "timestamp_ms": int(time.time() * 1000),
    }


# ── User-specified endpoints ───────────────────────────────────────────────────

@app.get("/api/telemetry", tags=["raw"])
async def api_telemetry() -> dict[str, Any]:
    """
    Latest row from simulation_results.parquet.
    Returns the most recently written Parquet record as a plain JSON object.
    Falls back to demo values if the file is unavailable.
    """
    rows = gateway.latest_rows(1)
    if rows:
        return rows[0]

    # Demo fallback
    return {
        "prompt_id": 0,
        "category": "standard",
        "entropy_score": 5,
        "ffi_overhead_ms": 0.75,
        "onnx_latency_ms": 7.90,
        "total_latency_ms": 9.87,
        "tokens_generated": 2,
        "cloud_cost_usd": 0.00006,
        "local_cost_usd": 0.0000076,
        "aei": 0.0000045,
        "sla_breach": False,
        "timestamp": time.time(),
    }


@app.get("/api/stream", tags=["raw"])
async def api_stream(request: Request) -> StreamingResponse:
    """
    SSE stream of raw Parquet rows.
    Emits a JSON-serialised row for every new record written by the simulation
    engine. Clients should reconnect on error (EventSource does this by default).
    """
    return StreamingResponse(
        _sse_generator(raw_row_bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ── Frontend dashboard endpoints ───────────────────────────────────────────────

@app.get("/api/v1/metrics/live", response_model=LiveMetrics, tags=["dashboard"])
async def metrics_live() -> LiveMetrics:
    """
    Aggregate live metrics for the MetricHero component (polled every 500ms).
    Derives capital allocation, delta, volatility, and uptime from Parquet data.
    """
    return _compute_live_metrics(gateway.all_rows())


@app.get("/api/v1/assets/prices", response_model=list[AssetPrice], tags=["dashboard"])
async def assets_prices() -> list[AssetPrice]:
    """
    Asset price snapshot for the AssetMatrix component (polled every 1000ms).
    Prices are derived from base values with AEI-driven micro-drift.
    """
    return _compute_asset_prices(gateway.all_rows())


@app.get("/api/v1/sla/timeseries", response_model=SlaTimeseries, tags=["dashboard"])
async def sla_timeseries() -> SlaTimeseries:
    """
    16-bar SLA timeseries for the SlaMonitor component (polled every 1000ms).
    Bar heights are derived from recent latency measurements.
    """
    return _compute_sla_timeseries(gateway.all_rows())


@app.get("/api/v1/transactions/stream", tags=["dashboard"])
async def transactions_stream(request: Request) -> StreamingResponse:
    """
    SSE stream of Transaction events for the DataLedger component.
    Each event contains a serialised Transaction JSON object.
    """
    return StreamingResponse(
        _sse_generator(tx_bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/telemetry/nodes", response_model=TelemetryNodes, tags=["dashboard"])
async def telemetry_nodes() -> TelemetryNodes:
    """
    Global node telemetry for the TelemetryMap component (polled every 5000ms).
    Regional latencies are derived from recent FFI and ONNX measurements.
    """
    return _compute_telemetry_nodes(gateway.all_rows())


@app.get("/api/v1/events/stream", tags=["dashboard"])
async def events_stream(request: Request) -> StreamingResponse:
    """
    SSE stream of TickerEvent objects for the TickerTape component.
    Events are derived from SLA breaches, high-AEI captures, and threat vectors.
    """
    return StreamingResponse(
        _sse_generator(events_bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=GATEWAY_PORT,
        loop="uvloop",
        http="httptools",
        log_level=LOG_LEVEL.lower(),
        access_log=True,
        reload=False,
    )
