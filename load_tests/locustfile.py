"""
Aegis V2 — Phase 3 Chaos Engineering Locust Test
==================================================

Stress-tests the EntropyRouter + CircuitBreaker stack by simulating 500+
concurrent users all hitting POST /v1/infer.  In degraded mode
(telemetry_available=False), every request is routed to CloudGeminiBackend.

Chaos trigger chain:
  500 users -> saturate httpx pool (max_connections=100) ->
  pool_timeout (1s) -> httpx.PoolTimeout ->
  CloudInferenceTimeoutError ->  3 consecutive qualifying failures ->
  CircuitBreaker OPEN -> HTTP 503 fast-fail

Run in Web UI mode (recommended for live observation):
    locust -f load_tests/locustfile.py --host http://localhost:8080

Run headless (CI / automated):
    locust -f load_tests/locustfile.py \
           --headless --users 500 --spawn-rate 50 \
           --run-time 120s --host http://localhost:8080 \
           --html load_tests/report.html --csv load_tests/results

Locust Web UI: http://localhost:8089 (default)
"""
from __future__ import annotations

import random
import string
import uuid

from locust import HttpUser, between, events, task
from locust.env import Environment

# ---------------------------------------------------------------------------
# Prompt corpora
# ---------------------------------------------------------------------------
# Three prompt tiers with distinct token budgets, mirroring realistic
# inference workloads against the EntropyRouter's semantic entropy calculation.

_SHORT_PROMPTS: list[str] = [
    "Explain entropy routing in one sentence.",
    "What is a circuit breaker pattern?",
    "Define FinOps in ten words.",
    "Summarise httpx connection pooling briefly.",
    "What does VRAM utilisation ratio mean?",
]

_MEDIUM_PROMPTS: list[str] = [
    (
        "Describe the FinOps implications of routing LLM inference workloads "
        "to local edge hardware versus cloud APIs.  Include cost modelling "
        "assumptions, amortisation of GPU capital expenditure, and the break-even "
        "request volume per day. Format as three bullet points."
    ),
    (
        "Explain how semantic entropy can be used as a routing signal in a "
        "disaggregated inference cluster.  Discuss the relationship between "
        "prompt perplexity, VRAM headroom, and latency SLOs. Limit to 200 words."
    ),
    (
        "Compare the asyncio Lock approach used in a circuit breaker versus "
        "a threading Lock in a gevent-based environment.  What are the GIL "
        "implications? Provide a concrete Python code example for each approach."
    ),
]

_LONG_PROMPTS: list[str] = [
    (
        "You are a Principal AI Infrastructure Architect.  Provide a comprehensive "
        "technical design document for a hardware-aware edge-to-cloud inference "
        "gateway.  The document must cover: (1) semantic entropy computation using "
        "cross-entropy of a calibration LM, (2) NVML-based VRAM telemetry with "
        "per-device breakdown, (3) a dual-tier routing decision tree with "
        "configurable thresholds, (4) circuit breaker state machine with CLOSED / "
        "OPEN / HALF-OPEN transitions and qualifying failure predicates, "
        "(5) httpx async connection pool sizing for bursty traffic, "
        "(6) non-blocking Parquet FinOps logging via asyncio.Queue and "
        "asyncio.to_thread, and (7) Locust-based chaos engineering methodology "
        "for validating pool exhaustion behaviour.  Use Google-style headings and "
        "include example environment variable configurations for each component."
        + " " + "x" * 500
    ),
    (
        "Analyse the following distributed systems failure scenario and produce "
        "a post-mortem report in the format: Summary, Timeline, Root Cause Analysis, "
        "Contributing Factors, Detection, Resolution, Lessons Learned, Action Items. "
        "\n\nScenario: A production inference gateway serving 800 RPS experienced "
        "a cascading failure when the upstream Gemini API began returning HTTP 503 "
        "responses intermittently.  The circuit breaker was misconfigured with a "
        "failure_threshold=10 and cooldown_s=300, causing prolonged OPEN state. "
        "Simultaneously, the Parquet FinOps logger queue filled to capacity "
        "(buffer_max_size=10000) and began dropping records silently.  The "
        "on-call engineer was alerted by Locust failure rate exceeding 40% but "
        "lacked visibility into circuit breaker state transitions because no "
        "structured logging was emitted on state changes. Provide specific, "
        "actionable recommendations with code-level detail."
        + " " + "y" * 500
    ),
]


def _random_suffix(n: int = 8) -> str:
    """Generate a short random alphanumeric suffix for request deduplication."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# ---------------------------------------------------------------------------
# Locust User
# ---------------------------------------------------------------------------

class AegisUser(HttpUser):
    """
    Simulates a real API consumer hitting the EntropyRouter at high concurrency.

    Task weight distribution (11 total):
      infer_short_prompt  -- weight 5 (45%) : high-volume, low-token requests
      infer_medium_prompt -- weight 3 (27%) : typical production workload
      infer_long_prompt   -- weight 2 (18%) : large-context stress case
      health_check        -- weight 1 ( 9%) : baseline availability probe

    wait_time = between(0.05, 0.3):
      Each user fires between 3-20 req/s.
      500 users -> ~1750-10000 RPS -> far exceeds the 100-slot httpx pool,
      triggering pool exhaustion and PoolTimeout within seconds.
    """

    wait_time = between(0.05, 0.3)

    # -----------------------------------------------------------------------
    # Tasks
    # -----------------------------------------------------------------------

    @task(5)
    def infer_short_prompt(self) -> None:
        """POST /v1/infer with a short prompt (~10 tokens)."""
        self._post_infer(
            prompt=random.choice(_SHORT_PROMPTS) + f" [{_random_suffix()}]",
            name="/v1/infer [short]",
        )

    @task(3)
    def infer_medium_prompt(self) -> None:
        """POST /v1/infer with a medium prompt (~100-150 tokens)."""
        self._post_infer(
            prompt=random.choice(_MEDIUM_PROMPTS) + f" [{_random_suffix()}]",
            name="/v1/infer [medium]",
        )

    @task(2)
    def infer_long_prompt(self) -> None:
        """POST /v1/infer with a long prompt (~700+ tokens) to stress entropy routing."""
        self._post_infer(
            prompt=random.choice(_LONG_PROMPTS) + f" [{_random_suffix()}]",
            name="/v1/infer [long]",
        )

    @task(1)
    def health_check(self) -> None:
        """GET /healthz -- lightweight availability probe."""
        with self.client.get("/healthz", catch_response=True, name="/healthz") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"healthz returned {resp.status_code}")

    # -----------------------------------------------------------------------
    # Shared POST helper
    # -----------------------------------------------------------------------

    def _post_infer(self, prompt: str, name: str) -> None:
        """
        POST /v1/infer and classify the response by circuit breaker state.

        HTTP 200  -> success (EntropyRouter processed the request normally)
        HTTP 503  -> circuit breaker OPEN or HALF-OPEN probe stolen (fast-fail)
        HTTP 422  -> Pydantic validation error (locustfile bug -- should not occur)
        other     -> unexpected server error
        """
        payload = {
            "prompt": prompt,
            "request_id": str(uuid.uuid4()),
        }

        with self.client.post(
            "/v1/infer",
            json=payload,
            catch_response=True,
            name=name,
        ) as resp:
            if resp.status_code == 200:
                resp.success()

            elif resp.status_code == 503:
                # Circuit breaker OPEN or HALF-OPEN probe stolen → fast-fail.
                # Appears in Locust "Failures" tab with a distinct label so the
                # CB trip moment is clearly visible in charts and CSV output.
                resp.failure("circuit-breaker-open [503]")

            elif resp.status_code == 504:
                # CloudInferenceTimeoutError: upstream Gemini/mock server timed
                # out before the circuit breaker tripped.  Appears in failures
                # tab as a separate category from CB-open errors, making the
                # pre-trip vs post-trip boundary clearly visible in metrics.
                resp.failure("cloud-timeout [504]")

            elif resp.status_code == 422:
                resp.failure(f"validation-error [422]: {resp.text[:200]}")

            else:
                resp.failure(
                    f"unexpected-{resp.status_code}: {resp.text[:200]}"
                )


# ---------------------------------------------------------------------------
# Event hooks
# ---------------------------------------------------------------------------

@events.init.add_listener
def on_locust_init(environment: Environment, **kwargs: object) -> None:
    """Print test banner at startup."""
    print(
        "\n"
        "================================================================\n"
        "  Aegis V2 -- Phase 3 Chaos Engineering Load Test\n"
        "\n"
        "  Target:   POST /v1/infer (EntropyRouter -> CloudGemini)\n"
        "  Chaos:    httpx pool exhaustion -> CircuitBreaker OPEN\n"
        "  Expected: HTTP 503 storm after 3 PoolTimeout failures\n"
        "\n"
        "  Watch Aegis logs for:\n"
        "    'qualifying failure N/3 (CloudInferenceTimeoutError)'\n"
        "    'consecutive qualifying failures -> OPEN'\n"
        "    'cooldown elapsed -> HALF-OPEN (probe request allowed)'\n"
        "================================================================\n"
    )


@events.request.add_listener
def on_request(
    request_type: str,
    name: str,
    response_time: float,
    response_length: int,
    exception: Exception | None,
    context: dict,
    **kwargs: object,
) -> None:
    """
    Per-request hook for structured console output during headless runs.
    Only logs exceptions to avoid overwhelming stdout at high RPS.
    """
    if exception is not None:
        print(
            f"[LOCUST] EXCEPTION {request_type} {name} "
            f"| {type(exception).__name__}: {exception}"
        )
