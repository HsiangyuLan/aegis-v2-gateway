//! Local ONNX NER for entity spans. Disabled when model/tokenizer paths are absent.

use std::path::Path;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};

use ag_error::AgError;
use ag_types::{PiiKind, PiiMatch};
use ndarray::Array2;
use ort::session::{builder::GraphOptimizationLevel, Session, SessionOutputs};
use ort::value::Tensor as OrtTensor;
use ort::inputs;
use tokenizers::Tokenizer;
use tracing::warn;

/// Pool of ORT sessions + shared tokenizer.
pub struct OnnxNerEngine {
    inner: Option<Arc<NerInner>>,
}

struct NerInner {
    sessions: Vec<Mutex<Session>>,
    tokenizer: Tokenizer,
    round_robin: AtomicUsize,
    max_seq_len: usize,
}

impl NerInner {
    fn acquire_session(&self) -> std::sync::MutexGuard<'_, Session> {
        let n = self.sessions.len();
        let i = self.round_robin.fetch_add(1, Ordering::Relaxed) % n;
        self.sessions[i]
            .lock()
            .expect("session mutex poisoned")
    }
}

impl OnnxNerEngine {
    /// Empty engine (regex-only upstream).
    pub fn disabled() -> Self {
        Self { inner: None }
    }

    /// Load from ONNX + tokenizer paths. On failure: logs and returns disabled.
    pub fn try_load(onnx_path: &Path, tokenizer_path: &Path) -> Self {
        match Self::load(onnx_path, tokenizer_path) {
            Ok(inner) => Self {
                inner: Some(Arc::new(inner)),
            },
            Err(e) => {
                warn!(?e, "ONNX NER disabled — falling back to regex-only");
                Self::disabled()
            }
        }
    }

    fn load(onnx_path: &Path, tokenizer_path: &Path) -> Result<NerInner, AgError> {
        let tokenizer = Tokenizer::from_file(tokenizer_path)
            .map_err(|e| AgError::Onnx(format!("tokenizer load: {e}")))?;

        let n_sess = std::thread::available_parallelism()
            .map(|n| n.get().clamp(2, 8))
            .unwrap_or(4);

        let mut sessions = Vec::with_capacity(n_sess);
        for _ in 0..n_sess {
            let s = Session::builder()
                .map_err(|e| AgError::Onnx(e.to_string()))?
                .with_optimization_level(GraphOptimizationLevel::Level3)
                .map_err(|e| AgError::Onnx(e.to_string()))?
                .with_intra_threads(1)
                .map_err(|e| AgError::Onnx(e.to_string()))?
                .commit_from_file(onnx_path)
                .map_err(|e| AgError::Onnx(e.to_string()))?;
            sessions.push(Mutex::new(s));
        }

        Ok(NerInner {
            sessions,
            tokenizer,
            round_robin: AtomicUsize::new(0),
            max_seq_len: 128,
        })
    }

    /// Run NER; returns empty if engine disabled.
    pub fn detect(&self, text: &str) -> Result<Vec<PiiMatch>, AgError> {
        let Some(inner) = &self.inner else {
            return Ok(vec![]);
        };

        if text.is_empty() {
            return Ok(vec![]);
        }

        let enc = inner
            .tokenizer
            .encode(text, true)
            .map_err(|e| AgError::Onnx(e.to_string()))?;

        let mut input_ids: Vec<i64> = enc.get_ids().iter().map(|&x| x as i64).collect();
        let mut attention: Vec<i64> = enc
            .get_attention_mask()
            .iter()
            .map(|&x| x as i64)
            .collect();

        let len = input_ids.len().min(inner.max_seq_len);
        input_ids.truncate(len);
        attention.truncate(len);

        let token_type_ids = vec![0i64; len];

        let ids_arr =
            Array2::from_shape_vec((1, len), input_ids).map_err(|e| AgError::Onnx(e.to_string()))?;
        let attn_arr =
            Array2::from_shape_vec((1, len), attention).map_err(|e| AgError::Onnx(e.to_string()))?;
        let type_arr = Array2::from_shape_vec((1, len), token_type_ids)
            .map_err(|e| AgError::Onnx(e.to_string()))?;

        let mut session = inner.acquire_session();

        let outputs: SessionOutputs = session
            .run(inputs![
                "input_ids" => OrtTensor::from_array(ids_arr).map_err(|e: ort::Error| AgError::Onnx(e.to_string()))?,
                "attention_mask" => OrtTensor::from_array(attn_arr).map_err(|e: ort::Error| AgError::Onnx(e.to_string()))?,
                "token_type_ids" => OrtTensor::from_array(type_arr).map_err(|e: ort::Error| AgError::Onnx(e.to_string()))?
            ])
            .map_err(|e| AgError::Onnx(e.to_string()))?;

        let (shape, flat) = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|e| AgError::Onnx(e.to_string()))?;

        let rank = shape.len();
        if rank != 3 {
            return Err(AgError::Onnx(format!(
                "expected logits rank 3, got rank {rank}"
            )));
        }
        let seq = shape[1] as usize;
        let nlab = shape[2] as usize;
        let preds = argmax_tokens(flat, seq, nlab);
        let offsets = enc.get_offsets();
        Ok(labels_to_byte_matches(&preds, offsets, text))
    }
}

fn argmax_tokens(flat: &[f32], seq: usize, nlab: usize) -> Vec<usize> {
    let mut preds = vec![0usize; seq];
    for t in 0..seq {
        let base = t * nlab;
        let slice = &flat[base..base + nlab];
        let (best, _) = slice
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| {
                a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal)
            })
            .unwrap_or((0, &0.0));
        preds[t] = best;
    }
    preds
}

/// Merge consecutive tokens with label != 0; map char offsets to UTF-8 byte spans.
fn labels_to_byte_matches(
    labels: &[usize],
    offsets: &[(usize, usize)],
    text: &str,
) -> Vec<PiiMatch> {
    let mut out: Vec<PiiMatch> = vec![];
    let mut i = 0usize;
    while i < labels.len() {
        if labels.get(i).copied().unwrap_or(0) == 0 {
            i += 1;
            continue;
        }
        let start_char = offsets.get(i).map(|o| o.0).unwrap_or(0);
        let mut j = i + 1;
        while j < labels.len() && labels[j] != 0 {
            j += 1;
        }
        let end_char = offsets
            .get(j.saturating_sub(1))
            .map(|o| o.1)
            .unwrap_or(start_char);
        let start_b = char_idx_to_byte(text, start_char);
        let end_b = char_idx_to_byte(text, end_char);
        if end_b > start_b && end_b <= text.len() {
            out.push(PiiMatch {
                pii_type: PiiKind::NerEntity,
                start:    start_b,
                end:      end_b,
            });
        }
        i = j;
    }
    out.sort_unstable_by_key(|m| m.start);
    out
}

fn char_idx_to_byte(s: &str, char_idx: usize) -> usize {
    if char_idx == 0 {
        return 0;
    }
    s.char_indices()
        .nth(char_idx)
        .map(|(b, _)| b)
        .unwrap_or(s.len())
}
