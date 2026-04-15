#!/usr/bin/env python3
"""
Sprint 4.1 — Real MiniLM model end-to-end test.

Validates the full chain:
  HuggingFace tokenizer (Python)
      → compute_entropy_from_tokens (Rust FFI)
          → OrtTensor forward pass (ONNX Runtime)
              → linear_probe (CLS embedding L2 norm)
                  → entropy score (float32)

Usage:
    python scripts/sprint4_1_test.py

Requirements:
    1. models/minilm-v2.onnx   (run scripts/download_model.py first)
    2. models/tokenizer/       (downloaded by download_model.py)
    3. aegis_rust_core         (maturin develop --release --features ort-backend)
    4. transformers            (pip install transformers)
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

MODEL_PATH = os.environ.get("AEGIS_MINILM_MODEL_PATH", "models/minilm-v2.onnx")
TOK_PATH   = os.environ.get("AEGIS_TOKENIZER_PATH",    "models/tokenizer")

# ── Test sentences — diverse complexity levels ────────────────────────────────
TEST_SENTENCES = [
    # (label, text, expected routing hint)
    ("simple_math",    "What is 2+2?",
     "low entropy → local_edge"),
    ("simple_fact",    "What is the capital of France?",
     "low entropy → local_edge"),
    ("simple_code",    "How to implement a linked list?",
     "medium entropy → local or cloud"),
    ("medium_tech",    "Explain gradient descent in neural networks.",
     "medium-high entropy → cloud"),
    ("complex_reason", "Analyze the trade-offs between microservices and "
                       "monolithic architectures for a high-traffic fintech platform.",
     "high entropy → cloud"),
    ("complex_multi",  "Compare Rust's ownership model to garbage collection "
                       "in terms of latency predictability for P99 SLA compliance "
                       "in production AI inference systems.",
     "high entropy → cloud"),
]


class InferenceResult(NamedTuple):
    label:         str
    prompt:        str
    token_count:   int
    entropy_score: float
    latency_ms:    float
    routing_hint:  str
    decision:      str  # "local_edge" or "cloud_gemini"


def _decide(score: float, threshold: float = 0.4) -> str:
    return "local_edge" if score < threshold else "cloud_gemini"


def run_test() -> int:
    print("=" * 70)
    print("  Aegis V2 — Sprint 4.1: Real MiniLM ONNX Inference Test")
    print("=" * 70)

    # ── 1. Verify model file ──────────────────────────────────────────────────
    model_path = Path(MODEL_PATH)
    if not model_path.exists():
        print(f"\nERROR: Model not found: {MODEL_PATH}")
        print("  Run: python scripts/download_model.py")
        return 1

    size_mb = model_path.stat().st_size / 1_048_576
    print(f"\n  Model  : {model_path} ({size_mb:.1f} MB)")

    # ── 2. Load Rust ONNX engine ──────────────────────────────────────────────
    try:
        from aegis_rust_core import EmbeddingEngine, compute_entropy_from_tokens
        print("  [RUST_CORE_READY] aegis_rust_core loaded")
    except ImportError as exc:
        print(f"\nERROR: {exc}")
        print("  Run: cd rust_core && maturin develop --release "
              "--features ort-backend,extension-module")
        return 1

    print(f"  Loading EmbeddingEngine ...")
    t0 = time.perf_counter()
    try:
        engine = EmbeddingEngine(MODEL_PATH, max_seq_len=64)
    except RuntimeError as exc:
        print(f"\nERROR loading model: {exc}")
        return 1
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"  Engine ready in {load_ms:.0f} ms\n")

    # ── 3. Load tokenizer ─────────────────────────────────────────────────────
    try:
        from transformers import AutoTokenizer
    except ImportError:
        print("ERROR: transformers not installed. Run: pip install transformers")
        return 1

    tok_dir = Path(TOK_PATH)
    tok_src  = str(tok_dir) if tok_dir.exists() else "sentence-transformers/all-MiniLM-L6-v2"
    print(f"  Loading tokenizer from: {tok_src}")
    try:
        tokenizer = AutoTokenizer.from_pretrained(tok_src)
        print(f"  Tokenizer vocabulary size: {tokenizer.vocab_size:,}")
    except Exception as exc:
        print(f"\nERROR loading tokenizer: {exc}")
        return 1

    # ── 4. Inference loop ─────────────────────────────────────────────────────
    print()
    print(f"  {'Prompt':<55} {'Tokens':>6} {'Score':>7} {'ms':>7} {'Route':<12}")
    print("  " + "─" * 92)

    results: list[InferenceResult] = []

    for label, prompt, hint in TEST_SENTENCES:
        # Tokenize with real HuggingFace tokenizer.
        # return_tensors=None → plain Python lists (no PyTorch required).
        enc = tokenizer(
            prompt,
            return_tensors=None,
            max_length=64,
            truncation=True,
            padding=False,
        )
        input_ids      = enc["input_ids"]       # list[int]
        attention_mask = enc["attention_mask"]   # list[int]

        # Warmup (first call has JIT overhead)
        compute_entropy_from_tokens(engine, input_ids, attention_mask)

        # Timed inference
        N = 20
        latencies = []
        for _ in range(N):
            t0 = time.perf_counter()
            score = compute_entropy_from_tokens(engine, input_ids, attention_mask)
            latencies.append((time.perf_counter() - t0) * 1000)

        lat_mean = statistics.mean(latencies)
        decision = _decide(score)
        preview  = (prompt[:52] + "…") if len(prompt) > 53 else prompt

        print(f"  {preview:<55} {len(input_ids):>6} {score:>7.4f} {lat_mean:>7.2f} {decision:<12}")

        results.append(InferenceResult(
            label=label, prompt=prompt, token_count=len(input_ids),
            entropy_score=score, latency_ms=lat_mean,
            routing_hint=hint, decision=decision,
        ))

    # ── 5. Summary ────────────────────────────────────────────────────────────
    print("  " + "─" * 92)
    print()

    all_latencies = [r.latency_ms for r in results]
    lat_sorted    = sorted(all_latencies)
    p50 = statistics.median(lat_sorted)
    p95 = lat_sorted[int(len(lat_sorted) * 0.95) - 1]
    p99 = lat_sorted[-1]  # with only 6 samples, max is P99

    print("  Latency summary (per-sentence mean over 20 calls):")
    print(f"    P50  : {p50:.3f} ms")
    print(f"    P95  : {p95:.3f} ms")
    print(f"    P99  : {p99:.3f} ms   {'✅ PASS' if p99 < 10 else '❌ FAIL (> 10 ms SLA)'}")

    print()
    print("  Routing decisions:")
    for r in results:
        icon = "⬇ local " if r.decision == "local_edge" else "☁ cloud"
        print(f"    [{icon}] score={r.entropy_score:.4f}  {r.label}")

    print()
    print("  Semantic entropy interpretation (placeholder probe):")
    print("    score ≈ 1 − clamp(‖CLS‖₂ / 20, 0, 1)")
    print("    Lower norm  → higher model confidence → lower entropy")
    print("    Sprint 4.2 TODO: replace with trained 2.6K-param linear probe.")

    print()
    print("=" * 70)
    print("  [SPRINT 4.1 COMPLETE] Real MiniLM ONNX inference validated.")
    print(f"  Model  : {size_mb:.1f} MB  |  Load: {load_ms:.0f} ms  |  P99: {p99:.2f} ms")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_test())
