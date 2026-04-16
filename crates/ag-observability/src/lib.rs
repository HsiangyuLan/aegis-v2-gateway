//! Initialise `tracing` from `RUST_LOG`.

use tracing_subscriber::EnvFilter;

/// Install global subscriber (idempotent if already set — may warn).
pub fn init_tracing_default() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .try_init();
}
