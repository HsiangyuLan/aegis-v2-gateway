//! Tower timeout + re-export of `tower-resilience` circuit breaker for gateway layers.

use std::time::Duration;

pub use tower_resilience_circuitbreaker::CircuitBreakerLayer;

use tower::timeout::TimeoutLayer;

/// Graceful degradation budget (default 10 ms per plan).
pub fn degrade_timeout(ms: u64) -> TimeoutLayer {
    TimeoutLayer::new(Duration::from_millis(ms.max(1)))
}
