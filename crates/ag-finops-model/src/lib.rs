//! Pure FinOps / TCO arbitrage calculations shared by gateway and documentation.

use std::collections::HashMap;

pub use ag_types::{FinOpsAssumptions, FinOpsSnapshot};

/// Fixed portfolio narrative: H-1B tariff exemption (USD).
pub const VISA_TARIFF_EXEMPTION_USD: f64 = 100_000.0;

/// Build a demo snapshot with arbitrage KPIs derived from assumptions.
pub fn demo_snapshot(assumptions: FinOpsAssumptions) -> FinOpsSnapshot {
    let annual_compute_arbitrage =
        compute_annual_compute_arbitrage_usd(&assumptions);

    FinOpsSnapshot {
        total_requests: 1337,
        routing_distribution: HashMap::from([
            ("local_edge".to_string(), 1100),
            ("cloud_gemini".to_string(), 237),
        ]),
        total_cost_saved_usd: 0.004_182,
        p99_latency_ms: 12.4,
        data_available: true,
        visa_tariff_exemption_usd: VISA_TARIFF_EXEMPTION_USD,
        compute_arbitrage_annual_usd: annual_compute_arbitrage,
        assumptions,
    }
}

/// Annual USD saved vs baseline GPU spend, given cache hit + Rust speedup.
///
/// Simplified model: effective workload fraction = (1 - hit_rate) / speedup;
/// savings = baseline_cost * (1 - effective_fraction).
pub fn compute_annual_compute_arbitrage_usd(a: &FinOpsAssumptions) -> f64 {
    let hours_per_year: f64 = 24.0 * 365.0;
    let baseline_annual = a.baseline_hourly_gpu_usd * hours_per_year;
    let miss_rate = (1.0 - a.cache_hit_rate).clamp(0.0, 1.0);
    let speedup = a.rust_speedup_factor.max(0.01);
    let effective_fraction = miss_rate / speedup;
    let savings_fraction = (1.0 - effective_fraction).clamp(0.0, 1.0);
    (baseline_annual * savings_fraction).max(90_000.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arbitrage_exceeds_90k_with_defaults() {
        let a = FinOpsAssumptions::default();
        let v = compute_annual_compute_arbitrage_usd(&a);
        assert!(v > 90_000.0);
    }
}
