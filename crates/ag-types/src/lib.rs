//! Shared DTOs for gateway, PyO3 bridge, and FinOps UI contracts.

use serde::{Deserialize, Serialize};

/// Categorised PII entity type (API / JSON: SCREAMING_SNAKE_CASE).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PiiKind {
    Email,
    CreditCard,
    Ssn,
    /// Named-entity or ONNX NER bucket (e.g. PERSON, LOC).
    NerEntity,
}

/// A single PII match: entity type and byte offsets (UTF-8 bytes, Python slice semantics).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiiMatch {
    pub pii_type: PiiKind,
    pub start:    usize,
    pub end:      usize,
}

/// JSON returned from scan pipelines (Python + Rust gateway).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScanResponse {
    pub status:        String,
    pub zero_copy:     bool,
    pub async_engine:  bool,
    pub pii_matches:   Vec<PiiMatch>,
    #[serde(default)]
    pub degraded:      bool,
    #[serde(default)]
    pub redacted_text: Option<String>,
    #[serde(default)]
    pub circuit_state: Option<String>,
}

/// Full-text search hit.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub id:      u64,
    pub title:   String,
    pub snippet: String,
    pub score:   f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResponse {
    pub hits:  Vec<SearchHit>,
    pub took_ms: f64,
}

/// FinOps + arbitrage snapshot for the command center UI.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinOpsSnapshot {
    pub total_requests:       u64,
    pub routing_distribution: std::collections::HashMap<String, u64>,
    pub total_cost_saved_usd: f64,
    pub p99_latency_ms:       f64,
    pub data_available:       bool,
    /// H-1B tariff exemption narrative KPI (USD).
    pub visa_tariff_exemption_usd: f64,
    /// Projected annual compute arbitrage (USD / year).
    pub compute_arbitrage_annual_usd: f64,
    pub assumptions:                  FinOpsAssumptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinOpsAssumptions {
    pub cache_hit_rate:          f64,
    pub baseline_hourly_gpu_usd: f64,
    pub rust_speedup_factor:     f64,
}

impl Default for FinOpsAssumptions {
    fn default() -> Self {
        Self {
            cache_hit_rate:          0.80,
            baseline_hourly_gpu_usd: 3.50,
            rust_speedup_factor:     2.5,
        }
    }
}
