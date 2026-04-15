"""
Phase 2: KV Cache-Aware Worker Router.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role in the two-stage routing pipeline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Stage 1 — ``EntropyRouter._decide()``
    Decides between LOCAL_EDGE and CLOUD_GEMINI based on semantic entropy and
    aggregate VRAM utilization.  This stage is UNCHANGED from Sprint 3.

Stage 2 — ``KVAwareRouter.select_worker()``  (this module)
    Only reached when Stage 1 returns LOCAL_EDGE.  Selects the specific
    disaggregated worker to handle the request by maximising KV prefix cache
    reuse.  Returns ``None`` if no healthy worker is available, causing
    ``EntropyRouter._execute()`` to fall back to the cloud path transparently.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Worker selection algorithm
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Snapshot — O(1) ``threading.Lock`` acquire/release via WorkerRegistryState.
2. Filter  — retain workers where ``is_healthy=True`` and
             ``kv.free_ratio > kv_min_free_ratio``.
3. Prefix match — hash the first ``kv_prefix_match_depth`` whitespace-split
             words of the prompt; look up in PrefixCacheIndex (O(k), no lock).
4. If a matching worker is in the healthy set → select it (prefix cache hit).
5. Otherwise → select the worker with the highest ``kv.free_ratio``
             (least-loaded fallback, O(w) where w = number of healthy workers).
6. If the healthy set is empty → return None (triggers cloud fallback in
             EntropyRouter._execute()).

All critical-path operations (steps 1-5) are synchronous and non-blocking.
The ``async def`` signature is kept for future extensibility.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import Settings
from app.routing.prefix_cache import PrefixCacheIndex, hash_prompt_prefix
from app.routing.worker_registry import WorkerInfo, WorkerRegistryState

logger = logging.getLogger(__name__)


class KVAwareRouter:
    """
    Second-stage router: selects the disaggregated worker with maximum KV
    cache prefix reuse for a LOCAL_EDGE-bound request.

    All dependencies are injected at construction time so the class is fully
    testable without a running FastAPI application.

    Parameters
    ----------
    registry:           Shared WorkerRegistryState populated by the background
                        poller.
    prefix_cache:       Shared PrefixCacheIndex for O(k) prefix lookups.
    settings:           Application settings (kv_prefix_match_depth,
                        kv_min_free_ratio).
    """

    def __init__(
        self,
        registry: WorkerRegistryState,
        prefix_cache: PrefixCacheIndex,
        settings: Settings,
    ) -> None:
        self._registry = registry
        self._prefix_cache = prefix_cache
        self._match_depth = settings.kv_prefix_match_depth
        self._min_free_ratio = settings.kv_min_free_ratio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def select_worker(
        self,
        prompt: str,
        request_id: str,
    ) -> tuple[WorkerInfo, bool] | None:
        """
        Select the best healthy worker for the given prompt.

        The method is ``async def`` for forward compatibility (e.g. if future
        eviction notifications require awaiting a lock).  Its critical path is
        entirely synchronous and non-blocking.

        Args:
            prompt:      Raw prompt string used for prefix matching.
            request_id:  Unique request identifier (used for debug logging).

        Returns:
            A ``(WorkerInfo, kv_prefix_hit)`` tuple where:
                WorkerInfo:    The selected worker's frozen state snapshot.
                kv_prefix_hit: True if a prefix cache hit drove the selection.
            Returns ``None`` if no healthy worker with sufficient free KV cache
            is available.  Callers must treat ``None`` as a signal to fall back
            to the cloud backend.
        """
        # Step 1: O(1) snapshot read
        snapshot = self._registry.get_snapshot()

        # Step 2: Filter to healthy workers with enough free KV cache
        healthy = [
            w for w in snapshot.workers
            if w.is_healthy and w.kv.free_ratio > self._min_free_ratio
        ]

        if not healthy:
            logger.debug(
                "request_id=%s KVAwareRouter: no healthy workers available "
                "(total registered: %d).",
                request_id,
                len(snapshot.workers),
            )
            return None

        # Step 3: O(k) prefix match — no lock acquired
        token_hashes = hash_prompt_prefix(prompt, self._match_depth)
        best_worker_id: Optional[str] = self._prefix_cache.lookup(token_hashes)

        # Step 4: Use the prefix-matched worker if it is in the healthy set
        if best_worker_id is not None:
            matched = next(
                (w for w in healthy if w.worker_id == best_worker_id), None
            )
            if matched is not None:
                logger.debug(
                    "request_id=%s KVAwareRouter: prefix cache HIT → worker=%s "
                    "(free_ratio=%.3f).",
                    request_id, matched.worker_id, matched.kv.free_ratio,
                )
                return matched, True

        # Step 5: Fallback — least-loaded healthy worker (max free_ratio)
        least_loaded = max(healthy, key=lambda w: w.kv.free_ratio)
        logger.debug(
            "request_id=%s KVAwareRouter: prefix cache MISS → least-loaded "
            "worker=%s (free_ratio=%.3f).",
            request_id, least_loaded.worker_id, least_loaded.kv.free_ratio,
        )
        return least_loaded, False
