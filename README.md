# Aegis V2 – Hardware-Aware Edge-Cloud Entropy Router

**Sprint 1 deliverable**: Non-blocking FastAPI base (uvloop + httptools) with real-time pynvml GPU telemetry and graceful NVML degrade mode.

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install runtime dependencies
pip install -r requirements.txt

# 3. Run the gateway
python -m app.main
# → Listening on http://0.0.0.0:8080
```

Or via uvicorn directly (recommended for production):

```bash
uvicorn app.main:app \
    --host 0.0.0.0 --port 8080 \
    --loop uvloop --http httptools \
    --workers 1
```

---

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

All tests pass in CPU-only / non-GPU environments because the NVML layer degrades gracefully.

---

## Environment variables

All settings are prefixed with `AEGIS_`.  Defaults are production-safe.

| Variable | Default | Description |
|---|---|---|
| `AEGIS_TELEMETRY_POLL_INTERVAL_S` | `1.0` | Seconds between NVML polls |
| `AEGIS_TELEMETRY_NVML_TIMEOUT_S` | `0.5` | Max wait (s) for a single NVML fetch before timeout |
| `AEGIS_TELEMETRY_FAIL_THRESHOLD` | `3` | Consecutive failures before exponential back-off activates |
| `AEGIS_TELEMETRY_BACKOFF_FACTOR` | `2.0` | Back-off multiplier per step |
| `AEGIS_TELEMETRY_MAX_BACKOFF_S` | `60.0` | Upper bound for back-off interval |
| `AEGIS_LOG_LEVEL` | `INFO` | Python logging level |

---

## API endpoints

### `GET /healthz`

Liveness probe.  Always returns HTTP 200.

```json
{
  "status": "ok",
  "telemetry_available": false,
  "timestamp_ms": 1743000000000,
  "degrade_reason": "NvmlUnavailableError: nvmlInit() failed – NVML error: Driver Not Loaded"
}
```

`telemetry_available: false` with a populated `degrade_reason` means the system is running in **CPU-only / Cloud-only degrade mode**.  The gateway continues operating normally; routing decisions in Sprint 2 will fall back to cloud inference when this flag is false.

### `GET /telemetry/gpu`

Returns the latest immutable GPU telemetry snapshot.  This endpoint **never** calls NVML; it only reads from an in-memory state object updated by the background sampler.

```json
{
  "timestamp_ms": 1743000000000,
  "telemetry_available": true,
  "gpu_count": 1,
  "per_gpu": [
    {
      "gpu_index": 0,
      "memory_used_bytes": 2147483648,
      "memory_free_bytes": 6442450944,
      "memory_total_bytes": 8589934592,
      "vram_utilization_ratio": 0.25,
      "sm_utilization_percent": 42,
      "memory_bandwidth_utilization_percent": 20
    }
  ],
  "degrade_reason": null
}
```

> **Note on `vram_utilization_ratio`**: This is `used_bytes / total_bytes` from NVML — an OS-level proxy for hardware memory pressure.  It is intentionally **not** called "fragmentation" because true VRAM fragmentation requires introspection into the CUDA Caching Allocator (e.g. vLLM internal metrics), which will be integrated via an external metrics endpoint in Phase 2.

---

## Degrade behaviour

The gateway is designed for **zero-crash operation** even when NVIDIA hardware or drivers are absent.  The table below documents each failure mode:

| Failure condition | `telemetry_available` | `gpu_count` | `degrade_reason` |
|---|---|---|---|
| `nvidia-ml-py3` package not installed | `false` | `null` | `"nvidia-ml-py3 package not installed: …"` |
| `nvmlInit()` fails (no driver / no permission) | `false` | `null` | `"nvmlInit() failed – NVML error: …"` |
| `nvmlInit()` fails (library `.so` missing) | `false` | `null` | `"nvmlInit() failed – OS error: …"` |
| Device count = 0 (no `/dev/nvidia*` mounts) | `false` | `0` | `"nvmlDeviceGetCount() returned 0 …"` |
| NVML fetch timeout (`> AEGIS_TELEMETRY_NVML_TIMEOUT_S`) | `false` | `null` | `"NVML fetch exceeded timeout of …"` |
| Single device read error (partial failure) | `true` | N | affected GPU fields set to `null` |
| `nvmlDeviceGetCount()` fails after init | `false` | `null` | exception class + message |

After `AEGIS_TELEMETRY_FAIL_THRESHOLD` consecutive failures, the sampler switches to exponential back-off (up to `AEGIS_TELEMETRY_MAX_BACKOFF_S`).  Recovery is automatic: the first successful fetch resets the interval and logs at INFO level.

---

## Architecture overview (Sprint 1)

```
Client Request
      │ HTTP
      ▼
 FastAPI Endpoint  ──read-only──▶  TelemetryState
      │                              (in-memory)
      │                                   ▲
      ▼                                   │ atomic replace (Lock)
  JSON Response           Background sampler task
                               │ asyncio.create_task()
                               ▼
                     ThreadPoolExecutor(max_workers=1)
                               │ executor thread
                               ▼
                     NvmlClient.fetch_snapshot_sync()
                       nvmlInit() → GetCount() → loop devices
                         GetMemoryInfo() + GetUtilizationRates()
```

Key invariants:
- NVML C-bindings **never** run on the ASGI event-loop thread.
- The request path only acquires a short `threading.Lock` to read a reference.
- `asyncio.shield` keeps the executor future alive across `wait_for` timeouts, enabling re-entrancy detection.

---

## Docker / Kubernetes deployment

```bash
docker build -t aegis-v2:sprint1 .

# CPU-only container (NVML degrades gracefully):
docker run -p 8080:8080 aegis-v2:sprint1

# GPU-enabled container (requires NVIDIA Container Toolkit):
docker run --gpus all -p 8080:8080 aegis-v2:sprint1
```

K8s liveness probe:

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
```

The probe always returns HTTP 200 regardless of GPU state, so pods are not restarted due to missing NVIDIA hardware.

---

## Sprint roadmap

| Sprint | Deliverable |
|---|---|
| **1 (this)** | FastAPI + uvloop base, non-blocking pynvml telemetry, degrade mode |
| 2 | Dual-routing engine: Semantic Entropy Probes + VRAM-threshold router |
| 3 | Circuit breaker (pybreaker), async Parquet logging, Polars FinOps pipeline |
