//! Re-export Criterion with Antigravity defaults.

pub use criterion::{criterion_group, criterion_main, Criterion};

/// Tighter sample size for CI-friendly benches.
pub fn criterion_quick() -> Criterion {
    Criterion::default().sample_size(20)
}
