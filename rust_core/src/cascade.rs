//! Cascading dual-model ONNX engine — fast (INT8 MiniLM) + optional quality path.
//!
//! Tier semantics (dashboard / FinOps metaphor):
//!   * Sentinel — fast path only; first-layer score sufficiently confident.
//!   * Scholar  — quality ONNX ran; post-calibration uncertainty below monarch band.
//!   * Monarch  — quality ONNX ran; residual ambiguity still high (supreme scrutiny).

#![deny(clippy::clone_on_ref_ptr)]
#![allow(clippy::useless_conversion)] // PyO3 `#[pyfunction]` + `PyResult` triggers false positives (rustc 1.94).

use pyo3::{buffer::PyBuffer, exceptions::PyBufferError, prelude::*};
use std::sync::atomic::{AtomicU64, Ordering};
use tracing::{instrument, warn};

#[cfg(feature = "ort-backend")]
use {
    crate::embedding::{build_session_pool, run_inference_on_pool, tokenize_for_engine},
    tokenizers::Tokenizer,
};

// ── Ambiguity (uncertainty) proxy ─────────────────────────────────────────────

/// Values in [0, 1].  Peaks at 1.0 when `score == 0.5` (maximally ambiguous).
#[inline]
fn ambiguity(score: f32) -> f32 {
    (1.0_f32 - (2.0_f32 * (score - 0.5_f32).abs())).clamp(0.0, 1.0)
}

// ── Model registry ───────────────────────────────────────────────────────────

#[cfg(feature = "ort-backend")]
pub struct ModelRegistry {
    pub fast: std::sync::Arc<crate::embedding::SessionPool>,
    pub quality: Option<std::sync::Arc<crate::embedding::SessionPool>>,
}

#[cfg(feature = "ort-backend")]
impl ModelRegistry {
    pub fn new(fast_path: &str, quality_path: Option<&str>, num_sessions: usize) -> PyResult<Self> {
        let fast = build_session_pool(fast_path, num_sessions)?;
        let quality = if let Some(qp) = quality_path {
            if qp.is_empty() {
                None
            } else if std::path::Path::new(qp).is_file() {
                Some(build_session_pool(qp, num_sessions)?)
            } else {
                warn!("Quality ONNX path does not exist ({qp}); cascading quality path disabled.");
                None
            }
        } else {
            None
        };
        Ok(Self { fast, quality })
    }
}

// ── Tier counters ─────────────────────────────────────────────────────────────

#[derive(Default)]
pub struct CascadeMetrics {
    pub sentinel: AtomicU64,
    pub scholar: AtomicU64,
    pub monarch: AtomicU64,
}

// ── PyO3 engine ───────────────────────────────────────────────────────────────

#[pyclass]
pub struct CascadingEngine {
    #[cfg(feature = "ort-backend")]
    registry: std::sync::Arc<ModelRegistry>,

    #[cfg(feature = "ort-backend")]
    tokenizer: Option<std::sync::Arc<Tokenizer>>,

    pub max_seq_len: usize,

    uncertainty_trigger: f32,
    monarch_uncertainty: f32,

    metrics: std::sync::Arc<CascadeMetrics>,
}

#[pymethods]
impl CascadingEngine {
    /// `quality_model_path`: empty string or missing file ⇒ fast-only (Sentinel-only path).
    #[new]
    #[pyo3(signature = (
        fast_model_path,
        quality_model_path=None,
        max_seq_len=64,
        tokenizer_path=None,
        num_sessions=4,
        uncertainty_trigger=0.35,
        monarch_uncertainty=0.42,
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        fast_model_path: &str,
        quality_model_path: Option<&str>,
        max_seq_len: usize,
        tokenizer_path: Option<&str>,
        num_sessions: usize,
        uncertainty_trigger: f32,
        monarch_uncertainty: f32,
    ) -> PyResult<Self> {
        #[cfg(feature = "ort-backend")]
        {
            let registry = std::sync::Arc::new(ModelRegistry::new(
                fast_model_path,
                quality_model_path,
                num_sessions,
            )?);

            let tokenizer = if let Some(tok_path) = tokenizer_path {
                match Tokenizer::from_file(tok_path) {
                    Ok(tok) => {
                        tracing::info!(tok_path, "CascadingEngine: tokenizer loaded.");
                        Some(std::sync::Arc::new(tok))
                    }
                    Err(e) => {
                        warn!("CascadingEngine: tokenizer load failed ({tok_path}): {e}");
                        None
                    }
                }
            } else {
                None
            };

            tracing::info!(
                fast_model_path,
                quality = ?quality_model_path,
                num_sessions,
                uncertainty_trigger,
                monarch_uncertainty,
                "[RUST_CASCADE_READY] ModelRegistry initialised."
            );

            Ok(Self {
                registry,
                tokenizer,
                max_seq_len,
                uncertainty_trigger: uncertainty_trigger.clamp(0.0, 1.0),
                monarch_uncertainty: monarch_uncertainty.clamp(0.0, 1.0),
                metrics: std::sync::Arc::new(CascadeMetrics::default()),
            })
        }

        #[cfg(not(feature = "ort-backend"))]
        {
            warn!("ort-backend OFF — CascadingEngine uses mock entropy.");
            Ok(Self {
                max_seq_len,
                uncertainty_trigger: uncertainty_trigger.clamp(0.0, 1.0),
                monarch_uncertainty: monarch_uncertainty.clamp(0.0, 1.0),
                metrics: std::sync::Arc::new(CascadeMetrics::default()),
            })
        }
    }

    /// Arc-share handles — ref-count only; zero copy of weights.
    pub fn share(&self) -> Self {
        #[cfg(feature = "ort-backend")]
        {
            Self {
                registry: std::sync::Arc::clone(&self.registry),
                tokenizer: self.tokenizer.as_ref().map(std::sync::Arc::clone),
                max_seq_len: self.max_seq_len,
                uncertainty_trigger: self.uncertainty_trigger,
                monarch_uncertainty: self.monarch_uncertainty,
                metrics: std::sync::Arc::clone(&self.metrics),
            }
        }
        #[cfg(not(feature = "ort-backend"))]
        {
            Self {
                max_seq_len: self.max_seq_len,
                uncertainty_trigger: self.uncertainty_trigger,
                monarch_uncertainty: self.monarch_uncertainty,
                metrics: std::sync::Arc::clone(&self.metrics),
            }
        }
    }

    pub fn pool_size_fast(&self) -> usize {
        #[cfg(feature = "ort-backend")]
        return self.registry.fast.size();
        #[cfg(not(feature = "ort-backend"))]
        0
    }

    pub fn pool_size_quality(&self) -> usize {
        #[cfg(feature = "ort-backend")]
        return self
            .registry
            .quality
            .as_ref()
            .map(|p| p.size())
            .unwrap_or(0);
        #[cfg(not(feature = "ort-backend"))]
        0
    }

    pub fn has_quality_path(&self) -> bool {
        #[cfg(feature = "ort-backend")]
        return self.registry.quality.is_some();
        #[cfg(not(feature = "ort-backend"))]
        false
    }

    pub fn has_real_tokenizer(&self) -> bool {
        #[cfg(feature = "ort-backend")]
        return self.tokenizer.is_some();
        #[cfg(not(feature = "ort-backend"))]
        false
    }

    /// `(sentinel, scholar, monarch)` cumulative request counts.
    pub fn tier_counts(&self) -> (u64, u64, u64) {
        (
            self.metrics.sentinel.load(Ordering::Relaxed),
            self.metrics.scholar.load(Ordering::Relaxed),
            self.metrics.monarch.load(Ordering::Relaxed),
        )
    }

    pub fn reset_tier_counts(&self) {
        self.metrics.sentinel.store(0, Ordering::Relaxed);
        self.metrics.scholar.store(0, Ordering::Relaxed);
        self.metrics.monarch.store(0, Ordering::Relaxed);
    }
}

impl CascadingEngine {
    #[cfg(feature = "ort-backend")]
    #[instrument(skip(self, input_bytes), fields(len = input_bytes.len()))]
    pub fn compute(&self, input_bytes: &[u8]) -> Result<f32, Box<dyn std::error::Error>> {
        let text = std::str::from_utf8(input_bytes)?;
        let (ids, mask, types) = tokenize_for_engine(&self.tokenizer, text, self.max_seq_len)?;

        let s1 = run_inference_on_pool(&self.registry.fast, &ids, &mask, &types)?;
        let u1 = ambiguity(s1);

        let q = match &self.registry.quality {
            Some(p) => p,
            None => {
                self.metrics.sentinel.fetch_add(1, Ordering::Relaxed);
                return Ok(s1);
            }
        };

        if u1 < self.uncertainty_trigger {
            self.metrics.sentinel.fetch_add(1, Ordering::Relaxed);
            return Ok(s1);
        }

        let s2 = run_inference_on_pool(q, &ids, &mask, &types)?;
        let u2 = ambiguity(s2);
        if u2 >= self.monarch_uncertainty {
            self.metrics.monarch.fetch_add(1, Ordering::Relaxed);
        } else {
            self.metrics.scholar.fetch_add(1, Ordering::Relaxed);
        }
        Ok(s2)
    }

    #[cfg(not(feature = "ort-backend"))]
    pub fn compute(&self, input_bytes: &[u8]) -> Result<f32, Box<dyn std::error::Error>> {
        let text = std::str::from_utf8(input_bytes)?;
        let _ = self.max_seq_len;
        self.metrics.sentinel.fetch_add(1, Ordering::Relaxed);
        Ok(crate::embedding::mock_entropy_text(text))
    }
}

#[pyfunction]
#[instrument(skip(py, engine, input_buf))]
pub fn compute_cascade_entropy_score(
    py: Python<'_>,
    engine: &CascadingEngine,
    input_buf: PyBuffer<u8>,
) -> PyResult<f32> {
    let cell_slice = input_buf.as_slice(py).ok_or_else(|| {
        PyBufferError::new_err("Input must be C-contiguous buffer (bytes / bytearray / memoryview)")
    })?;
    let bytes: &[u8] =
        unsafe { std::slice::from_raw_parts(cell_slice.as_ptr() as *const u8, cell_slice.len()) };
    engine
        .compute(bytes)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}
