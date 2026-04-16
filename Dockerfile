# Project Antigravity — `ag-gateway` (Rust / Axum) multi-stage image
# Python API image (legacy): see Dockerfile.python
# Build: docker build -t ag-gateway:local .
# Run:   docker run --rm -p 8080:8080 \
#          -v "$(pwd)/data/tantivy_index:/data/tantivy_index" \
#          -v "$(pwd)/models:/app/models:ro" \
#          ag-gateway:local
#
# Listen: 8080 (AG_GATEWAY_LISTEN). Writable Tantivy: /data/tantivy_index.
# Optional ONNX: mount assets under /app/models and set AG_PII_NER_*.

FROM rust:1.84-bookworm AS builder
WORKDIR /app

COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY rust_core ./rust_core

RUN cargo build --release -p ag-gateway

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && apt-get clean

ENV RUST_LOG=info
ENV AG_GATEWAY_LISTEN=0.0.0.0:8080
ENV AG_TANTIVY_INDEX_DIR=/data/tantivy_index

COPY models/pii-ner /app/models/pii-ner

COPY --from=builder /app/target/release/ag-gateway /usr/local/bin/ag-gateway

RUN groupadd --system --gid 65532 appgroup \
    && useradd --system --uid 65532 --gid appgroup --home /nonexistent --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/tantivy_index \
    && chown -R 65532:65532 /data /app/models

USER 65532:65532

EXPOSE 8080

VOLUME ["/data/tantivy_index", "/app/models"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=25s --retries=3 \
    CMD curl -sf http://127.0.0.1:8080/health >/dev/null || exit 1

CMD ["/usr/local/bin/ag-gateway"]
