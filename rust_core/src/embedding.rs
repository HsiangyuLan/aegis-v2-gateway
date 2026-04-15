//! MiniLM ONNX inference engine — Sprint 4.2: Session Pool + Real Tokenizer.
//!
//! ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//! Architecture: Lock-eliminated Session Pool
//! ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//!
//! Sprint 4.1: Arc<Mutex<Session>>
//!   All concurrent callers serialise through ONE mutex.
//!   At 50 concurrent asyncio.to_thread() calls, wait time = N × inference_ms.
//!
//! Sprint 4.2: Arc<SessionPool> with Vec<Mutex<Session>>
//!   N independent sessions (one per CPU core by default).
//!   Round-robin with lock-stealing: concurrent callers get different sessions.
//!   Mutex held ONLY during ORT forward pass (~2–15 ms).
//!   Contention drops from O(N) to O(1) for N ≤ pool_size threads.
//!
//! ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//! Memory ownership
//! ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//!
//!  Arc<SessionPool>        — shared across all EmbeddingEngine handles (0 copy)
//!    └ Vec<Mutex<Session>> — N sessions; mutex held only during run()
//!
//!  Arc<tokenizers::Tokenizer> — read-only; Sync; shared without mutex
//!
//!  &[u8] / &[i64]            — borrowed from Python; zero-copy across FFI
//!
//! No clone() on payloads.  Arc::clone() = 8-byte ref-count increment only.

#![deny(clippy::clone_on_ref_ptr)]

use pyo3::{prelude::*, PyErr};
use tracing::{debug, instrument, warn};

#[cfg(feature = "ort-backend")]
use {
    ndarray::Array2,
    ort::{
        inputs,
        session::{builder::GraphOptimizationLevel, Session},
        value::Tensor as OrtTensor,
    },
    std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex, MutexGuard,
    },
    tokenizers::Tokenizer,
};

// ── Session Pool ──────────────────────────────────────────────────────────────

/// N independent ORT sessions with round-robin + lock-stealing assignment.
///
/// Why not a single `Arc<Mutex<Session>>`?
/// A single mutex serialises ALL concurrent callers.  With 50 concurrent
/// asyncio.to_thread() calls and 5 ms inference each, the last caller waits
/// 50 × 5 ms = 250 ms.  With a pool of N sessions, callers fan out and the
/// wait time drops to ~(50/N) × 5 ms.
#[cfg(feature = "ort-backend")]
pub(crate) struct SessionPool {
    sessions: Vec<Mutex<Session>>,
    round_robin: AtomicUsize,
}

#[cfg(feature = "ort-backend")]
impl SessionPool {
    fn new(sessions: Vec<Session>) -> Self {
        Self {
            sessions: sessions.into_iter().map(Mutex::new).collect(),
            round_robin: AtomicUsize::new(0),
        }
    }

    /// Acquire a session with lock-stealing.
    ///
    /// 1. Pick a session via round-robin (atomic, no lock).
    /// 2. `try_lock` on that session.  If free → return immediately.
    /// 3. If busy → try the next session (lock-stealing).
    /// 4. If all busy → block on the original round-robin slot.
    ///
    /// Expected path for N threads ≤ pool_size: step 2 succeeds in O(1).
    fn acquire(&self) -> MutexGuard<'_, Session> {
        let n = self.sessions.len();
        let start = self.round_robin.fetch_add(1, Ordering::Relaxed) % n;

        for i in 0..n {
            let idx = (start + i) % n;
            if let Ok(guard) = self.sessions[idx].try_lock() {
                return guard;
            }
        }
        // All busy: block on the originally assigned slot.
        self.sessions[start].lock().expect("Session mutex poisoned")
    }

    pub(crate) fn size(&self) -> usize {
        self.sessions.len()
    }
}

/// Build N ORT sessions for one ONNX file (shared by ``EmbeddingEngine`` and ``CascadingEngine``).
#[cfg(feature = "ort-backend")]
pub(crate) fn build_session_pool(
    model_path: &str,
    num_sessions: usize,
) -> PyResult<Arc<SessionPool>> {
    let n = num_sessions.max(1);
    let mut sessions = Vec::with_capacity(n);
    for i in 0..n {
        let sess = Session::builder()
            .map_err(ort_err)?
            .with_optimization_level(GraphOptimizationLevel::Level3)
            .map_err(ort_err)?
            .with_intra_threads(1)
            .map_err(ort_err)?
            .commit_from_file(model_path)
            .map_err(ort_err)?;
        sessions.push(sess);
        debug!("Session {} of {} ready.", i + 1, n);
    }
    Ok(Arc::new(SessionPool::new(sessions)))
}

/// Tokenize once; reused by cascade fast + quality paths (same token tensors).
#[cfg(feature = "ort-backend")]
#[allow(clippy::type_complexity)]
pub(crate) fn tokenize_for_engine(
    tokenizer: &Option<Arc<Tokenizer>>,
    text: &str,
    max_seq_len: usize,
) -> Result<(Vec<i64>, Vec<i64>, Vec<i64>), Box<dyn std::error::Error>> {
    if let Some(tok) = tokenizer {
        let enc = tok.encode(text, true).map_err(|e| e.to_string())?;
        let max = max_seq_len;
        let ids: Vec<i64> = enc.get_ids().iter().take(max).map(|&x| x as i64).collect();
        let mask: Vec<i64> = enc
            .get_attention_mask()
            .iter()
            .take(max)
            .map(|&x| x as i64)
            .collect();
        let types: Vec<i64> = enc
            .get_type_ids()
            .iter()
            .take(max)
            .map(|&x| x as i64)
            .collect();
        Ok((ids, mask, types))
    } else {
        let ids = tokenise_placeholder(text, max_seq_len);
        let n = ids.len();
        Ok((ids, vec![1i64; n], vec![0i64; n]))
    }
}

/// Run forward on a pool; mutex scope = single ``run()`` only.
#[cfg(feature = "ort-backend")]
pub(crate) fn run_inference_on_pool(
    pool: &SessionPool,
    input_ids: &[i64],
    attention_mask: &[i64],
    token_type_ids: &[i64],
) -> Result<f32, Box<dyn std::error::Error>> {
    if input_ids.is_empty() {
        return Ok(0.0);
    }
    let seq_len = input_ids.len();
    let ids_arr = Array2::from_shape_vec([1, seq_len], input_ids.to_vec())?;
    let mask_arr = Array2::from_shape_vec([1, seq_len], attention_mask.to_vec())?;
    let type_arr = Array2::from_shape_vec([1, seq_len], token_type_ids.to_vec())?;

    let mut session_guard = pool.acquire();
    let outputs = session_guard.run(inputs![
        "input_ids"      => OrtTensor::from_array(ids_arr).map_err(ort_err)?,
        "attention_mask" => OrtTensor::from_array(mask_arr).map_err(ort_err)?,
        "token_type_ids" => OrtTensor::from_array(type_arr).map_err(ort_err)?,
    ])?;

    let (shape, flat_data) = outputs[0].try_extract_tensor::<f32>()?;
    let hidden_dim = *shape.last().ok_or("empty output shape")? as usize;
    let cls: &[f32] = &flat_data[..hidden_dim.min(flat_data.len())];
    Ok(linear_probe(cls))
}

// ── Engine struct ─────────────────────────────────────────────────────────────

#[pyclass]
pub struct EmbeddingEngine {
    pub max_seq_len: usize,

    #[cfg(feature = "ort-backend")]
    pool: Arc<SessionPool>,

    /// Real HuggingFace tokenizer (loaded from tokenizer.json).
    /// `Tokenizer` is Sync, so Arc without Mutex suffices.
    /// `None` when no tokenizer path was provided → fallback to placeholder.
    #[cfg(feature = "ort-backend")]
    tokenizer: Option<Arc<Tokenizer>>,
}

#[pymethods]
impl EmbeddingEngine {
    /// Build the session pool and load the optional real tokenizer.
    ///
    /// # Arguments
    /// * `model_path`      — path to the `.onnx` model file
    /// * `max_seq_len`     — token truncation limit (default 64)
    /// * `tokenizer_path`  — path to `tokenizer.json` (default None → placeholder)
    /// * `num_sessions`    — session pool size (default 4 = typical CPU core count)
    #[new]
    #[pyo3(signature = (model_path, max_seq_len=64, tokenizer_path=None, num_sessions=4))]
    pub fn new(
        model_path: &str,
        max_seq_len: usize,
        tokenizer_path: Option<&str>,
        num_sessions: usize,
    ) -> PyResult<Self> {
        #[cfg(feature = "ort-backend")]
        {
            let pool = build_session_pool(model_path, num_sessions)?;
            let n = pool.size();
            tracing::info!(
                model_path,
                num_sessions = n,
                max_seq_len,
                "[RUST_CORE_READY] Session pool initialised."
            );

            // ── Load tokenizer ───────────────────────────────────────────────
            let tokenizer = if let Some(tok_path) = tokenizer_path {
                match Tokenizer::from_file(tok_path) {
                    Ok(tok) => {
                        tracing::info!(tok_path, "HuggingFace tokenizer loaded.");
                        Some(Arc::new(tok))
                    }
                    Err(e) => {
                        warn!("Failed to load tokenizer from {tok_path}: {e}. Using placeholder.");
                        None
                    }
                }
            } else {
                None
            };

            Ok(Self {
                pool,
                tokenizer,
                max_seq_len,
            })
        }

        #[cfg(not(feature = "ort-backend"))]
        {
            warn!("ort-backend OFF — EmbeddingEngine returns mock entropy.");
            Ok(Self { max_seq_len })
        }
    }

    /// Clone the Arc handles — zero byte copy of model weights or tokenizer data.
    pub fn share(&self) -> Self {
        #[cfg(feature = "ort-backend")]
        return Self {
            pool: Arc::clone(&self.pool),
            tokenizer: self.tokenizer.as_ref().map(Arc::clone),
            max_seq_len: self.max_seq_len,
        };

        #[cfg(not(feature = "ort-backend"))]
        Self {
            max_seq_len: self.max_seq_len,
        }
    }

    /// Report pool statistics for dashboard / monitoring.
    pub fn pool_size(&self) -> usize {
        #[cfg(feature = "ort-backend")]
        return self.pool.size();

        #[cfg(not(feature = "ort-backend"))]
        0
    }

    pub fn has_real_tokenizer(&self) -> bool {
        #[cfg(feature = "ort-backend")]
        return self.tokenizer.is_some();

        #[cfg(not(feature = "ort-backend"))]
        false
    }
}

// ── Public inference API ──────────────────────────────────────────────────────

impl EmbeddingEngine {
    /// Infer from raw UTF-8 bytes.
    ///
    /// Tokenization path:
    ///   - Real tokenizer available → true WordPiece/BPE (semantically correct)
    ///   - No tokenizer            → placeholder (Sprint 4.1 fallback)
    #[instrument(skip(self, input_bytes), fields(len = input_bytes.len()))]
    pub fn compute(&self, input_bytes: &[u8]) -> Result<f32, Box<dyn std::error::Error>> {
        let text = std::str::from_utf8(input_bytes)?;
        debug!(preview = &text[..text.len().min(60)], "compute() called");

        #[cfg(feature = "ort-backend")]
        return self.infer_ort_text(text);

        #[cfg(not(feature = "ort-backend"))]
        Ok(mock_entropy_text(text))
    }

    /// Infer from pre-tokenized inputs (Python-tokenized path).
    ///
    /// Bypasses the internal tokenizer; use this when calling from Python
    /// with a HuggingFace AutoTokenizer for full control over tokenization.
    #[cfg(feature = "ort-backend")]
    #[instrument(skip(self, input_ids, attention_mask),
                 fields(seq_len = input_ids.len()))]
    pub fn compute_from_tokens(
        &self,
        input_ids: &[i64],
        attention_mask: &[i64],
    ) -> Result<f32, Box<dyn std::error::Error>> {
        if input_ids.is_empty() {
            return Ok(0.0);
        }
        let type_ids = vec![0i64; input_ids.len()];
        self.run_inference(input_ids, attention_mask, &type_ids)
    }
}

// ── ORT forward pass (ort-backend only) ──────────────────────────────────────

#[cfg(feature = "ort-backend")]
impl EmbeddingEngine {
    /// Tokenize text (real or placeholder) then run ORT inference.
    fn infer_ort_text(&self, text: &str) -> Result<f32, Box<dyn std::error::Error>> {
        let (ids, mask, type_ids) = tokenize_for_engine(&self.tokenizer, text, self.max_seq_len)?;
        self.run_inference(&ids, &mask, &type_ids)
    }

    /// Core ORT inference: pool + timing (cascade path uses ``run_inference_on_pool`` directly).
    fn run_inference(
        &self,
        input_ids: &[i64],
        attention_mask: &[i64],
        token_type_ids: &[i64],
    ) -> Result<f32, Box<dyn std::error::Error>> {
        let seq_len = input_ids.len();
        let t0 = std::time::Instant::now();
        let out = run_inference_on_pool(&self.pool, input_ids, attention_mask, token_type_ids)?;
        let elapsed_us = t0.elapsed().as_micros();
        debug!(elapsed_us, seq_len, "ORT inference complete");
        if elapsed_us > 6_000 {
            warn!(elapsed_us, seq_len, "P99 SLA at risk (> 6 ms threshold)");
        }
        Ok(out)
    }
}

// ── Probe / mock ──────────────────────────────────────────────────────────────

/// Norm-based entropy proxy.
///
/// Sprint 4.2 TODO: replace with `sigmoid(w · cls + b)` using a 2.6K-param
/// linear probe trained on labeled {certain, uncertain} query pairs.
/// Current heuristic works as a routing signal but is not calibrated.
#[cfg(feature = "ort-backend")]
pub(crate) fn linear_probe(cls: &[f32]) -> f32 {
    let norm: f32 = cls.iter().map(|&x| x * x).sum::<f32>().sqrt();
    (1.0 - (norm / 20.0_f32).clamp(0.0, 1.0)).clamp(0.0, 1.0)
}

#[cfg(not(feature = "ort-backend"))]
pub(crate) fn mock_entropy_text(text: &str) -> f32 {
    let tokens: Vec<&str> = text.split_whitespace().collect();
    if tokens.len() < 2 {
        return 0.0;
    }
    let unique = tokens
        .windows(2)
        .map(|w| (w[0], w[1]))
        .collect::<std::collections::HashSet<_>>()
        .len();
    let diversity = unique as f32 / (tokens.len() - 1) as f32;
    let length_factor = (1.0 + tokens.len() as f32).ln() / (1.0 + 15.0_f32).ln();
    (diversity * length_factor).clamp(0.0, 1.0)
}

#[cfg(feature = "ort-backend")]
fn tokenise_placeholder(text: &str, max_len: usize) -> Vec<i64> {
    std::iter::once(101i64)
        .chain(
            text.split_whitespace()
                .take(max_len.saturating_sub(2))
                .enumerate()
                .map(|(i, _)| (1000 + i as i64) % 30_522),
        )
        .chain(std::iter::once(102i64))
        .take(max_len)
        .collect()
}

#[cfg(feature = "ort-backend")]
#[inline]
fn ort_err<E: std::fmt::Display>(e: E) -> PyErr {
    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
}
