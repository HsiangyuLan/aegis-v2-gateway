#!/usr/bin/env bash
# =============================================================================
# Aegis V2 — Phase 3 Chaos Engineering: Service Startup Script
# =============================================================================
#
# Launches the Aegis FastAPI server with environment variables tuned to make
# the CircuitBreaker trip quickly and reliably during Locust load testing.
#
# Key overrides:
#   AEGIS_CLOUD_GEMINI_API_KEY   = non-empty  -> bypasses mock mode, forces
#                                               _real_infer() + real httpx calls
#   AEGIS_CLOUD_GEMINI_BASE_URL  = localhost   -> points at slow_gemini_server.py
#                                               (port 19999, delay=10s per req)
#   AEGIS_HTTPX_POOL_TIMEOUT_S   = 1.0        -> pool slot wait limit (was 5.0s)
#                                               pool exhaustion hits after ~100
#                                               concurrent inflight requests
#   AEGIS_HTTPX_READ_TIMEOUT_S   = 12.0       -> must exceed mock server delay (10s)
#                                               so PoolTimeout fires before ReadTimeout
#   AEGIS_CIRCUIT_BREAKER_COOLDOWN_S = 15.0   -> shortened from 30s to observe
#                                               multiple OPEN->HALF-OPEN cycles
#                                               within a 120s Locust run
#
# Prerequisites:
#   1. slow_gemini_server.py must be running on port 19999:
#      python load_tests/slow_gemini_server.py --port 19999 --delay 10
#
#   2. Locust must be installed:
#      pip install locust
#
# Usage:
#   bash load_tests/chaos_start.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "================================================================"
echo "  Aegis V2 -- Phase 3 Chaos Engineering"
echo "  Starting Aegis service with chaos parameters..."
echo "  Project root: ${PROJECT_ROOT}"
echo "================================================================"

# Verify slow mock server is reachable before starting Aegis.
if ! curl -sf http://localhost:19999/healthz > /dev/null 2>&1; then
    echo ""
    echo "[ERROR] Slow Gemini mock server is NOT running on port 19999."
    echo ""
    echo "  Start it first in a separate terminal:"
    echo "    python load_tests/slow_gemini_server.py --port 19999 --delay 10"
    echo ""
    exit 1
fi

echo "[OK] Slow Gemini mock server is reachable on port 19999."
echo ""

cd "${PROJECT_ROOT}"

AEGIS_CLOUD_GEMINI_API_KEY="chaos-test-key-not-real" \
AEGIS_CLOUD_GEMINI_BASE_URL="http://localhost:19999" \
AEGIS_HTTPX_MAX_CONNECTIONS=100 \
AEGIS_HTTPX_MAX_KEEPALIVE=20 \
AEGIS_HTTPX_CONNECT_TIMEOUT_S=2.0 \
AEGIS_HTTPX_READ_TIMEOUT_S=12.0 \
AEGIS_HTTPX_POOL_TIMEOUT_S=1.0 \
AEGIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3 \
AEGIS_CIRCUIT_BREAKER_COOLDOWN_S=15.0 \
AEGIS_FINOPS_FLUSH_INTERVAL_S=5.0 \
python -m app.main
