"""
Slow Gemini Mock Server — Phase 3 Chaos Engineering

This server impersonates the Gemini generative language API endpoint,
but deliberately holds each connection open for DELAY_S seconds before
responding. This saturates the httpx connection pool (max_connections=100)
when subjected to high concurrency (>100 inflight requests), causing
httpx.PoolTimeout → CloudInferenceTimeoutError → CircuitBreaker OPEN.

Usage:
    python load_tests/slow_gemini_server.py [--port 19999] [--delay 10]

The server exposes:
    POST /v1beta/models/gemini-pro:generateContent  → slow 200 OK
    GET  /healthz                                   → immediate 200 OK
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [slow-gemini] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_GENERATE_PATH = "/v1beta/models/gemini-pro:generateContent"


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slow Gemini Mock Server")
    parser.add_argument("--port", type=int, default=19999, help="Listen port (default: 19999)")
    parser.add_argument(
        "--delay",
        type=float,
        default=10.0,
        help="Seconds to sleep before responding (default: 10.0)",
    )
    return parser.parse_args()


class SlowGeminiHandler(BaseHTTPRequestHandler):
    """
    HTTP handler that impersonates the Gemini generateContent endpoint.

    The DELAY_S class variable is injected by the factory below so individual
    handler instances can access the configured delay without globals.
    """

    DELAY_S: float = 10.0

    # ── POST handler ──────────────────────────────────────────────────────────

    def do_POST(self) -> None:
        if self.path.startswith(_GENERATE_PATH):
            self._handle_generate()
        else:
            self._send_json({"error": "not found"}, status=404)

    def _handle_generate(self) -> None:
        # Consume request body to avoid client-side broken pipe on some OS.
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

        logger.debug(
            "Holding connection for %.1fs (X-Request-Id: %s).",
            self.DELAY_S,
            self.headers.get("X-Request-Id", "unknown"),
        )
        time.sleep(self.DELAY_S)

        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "[SLOW_MOCK] Chaos response after delay."}]
                        }
                    }
                ]
            }
        ).encode()
        self._send_raw(body, status=200)

    # ── GET handler ───────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json({"status": "ok", "delay_s": self.DELAY_S})
        else:
            self._send_json({"error": "not found"}, status=404)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self._send_raw(body, status=status, content_type="application/json")

    def _send_raw(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        # Suppress per-request access log spam; only warnings/errors surface.
        pass


def make_handler_class(delay_s: float) -> type[SlowGeminiHandler]:
    """Return a SlowGeminiHandler subclass with the configured delay baked in."""

    class ConfiguredHandler(SlowGeminiHandler):
        DELAY_S = delay_s

    return ConfiguredHandler


def main() -> None:
    args = _build_args()

    handler_cls = make_handler_class(args.delay)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler_cls)

    logger.info(
        "Slow Gemini mock server listening on port %d — delay=%.1fs per request.",
        args.port,
        args.delay,
    )
    logger.info(
        "Endpoint: POST http://localhost:%d%s",
        args.port,
        _GENERATE_PATH,
    )
    logger.info(
        "With httpx pool_timeout=1.0s and max_connections=100: "
        "pool exhaustion occurs at ~101 concurrent inflight requests."
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down slow mock server.")
        server.shutdown()


if __name__ == "__main__":
    main()
