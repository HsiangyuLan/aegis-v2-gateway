//! Load configuration from environment variables.

use std::path::PathBuf;
use std::time::Duration;

use ag_error::AgError;

/// Gateway and engine configuration.
#[derive(Debug, Clone)]
pub struct AgConfig {
    pub listen_addr:           String,
    pub pii_ner_onnx_path:     Option<PathBuf>,
    pub pii_ner_tokenizer_path: Option<PathBuf>,
    pub tantivy_index_dir:     PathBuf,
    pub degrade_timeout:       Duration,
    pub circuit_failure_rate:  f64,
    pub circuit_window:        usize,
}

impl AgConfig {
    /// Load from process environment. Missing optional paths disable ONNX NER.
    pub fn from_env() -> Result<Self, AgError> {
        let listen_addr =
            std::env::var("AG_GATEWAY_LISTEN").unwrap_or_else(|_| "0.0.0.0:8081".to_string());

        let pii_ner_onnx_path = std::env::var("AG_PII_NER_ONNX").ok().map(PathBuf::from);
        let pii_ner_tokenizer_path =
            std::env::var("AG_PII_NER_TOKENIZER").ok().map(PathBuf::from);

        let tantivy_index_dir = std::env::var("AG_TANTIVY_INDEX_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("data/tantivy_index"));

        let degrade_ms: u64 = std::env::var("AG_DEGRADE_TIMEOUT_MS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(10);

        let circuit_failure_rate: f64 = std::env::var("AG_CIRCUIT_FAILURE_RATE")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.45);

        let circuit_window: usize = std::env::var("AG_CIRCUIT_WINDOW")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(64);

        Ok(Self {
            listen_addr,
            pii_ner_onnx_path,
            pii_ner_tokenizer_path,
            tantivy_index_dir,
            degrade_timeout: Duration::from_millis(degrade_ms),
            circuit_failure_rate,
            circuit_window,
        })
    }
}
