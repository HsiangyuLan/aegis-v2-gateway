"""
Tests for SemanticEntropyProbe.

All tests are synchronous — the probe executes in < 1 ms and has no I/O.
"""
from __future__ import annotations

import time

import pytest

from app.routing.entropy import SemanticEntropyProbe


@pytest.fixture(scope="module")
def probe() -> SemanticEntropyProbe:
    return SemanticEntropyProbe()


class TestScoreRange:
    def test_returns_float(self, probe: SemanticEntropyProbe) -> None:
        assert isinstance(probe.calculate("hello world"), float)

    def test_score_between_zero_and_one(self, probe: SemanticEntropyProbe) -> None:
        score = probe.calculate("Explain the entire history of machine learning in detail.")
        assert 0.0 <= score <= 1.0

    def test_empty_prompt_returns_zero(self, probe: SemanticEntropyProbe) -> None:
        assert probe.calculate("") == 0.0

    def test_single_token_returns_zero(self, probe: SemanticEntropyProbe) -> None:
        assert probe.calculate("hello") == 0.0


class TestDeterminism:
    def test_same_prompt_same_score(self, probe: SemanticEntropyProbe) -> None:
        prompt = "What is the capital of France?"
        assert probe.calculate(prompt) == probe.calculate(prompt)

    def test_different_prompts_different_scores(
        self, probe: SemanticEntropyProbe
    ) -> None:
        simple = probe.calculate("yes")
        complex_ = probe.calculate(
            "Analyze the socioeconomic implications of large language model "
            "deployment in emerging markets with reference to multiple case studies."
        )
        assert simple < complex_


class TestRoutingSemantics:
    """Verify that the probe score aligns with the routing threshold (0.4)."""

    THRESHOLD = 0.4

    def test_short_factual_query_below_threshold(
        self, probe: SemanticEntropyProbe
    ) -> None:
        """Simple two-word queries should score well below the routing threshold."""
        score = probe.calculate("What is 2+2?")
        assert score < self.THRESHOLD, (
            f"Expected short factual query to score < {self.THRESHOLD}, got {score}"
        )

    def test_long_complex_query_above_threshold(
        self, probe: SemanticEntropyProbe
    ) -> None:
        """Long multi-concept reasoning prompts should score above the threshold."""
        prompt = (
            "Explain quantum entanglement in detail, covering the EPR paradox, "
            "Bell inequalities, experimental evidence, and implications for "
            "quantum computing and cryptography."
        )
        score = probe.calculate(prompt)
        assert score >= self.THRESHOLD, (
            f"Expected complex prompt to score >= {self.THRESHOLD}, got {score}"
        )


class TestPerformance:
    def test_executes_under_5ms(self, probe: SemanticEntropyProbe) -> None:
        prompt = (
            "Describe the history of artificial intelligence from Turing to GPT-4, "
            "including key milestones, breakthroughs, and controversies."
        )
        t0 = time.perf_counter()
        probe.calculate(prompt)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 5.0, (
            f"SemanticEntropyProbe.calculate() took {elapsed_ms:.2f}ms (limit: 5ms)"
        )
