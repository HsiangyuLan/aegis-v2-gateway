//! Unified error type for workspace crates.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AgError {
    #[error("invalid UTF-8: {0}")]
    Utf8(#[from] std::str::Utf8Error),

    #[error("configuration: {0}")]
    Config(String),

    #[error("ONNX inference: {0}")]
    Onnx(String),

    #[error("search engine: {0}")]
    Search(String),

    #[error("internal: {0}")]
    Internal(String),
}

#[derive(Serialize)]
struct ErrorBody {
    error: String,
}

impl IntoResponse for AgError {
    fn into_response(self) -> Response {
        let status = match &self {
            AgError::Utf8(_) => StatusCode::BAD_REQUEST,
            AgError::Config(_) => StatusCode::INTERNAL_SERVER_ERROR,
            AgError::Onnx(_) => StatusCode::SERVICE_UNAVAILABLE,
            AgError::Search(_) => StatusCode::INTERNAL_SERVER_ERROR,
            AgError::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        };
        let body = Json(ErrorBody {
            error: self.to_string(),
        });
        (status, body).into_response()
    }
}
