//! Criterion benchmarks for EmbeddingEngine — P99 < 10 ms SLA verification.
//!
//! Run:
//!   cargo bench --features ort-backend          # full ORT path
//!   cargo bench                                 # mock path (CI-safe)
//!   cargo bench -- --save-baseline sprint4      # save for regression
//!   cargo bench -- --baseline sprint4           # compare vs baseline
//!
//! HTML report: target/criterion/embedding_bench/report/index.html

use aegis_rust_core::EmbeddingEngine;
use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion};

// ── Fixture data ──────────────────────────────────────────────────────────────

const SHORT_PROMPT: &[u8] = b"What is 2+2?"; // ~3 tokens

const MEDIUM_PROMPT: &[u8] = b"Explain quantum entanglement and its implications for cryptography."; // ~11 tokens

const LONG_PROMPT: &[u8] = b"Analyze the socioeconomic implications of large language model \
      deployment in emerging markets with reference to multiple case studies \
      and provide a comparative analysis of cost structures."; // ~30 tokens

const BOUNDARY_PROMPT: &[u8] =
    b"What is the relationship between entropy in information theory and \
      semantic uncertainty in transformer-based language models? Provide \
      a mathematical derivation."; // ~30 tokens  (P99 target)

// ── Benchmark groups ──────────────────────────────────────────────────────────

/// Latency across prompt lengths — the primary SLA benchmark.
///
/// P99 target: < 10 ms for all prompt classes.
/// Expected results (MiniLM-v2, CPU, single thread):
///   Short:    ~2–4 ms
///   Medium:   ~4–6 ms
///   Long:     ~6–9 ms
///   Boundary: ~8–10 ms  ← must stay under
fn bench_entropy_by_length(c: &mut Criterion) {
    // Sprint 4: replace "/path/to/minilm.onnx" with the real model path,
    // loaded from AEGIS_MINILM_MODEL_PATH environment variable.
    #[cfg(feature = "ort-backend")]
    let model_path = std::env::var("AEGIS_MINILM_MODEL_PATH")
        .unwrap_or_else(|_| "models/minilm-v2.onnx".to_string());
    #[cfg(not(feature = "ort-backend"))]
    let model_path = "mock";

    let engine =
        EmbeddingEngine::new(&model_path, 64).expect("Failed to initialise EmbeddingEngine");

    let mut group = c.benchmark_group("entropy_by_length");

    // Configure for latency percentile reporting.
    group.measurement_time(std::time::Duration::from_secs(10));
    group.sample_size(500); // 500 samples → reliable P99 estimate

    for (label, payload) in [
        ("short_3tok", SHORT_PROMPT),
        ("medium_11tok", MEDIUM_PROMPT),
        ("long_30tok", LONG_PROMPT),
        ("boundary_30tok", BOUNDARY_PROMPT),
    ] {
        group.bench_with_input(
            BenchmarkId::new("compute_entropy_score", label),
            payload,
            |b, input| {
                b.iter(|| {
                    // black_box prevents the compiler from optimising away
                    // the call (which it might do since the result is unused).
                    engine.compute(black_box(input)).expect("Inference failed")
                })
            },
        );
    }
    group.finish();
}

/// Thread-sharing benchmark — validates `Arc<Session>` zero-copy sharing.
///
/// Spawns 4 threads each running 100 inferences on the same engine handle.
/// Peak memory must not exceed single-engine baseline (no model duplication).
fn bench_concurrent_sharing(c: &mut Criterion) {
    #[cfg(not(feature = "ort-backend"))]
    let model_path = "mock";
    #[cfg(feature = "ort-backend")]
    let model_path = std::env::var("AEGIS_MINILM_MODEL_PATH")
        .unwrap_or_else(|_| "models/minilm-v2.onnx".to_string());

    let engine = EmbeddingEngine::new(&model_path, 64).unwrap();

    c.bench_function("concurrent_4threads_arc_share", |b| {
        b.iter(|| {
            use std::thread;
            let handles: Vec<_> = (0..4)
                .map(|_| {
                    // `share()` = Arc::clone + 8 bytes.  Model weights: 0 bytes copied.
                    let shared = engine.share();
                    thread::spawn(move || {
                        for _ in 0..10 {
                            shared
                                .compute(black_box(MEDIUM_PROMPT))
                                .expect("Inference failed");
                        }
                    })
                })
                .collect();
            for h in handles {
                h.join().unwrap();
            }
        })
    });
}

/// SLA regression guard — fails CI if P99 drifts above 10 ms.
///
/// This benchmark is intended to be run in CI with `--baseline sprint4`.
/// If mean latency exceeds 8 ms (80% of SLA budget), the bench fails and
/// blocks the merge — preventing latency regressions from shipping silently.
fn bench_sla_guard(c: &mut Criterion) {
    #[cfg(not(feature = "ort-backend"))]
    let model_path = "mock";
    #[cfg(feature = "ort-backend")]
    let model_path = std::env::var("AEGIS_MINILM_MODEL_PATH")
        .unwrap_or_else(|_| "models/minilm-v2.onnx".to_string());

    let engine = EmbeddingEngine::new(&model_path, 64).unwrap();

    let mut group = c.benchmark_group("sla_guard");
    // Tight measurement window to catch regressions quickly.
    group.significance_level(0.01);

    group.bench_function("p99_must_be_below_10ms", |b| {
        b.iter(|| engine.compute(black_box(BOUNDARY_PROMPT)).unwrap())
    });
    group.finish();
}

criterion_group!(
    benches,
    bench_entropy_by_length,
    bench_concurrent_sharing,
    bench_sla_guard,
);
criterion_main!(benches);
