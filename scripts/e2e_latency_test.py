#!/usr/bin/env python3
"""
Aegis V2 — End-to-End Latency Benchmark
────────────────────────────────────────

Measures P50 / P95 / P99 latency for three scenarios:

  1. Direct Rust SEP call   — compute_entropy_score() via PyBuffer<u8>
  2. Async thread path      — asyncio.to_thread() wrapping the Rust call
  3. Full routing chain     — SemanticEntropyProbe → EntropyRouter → decision

Usage:
    AEGIS_MINILM_MODEL_PATH=models/minilm-v2.onnx python scripts/e2e_latency_test.py

Env vars:
    AEGIS_MINILM_MODEL_PATH   path to .onnx model (default: models/minilm-v2.onnx)
    BENCH_N                   number of iterations   (default: 500)
    BENCH_CONCURRENCY         concurrent tasks (async path) (default: 50)
"""
from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_PATH  = os.environ.get("AEGIS_MINILM_MODEL_PATH", "models/minilm-v2.onnx")
N           = int(os.environ.get("BENCH_N", "500"))
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "50"))

PROMPTS = [
    b"What is 2+2?",                                             # short factual
    b"Explain the theory of general relativity.",                # medium
    b"Analyze the socioeconomic implications of large language " # long / complex
    b"model deployment in emerging markets with references to "
    b"multiple case studies and provide a comparative analysis.",
    b"How does gradient descent work in neural networks?",
    b"What is the capital of France?",
    b"Describe the ACID properties of database transactions.",
    b"Explain quantum entanglement and its role in computing.",
    b"What causes inflation and how can it be controlled?",
]


# ── Statistics helper ─────────────────────────────────────────────────────────

def _report(name: str, latencies_ms: list[float]) -> None:
    lat = sorted(latencies_ms)
    p50  = statistics.median(lat)
    p95  = lat[int(len(lat) * 0.95)]
    p99  = lat[int(len(lat) * 0.99)]
    mean = statistics.mean(lat)
    tput = 1000 / mean if mean > 0 else 0
    sla  = "✅ PASS" if p99 < 10.0 else "❌ FAIL (> 10 ms)"

    bar_p99 = "█" * min(int(p99 / 0.5), 40)  # 0.5ms per block

    print(f"\n  ┌─ {name}")
    print(f"  │  samples   : {len(lat):,}")
    print(f"  │  mean      : {mean:7.3f} ms")
    print(f"  │  P50       : {p50:7.3f} ms")
    print(f"  │  P95       : {p95:7.3f} ms")
    print(f"  │  P99       : {p99:7.3f} ms   {sla}")
    print(f"  │  throughput: {tput:,.0f} req/s (single-thread estimate)")
    print(f"  └─ P99 bar   : [{bar_p99:<40}]")


# ── Benchmark 1: direct Rust FFI call (synchronous) ──────────────────────────

def bench_direct_rust(engine, compute_fn) -> list[float]:
    """Measures raw PyBuffer<u8> → Rust ONNX → f32 round-trip."""
    latencies = []
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(N)]

    # Warmup
    for p in prompts[:20]:
        compute_fn(engine, p)

    for p in prompts:
        t0 = time.perf_counter()
        compute_fn(engine, p)
        latencies.append((time.perf_counter() - t0) * 1000)

    return latencies


# ── Benchmark 2: asyncio.to_thread path ──────────────────────────────────────

async def bench_async_thread(engine, compute_fn) -> list[float]:
    """
    Simulates production usage: ASGI event loop dispatches to thread pool.
    Each call = asyncio.to_thread() → Rust inference.
    Concurrency = CONCURRENCY concurrent tasks at a time.
    """
    sem = asyncio.Semaphore(CONCURRENCY)
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(N)]

    # Warmup
    for p in prompts[:20]:
        await asyncio.to_thread(compute_fn, engine, p)

    async def one(p: bytes) -> float:
        async with sem:
            t0 = time.perf_counter()
            await asyncio.to_thread(compute_fn, engine, p)
            return (time.perf_counter() - t0) * 1000

    return await asyncio.gather(*[one(p) for p in prompts])


# ── Benchmark 3: full routing chain ──────────────────────────────────────────

def bench_routing_chain(probe) -> list[float]:
    """
    Full SemanticEntropyProbe.calculate() → routing decision.
    Exercises the __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ path.
    """
    prompts_str = [p.decode() for p in PROMPTS]
    latencies = []
    all_prompts = [prompts_str[i % len(prompts_str)] for i in range(N)]

    # Warmup
    for p in all_prompts[:20]:
        probe.calculate(p)

    for p in all_prompts:
        t0 = time.perf_counter()
        probe.calculate(p)
        latencies.append((time.perf_counter() - t0) * 1000)

    return latencies


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 70)
    print("  Aegis V2 — Rust ONNX SEP Latency Benchmark")
    print(f"  Model : {MODEL_PATH}")
    print(f"  N     : {N:,} iterations   concurrency={CONCURRENCY}")
    print("=" * 70)

    # ── Check model path ──────────────────────────────────────────────────────
    if not Path(MODEL_PATH).exists():
        print(f"\nERROR: Model not found: {MODEL_PATH}")
        print("  Run: python scripts/create_dummy_model.py")
        return 1

    # ── Import Rust module ────────────────────────────────────────────────────
    try:
        import aegis_rust_core
        from aegis_rust_core import EmbeddingEngine, compute_entropy_score
        rust_available = True
        print(f"\n[RUST_CORE_READY]  aegis_rust_core loaded successfully")
    except ImportError as exc:
        print(f"\n[RUST_CORE_MISSING]  {exc}")
        print("  Run: cd rust_core && maturin develop --release --features ort-backend,extension-module")
        rust_available = False

    from app.routing.entropy import SemanticEntropyProbe

    if rust_available:
        # ── Load ONNX model ───────────────────────────────────────────────────
        print(f"\n  Loading EmbeddingEngine from {MODEL_PATH} ...")
        t0 = time.perf_counter()
        try:
            engine = EmbeddingEngine(MODEL_PATH, 64)
        except RuntimeError as exc:
            print(f"  ERROR loading model: {exc}")
            return 1
        load_ms = (time.perf_counter() - t0) * 1000
        print(f"  Model loaded in {load_ms:.0f} ms")

        # ── Benchmark 1: direct Rust ──────────────────────────────────────────
        print("\n  Running Benchmark 1: Direct Rust FFI (synchronous) ...")
        lat1 = bench_direct_rust(engine, compute_entropy_score)
        _report("Direct Rust FFI (PyBuffer<u8> → ORT → f32)", lat1)

        # ── Benchmark 2: async thread path ───────────────────────────────────
        print(f"\n  Running Benchmark 2: asyncio.to_thread (concurrency={CONCURRENCY}) ...")
        lat2 = asyncio.run(bench_async_thread(engine, compute_entropy_score))
        _report(f"asyncio.to_thread → Rust (concurrency={CONCURRENCY})", lat2)

        # ── Routing probe with Rust backend ──────────────────────────────────
        probe_rust = SemanticEntropyProbe(rust_engine=engine)
        print("\n  Running Benchmark 3: Full Routing Chain (Rust SEP + decision) ...")
        lat3 = bench_routing_chain(probe_rust)
        _report("SemanticEntropyProbe + routing decision (Rust backend)", lat3)

    # ── Benchmark: Python mock for comparison ─────────────────────────────────
    probe_mock = SemanticEntropyProbe(rust_engine=None)
    print("\n  Running Benchmark 4: Python Mock Probe (baseline comparison) ...")
    lat4 = bench_routing_chain(probe_mock)
    _report("SemanticEntropyProbe (Python bigram mock, no Rust)", lat4)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    if rust_available:
        rust_mean = statistics.mean(lat1)
        mock_mean = statistics.mean(lat4)
        overhead  = rust_mean - mock_mean
        print(f"  Rust ORT mean     : {rust_mean:.3f} ms")
        print(f"  Python mock mean  : {mock_mean:.3f} ms")
        print(f"  ONNX overhead     : {overhead:.3f} ms  "
              f"({'within' if overhead < 10 else 'EXCEEDS'} 10 ms SLA budget)")
    print(f"\n  P99 SLA target    : < 10.00 ms")
    if rust_available:
        p99_rust = sorted(lat1)[int(len(lat1) * 0.99)]
        verdict = "✅  PASS" if p99_rust < 10 else "❌  FAIL — requires optimisation"
        print(f"  P99 achieved      : {p99_rust:.3f} ms  →  {verdict}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
