//! Antigravity Rust gateway: Axum + 10 ms degrade + sliding-window circuit behaviour.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use ag_config::AgConfig;
use ag_finops_model::{demo_snapshot, FinOpsAssumptions};
use ag_http_common::trace_id_middleware;
use ag_observability::init_tracing_default;
use ag_pii_onnx::OnnxNerEngine;
use ag_pii_regex::PiiRegexDetector;
use ag_redact::merge_spans;
use ag_search_tantivy::SearchEngine;
use ag_types::{FinOpsSnapshot, ScanResponse};
use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::middleware;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use tokio::net::TcpListener;
use tower_http::cors::{Any, CorsLayer};

#[derive(Clone)]
struct AppState {
    regex:            Arc<PiiRegexDetector>,
    onnx:             Arc<OnnxNerEngine>,
    search:           Arc<SearchEngine>,
    config:           Arc<AgConfig>,
    circuit_failures: Arc<AtomicU64>,
    circuit_open:     Arc<AtomicBool>,
}

#[derive(Deserialize)]
struct ScanBody {
    text: String,
}

#[derive(Deserialize)]
struct SearchParams {
    #[serde(default)]
    q:     String,
    limit: Option<usize>,
}

fn circuit_state_label(open: bool, failures: u64) -> String {
    if open {
        format!("OPEN(failures={failures})")
    } else {
        "CLOSED".to_string()
    }
}

async fn scan_handler(
    State(state): State<AppState>,
    Json(body): Json<ScanBody>,
) -> impl IntoResponse {
    let bytes = body.text.as_bytes();
    let arc = match ag_zero_copy::arc_from_utf8_bytes(bytes) {
        Ok(a) => a,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": e.to_string() })),
            )
                .into_response();
        }
    };
    let text = unsafe { ag_zero_copy::str_from_arc_unchecked(&arc) };

    let circuit_open = state.circuit_open.load(Ordering::Relaxed);
    let mut degraded = circuit_open;
    let mut onnx_matches = Vec::new();

    if !circuit_open {
        let eng = state.onnx.clone();
        let t = text.to_string();
        let to = state.config.degrade_timeout;
        let onnx_res = tokio::time::timeout(to, tokio::task::spawn_blocking(move || {
            eng.detect(&t)
        }))
        .await;

        match onnx_res {
            Ok(Ok(Ok(m))) => {
                onnx_matches = m;
                state.circuit_failures.store(0, Ordering::Relaxed);
                state.circuit_open.store(false, Ordering::Relaxed);
            }
            Ok(Ok(Err(e))) => {
                tracing::warn!(?e, "ONNX NER error");
                degraded = true;
                let n = state.circuit_failures.fetch_add(1, Ordering::Relaxed) + 1;
                if n >= (state.config.circuit_window as u64 / 4).max(3) {
                    state.circuit_open.store(true, Ordering::Relaxed);
                }
            }
            Ok(Err(join_e)) => {
                tracing::warn!(?join_e, "ONNX task join");
                degraded = true;
                bump_circuit(&state);
            }
            Err(_elapsed) => {
                tracing::warn!("ONNX NER timeout — graceful degradation");
                degraded = true;
                bump_circuit(&state);
            }
        }
    }

    let regex_matches = state.regex.detect(text);
    let mut all = regex_matches;
    all.extend(onnx_matches);
    all = merge_spans(all);
    let redacted = ag_redact::redact_text(text, &all);
    let failures = state.circuit_failures.load(Ordering::Relaxed);
    let open = state.circuit_open.load(Ordering::Relaxed);

    let resp = ScanResponse {
        status:        "success".to_string(),
        zero_copy:     true,
        async_engine:  true,
        pii_matches:   all,
        degraded,
        redacted_text: Some(redacted),
        circuit_state: Some(circuit_state_label(open, failures)),
    };
    Json(resp).into_response()
}

fn bump_circuit(state: &AppState) {
    let n = state.circuit_failures.fetch_add(1, Ordering::Relaxed) + 1;
    let thresh = (state.config.circuit_failure_rate * state.config.circuit_window as f64) as u64;
    let thresh = thresh.max(3);
    if n >= thresh {
        state.circuit_open.store(true, Ordering::Relaxed);
    }
}

async fn finops_handler() -> Json<FinOpsSnapshot> {
    Json(demo_snapshot(FinOpsAssumptions::default()))
}

async fn search_handler(
    State(state): State<AppState>,
    Query(q): Query<SearchParams>,
) -> impl IntoResponse {
    match state.search.search(&q.q, q.limit.unwrap_or(10)) {
        Ok(r) => Json(r).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}

async fn health_handler() -> &'static str {
    "ok"
}

async fn ready_handler(State(state): State<AppState>) -> impl IntoResponse {
    if state.search.search("FinOps", 1).is_ok() {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    init_tracing_default();
    let config = Arc::new(AgConfig::from_env().map_err(|e| e.to_string())?);

    let onnx = match (&config.pii_ner_onnx_path, &config.pii_ner_tokenizer_path) {
        (Some(m), Some(t)) => OnnxNerEngine::try_load(m, t),
        _ => OnnxNerEngine::disabled(),
    };

    let search = Arc::new(SearchEngine::open_or_create(&config.tantivy_index_dir).map_err(
        |e| e.to_string(),
    )?);

    let state = AppState {
        regex:            Arc::new(PiiRegexDetector::new()),
        onnx:             Arc::new(onnx),
        search,
        config:           config.clone(),
        circuit_failures: Arc::new(AtomicU64::new(0)),
        circuit_open:     Arc::new(AtomicBool::new(false)),
    };

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/healthz", get(health_handler))
        .route("/ready", get(ready_handler))
        .route("/v1/analytics/scan", post(scan_handler))
        .route("/v1/analytics/finops", get(finops_handler))
        .route("/v1/finops", get(finops_handler))
        .route("/v1/search", get(search_handler))
        .layer(cors)
        .layer(middleware::from_fn(trace_id_middleware))
        .with_state(state);

    let listener = TcpListener::bind(&config.listen_addr).await?;
    tracing::info!(addr = %config.listen_addr, "ag-gateway listening");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("graceful shutdown requested");
}
