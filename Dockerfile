# ── Aegis V2 Gateway — Production Multi-Stage Build ──────────────────────────
#
# Stage 1 (builder): Install Python dependencies into an isolated virtualenv.
#                    The builder stage is discarded after the build; only
#                    /venv is carried forward, keeping the final image lean.
#
# Stage 2 (runner):  Minimal runtime image.  Copies /venv from builder and
#                    application code.  Runs as non-root user "appuser"
#                    (UID/GID 1001) — never root.
#
# GPU-enabled (requires NVIDIA Container Toolkit on the host):
#   docker build -t aegis-v2:latest .
#   docker run --gpus all -p 8080:8080 aegis-v2:latest
#
# CPU-only (NVML degrades gracefully — all endpoints return 200):
#   docker run -p 8080:8080 aegis-v2:latest
#
# Rust extension (aegis_rust_core):
#   Not compiled inside this image.  entropy.py falls back to the Python
#   mock SEP on ImportError — no Rust toolchain needed at runtime.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────────────────────

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Create an isolated virtualenv so the runner stage receives a clean,
# self-contained /venv directory — no interference with system Python paths.
RUN python -m venv /venv

# Install production dependencies into the venv.
# --no-cache-dir keeps the layer small (pip cache is useless in ephemeral builders).
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir --upgrade pip \
 && /venv/bin/pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runner ───────────────────────────────────────────────────────────

FROM python:3.13-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Activate the virtualenv for all subsequent RUN / CMD / ENTRYPOINT calls.
    PATH="/venv/bin:$PATH"

WORKDIR /app

# Create a non-root system user and group.
# --system:         no login shell entry in /etc/passwd by default
# --no-create-home: no home directory (not needed for a service process)
# --shell:          explicit nologin to block interactive logins
RUN groupadd --system --gid 1001 appgroup \
 && useradd  --system --uid 1001 --gid appgroup \
             --no-create-home --shell /sbin/nologin appuser

# ── Copy dependencies from builder ────────────────────────────────────────────
COPY --from=builder /venv /venv

# ── Copy application source ───────────────────────────────────────────────────
COPY app/ ./app/

# ── Copy essential model files only (~23 MB total) ────────────────────────────
# minilm-v2-int8.onnx  → AEGIS_RUST_FAST_MODEL_PATH default
# tokenizer/           → AEGIS_RUST_TOKENIZER_PATH default
# Heavy variants (minilm-v2.onnx ~86 MB, _onnx/, _hf_cache/) are excluded
# via .dockerignore; they are only needed if the full Rust ONNX path is enabled.
COPY models/minilm-v2-int8.onnx    ./models/minilm-v2-int8.onnx
COPY models/tokenizer/             ./models/tokenizer/

# ── Create Parquet log directory and fix ownership ────────────────────────────
# RequestLogger writes Parquet files to AEGIS_FINOPS_LOG_DIR (default: ./logs/finops).
# The directory must be pre-created and writable by appuser before the process starts.
# docker-compose bind-mounts the host ./logs/finops here for persistence across
# container restarts.
RUN mkdir -p logs/finops \
 && chown -R appuser:appgroup /app

# ── Drop privileges ───────────────────────────────────────────────────────────
USER appuser

EXPOSE 8080

# uvloop + httptools are explicitly requested so the event-loop swap is
# guaranteed regardless of how uvicorn detects its optional extras.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--workers", "1"]
