//! HTTP middleware: propagate `X-Request-Id` on the response.

use axum::extract::Request;
use axum::middleware::Next;
use axum::response::Response;
use http::header::HeaderValue;
use uuid::Uuid;

#[derive(Clone, Debug)]
pub struct RequestId(pub String);

pub async fn trace_id_middleware(req: Request, next: Next) -> Response {
    let id = Uuid::new_v4().to_string();
    let mut req = req;
    req.extensions_mut().insert(RequestId(id.clone()));

    let mut res = next.run(req).await;
    if let Ok(h) = HeaderValue::from_str(&id) {
        res.headers_mut().insert("x-request-id", h);
    }
    res
}
