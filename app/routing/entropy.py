"""
Semantic Entropy Probe (SEP).

Sprint 2–3: Python bigram-diversity mock (deterministic, < 1 ms, no deps).
Sprint 4+:  Rust ONNX bridge via ``aegis_rust_core.compute_entropy_score``.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ — FinOps prompt-caching architecture
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM APIs (Gemini, Anthropic, OpenAI) support prompt-prefix caching: tokens
that appear verbatim at the start of every request are billed at a discounted
"cache read" rate rather than the full input rate.

Aegis V2's routing prompt has two regions:

  ┌─────────────────────────────────────────────────────┐
  │  [STATIC / CACHEABLE]                               │
  │  System instructions + few-shot routing examples   │ ← cached by LLM API
  │  Typical size: 512–1024 tokens                      │
  ├─────────────────────────────────────────────────────┤ ◄ BOUNDARY
  │  [DYNAMIC / NON-CACHEABLE]                          │
  │  Actual user query + telemetry snapshot             │ ← billed at full rate
  └─────────────────────────────────────────────────────┘

The SEP probe only processes the DYNAMIC region: the user query itself.
The static system instructions never change between requests, so they
contribute zero entropy to the routing decision.

Annual cost savings from prefix caching (rough estimate):
  Assumptions:
    - 10,000 requests / day
    - 512 cached tokens / request
    - Gemini Pro input price: $0.0025 / 1K tokens (non-cached)
    - Cache read discount:    80% reduction → $0.0005 / 1K tokens
  Daily savings:   10,000 × 0.512 × ($0.0025 − $0.0005) = $10.24
  Annual savings:  $10.24 × 365 ≈ **$3,737 / year**
  (Scales linearly with request volume; at 100K req/day → ~$37,370 / year)

These are tracked in the FinOps Parquet pipeline (Sprint 3) under
``cost_saved_usd`` per request.

Algorithm (current mock)
────────────────────────
score = bigram_diversity × (1 − e^(−token_count / SATURATION_TOKENS))
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

# ── __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ ───────────────────────────────────────
# This sentinel marks the conceptual boundary between:
#   - The STATIC prefix (system instructions; same every request; cacheable)
#   - The DYNAMIC payload (user query; unique every request; non-cacheable)
#
# The SEP probe receives only the DYNAMIC portion.  The boundary is enforced
# by the EntropyRouter, which strips the system prefix before calling
# SemanticEntropyProbe.calculate().
#
# In Sprint 4, the Rust ONNX engine receives `prompt.encode("utf-8")` as
# a `PyBuffer<u8>` — zero-copy across the FFI boundary (see rust_core/src/lib.rs).
__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__: str = "### USER QUERY ###"

# ── Rust backend availability ─────────────────────────────────────────────────
# Attempt to import the compiled PyO3 extension.
# Fails gracefully when rust_core has not been built (`maturin develop`).
# All 161 existing tests continue to use the Python mock when Rust is absent.
try:
    from aegis_rust_core import CascadingEngine as _CascadingEngine
    from aegis_rust_core import EmbeddingEngine as _RustEngine
    from aegis_rust_core import compute_cascade_entropy_score as _rust_cascade_compute
    from aegis_rust_core import compute_entropy_score as _rust_compute

    _RUST_AVAILABLE: bool = True
    logger.info(
        "[RUST_CORE_READY]  aegis_rust_core loaded — "
        "PyBuffer<u8> zero-copy path; CascadingEngine (dual ONNX) + EmbeddingEngine."
    )
except ImportError:
    _RUST_AVAILABLE = False
    _CascadingEngine = None  # type: ignore[assignment,misc]
    _RustEngine = None  # type: ignore[assignment,misc]
    _rust_compute = None  # type: ignore[assignment]
    _rust_cascade_compute = None  # type: ignore[assignment]
    logger.debug(
        "aegis_rust_core not found — using Python mock SEP. "
        "Run: cd rust_core && maturin develop --release "
        "--features ort-backend,extension-module"
    )


def build_rust_entropy_engine(settings: "Settings") -> object | None:
    """
    Construct ``CascadingEngine`` when the fast ONNX exists; fall back to
    ``EmbeddingEngine`` if cascade construction fails.  Returns ``None`` when
    Rust is unavailable or no model file is present (Python mock SEP).
    """
    if not _RUST_AVAILABLE or _RustEngine is None:
        return None

    fast = settings.rust_fast_model_path
    if not fast or not Path(fast).is_file():
        logger.debug("Rust SEP skipped: fast model not found (%s)", fast)
        return None

    tok = settings.rust_tokenizer_path
    tok_arg: str | None = tok if tok and Path(tok).is_file() else None

    q = (settings.rust_quality_model_path or "").strip()
    quality_arg: str | None = q if q and Path(q).is_file() else None

    if _CascadingEngine is not None:
        try:
            eng = _CascadingEngine(
                fast,
                quality_arg,
                settings.rust_max_seq_len,
                tok_arg,
                settings.rust_num_sessions,
                settings.cascade_uncertainty_trigger,
                settings.cascade_monarch_uncertainty,
            )
            logger.info(
                "[RUST_CASCADE_INIT] fast=%s quality=%s uncertainty_trigger=%.3f "
                "monarch_uncertainty=%.3f",
                fast,
                quality_arg or "—",
                settings.cascade_uncertainty_trigger,
                settings.cascade_monarch_uncertainty,
            )
            return eng
        except Exception as exc:
            logger.warning(
                "CascadingEngine init failed (%s); falling back to EmbeddingEngine.",
                exc,
            )

    try:
        return _RustEngine(
            fast,
            settings.rust_max_seq_len,
            tok_arg,
            settings.rust_num_sessions,
        )
    except Exception as exc2:
        logger.warning("EmbeddingEngine init failed: %s", exc2)
        return None

# ── Mock constants (Python path only) ────────────────────────────────────────
# Characteristic token count for the length saturation curve.
_SATURATION_TOKENS: int = 15


def _tokenise(text: str) -> list[str]:
    """Naive whitespace + punctuation tokeniser; fast and dependency-free."""
    return re.findall(r"\w+", text.lower())


def _bigram_diversity(tokens: list[str]) -> float:
    """Return fraction of unique bigrams over total bigrams."""
    if len(tokens) < 2:
        return 0.0
    bigrams = [(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]
    return len(set(bigrams)) / len(bigrams)


# ── Probe class ───────────────────────────────────────────────────────────────

class SemanticEntropyProbe:
    """
    Lightweight uncertainty estimator for incoming prompts.

    When ``aegis_rust_core`` is available (Sprint 4+), the Rust ONNX path
    is used: the prompt is encoded to UTF-8 bytes and passed via the buffer
    protocol to ``compute_entropy_score`` — physically zero-copy across the
    Python/Rust FFI boundary.

    When Rust is unavailable, the deterministic Python bigram formula is used.
    Both paths produce scores in [0.0, 1.0] with identical routing semantics,
    so all existing tests pass regardless of which path is active.

    CPU-bound note
    ──────────────
    The Python mock runs in < 1 ms and is safe to call from the event loop.
    The Rust ONNX path is CPU-bound (~3–10 ms) and MUST be wrapped in
    ``asyncio.to_thread()`` by the caller (``EntropyRouter.route()``).

    TODO (Sprint 4): Pass the loaded ``EmbeddingEngine`` instance at
    construction time so the session is shared, not recreated per-request.
    """

    def __init__(self, rust_engine: object | None = None) -> None:
        """
        Parameters
        ----------
        rust_engine:
            Optional pre-loaded ``aegis_rust_core.EmbeddingEngine`` instance.
            Sprint 4.2: construct with real tokenizer path for proper inference:

            .. code-block:: python

                engine = EmbeddingEngine(
                    "models/minilm-v2-int8.onnx",
                    tokenizer_path="models/tokenizer/tokenizer.json",
                    num_sessions=4,
                )
                probe = SemanticEntropyProbe(rust_engine=engine)
        """
        self._engine = rust_engine
        self._use_cascade = bool(
            rust_engine is not None
            and _CascadingEngine is not None
            and isinstance(rust_engine, _CascadingEngine)
        )
        self._use_embed = bool(
            rust_engine is not None
            and _RustEngine is not None
            and isinstance(rust_engine, _RustEngine)
        )
        self._use_rust = self._use_cascade or self._use_embed

    def cascade_tier_counts(self) -> tuple[int, int, int] | None:
        """
        Return cumulative ``(哨兵, 學者, 君主)`` tier counts from Rust when using
        ``CascadingEngine``; otherwise ``None``.
        """
        if (
            self._engine is not None
            and _CascadingEngine is not None
            and isinstance(self._engine, _CascadingEngine)
        ):
            s, c, m = self._engine.tier_counts()
            return (int(s), int(c), int(m))
        return None

    def calculate(self, prompt: str) -> float:
        """
        Return a semantic uncertainty score in [0.0, 1.0].

        Routes via Rust ONNX (if available) or Python mock (fallback).

        Routing threshold: scores < 0.4 → local edge; ≥ 0.4 → cloud.

        NOTE: When the Rust backend is active, callers MUST wrap this method
        in ``asyncio.to_thread()`` to avoid blocking the ASGI event loop.
        The ``EntropyRouter.route()`` coroutine will handle this in Sprint 4.
        """
        if self._use_rust and self._engine is not None:
            return self._calculate_rust(prompt)
        return self._calculate_mock(prompt)

    def _calculate_rust(self, prompt: str) -> float:
        """
        Rust ONNX path.

        The prompt is encoded to UTF-8 **once** and the resulting ``bytes``
        object is passed directly to ``compute_entropy_score``.  PyO3's
        ``PyBuffer<u8>`` protocol reads the CPython bytes buffer without
        any copy — the same physical memory is accessed from Rust.

        TODO (Sprint 4): When replacing with real MiniLM, add:
            wrap the call in asyncio.to_thread() because neural inference
            is CPU-bound and will block the ASGI event loop if awaited directly.
        """
        # .encode("utf-8") is the only allocation: a CPython bytes object.
        # The bytes internals are then accessed zero-copy via PyBuffer<u8>.
        payload: bytes = prompt.encode("utf-8")
        if self._use_cascade:
            assert _rust_cascade_compute is not None
            return float(_rust_cascade_compute(self._engine, payload))
        assert _rust_compute is not None
        return float(_rust_compute(self._engine, payload))

    def _calculate_mock(self, prompt: str) -> float:
        """
        Python bigram-diversity mock.

        score = bigram_diversity × (1 − e^(−token_count / SATURATION_TOKENS))

        Deterministic: same prompt always returns same score.
        Executes in < 1 ms — safe on the event loop without ``to_thread``.

        TODO (Sprint 4): When replacing this mock with a real MiniLM forward
        pass, wrap the call in ``asyncio.to_thread()`` because neural inference
        is CPU-bound and will block the ASGI event loop if awaited directly.
        """
        tokens = _tokenise(prompt)
        if not tokens:
            return 0.0
        diversity = _bigram_diversity(tokens)
        length_factor = 1.0 - math.exp(-len(tokens) / _SATURATION_TOKENS)
        return round(min(max(diversity * length_factor, 0.0), 1.0), 6)
