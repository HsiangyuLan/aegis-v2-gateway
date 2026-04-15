"""
Phase 2: Non-blocking Radix Prefix Cache Index.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Concurrency model — Copy-on-Write (COW)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The hot path (``lookup``) runs inside ``async def`` request handlers on the
uvloop event-loop thread and must NEVER block.  The write path (``insert``,
``evict_worker``) runs on the background poller coroutine and happens at most
once per poll cycle (≤1 Hz).

COW guarantee:
  * ``self._root`` is a plain Python reference.  Replacing it with a new
    ``_PrefixNode`` subtree is an atomic operation under the GIL.
  * Nodes in the "live" tree (reachable from the current ``self._root``) are
    NEVER mutated after being made reachable.  Path-copying creates new node
    objects along the insertion path; all unmodified subtrees are shared.
  * The read path therefore needs no lock: it grabs a local alias of
    ``self._root`` (GIL-atomic), then traverses the immutable tree.

Read complexity:   O(k) where k = len(token_hashes) ≤ AEGIS_KV_PREFIX_MATCH_DEPTH
Write complexity:  O(k) for ``insert`` (path-copy); O(n) for ``evict_worker``
                   where n = total nodes in tree (background operation, rare).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Token hashing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

``hash_prompt_prefix(prompt, depth)`` converts a prompt string into a list of
hex hash strings suitable for radix-tree traversal.

Strategy: whitespace-split the prompt into words; hash each word combined with
its position using BLAKE2s (8-byte output → 16-char hex).  This is a fast,
collision-resistant approximation of token-level prefix matching that requires
no model or tokenizer dependency.

Rationale for position encoding: two prompts "buy now sell" and "sell now buy"
have the same words but different positions, so different KV caches.  The hash
``blake2s(f"{depth}:{word}")`` distinguishes them.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Radix node (mutable during construction; effectively immutable once live) ─

@dataclass
class _PrefixNode:
    """Single node in the radix prefix tree."""
    worker_id: Optional[str] = None
    children: dict[str, "_PrefixNode"] = field(default_factory=dict)


# ─── Path-copying helpers ─────────────────────────────────────────────────────

def _path_copy_insert(
    node: _PrefixNode,
    hashes: list[str],
    depth: int,
    worker_id: str,
) -> _PrefixNode:
    """
    Return a new node that is a path-copy of ``node`` with ``worker_id``
    installed at the leaf ``hashes[-1]``.

    Only nodes along the insertion path are copied; sibling subtrees are shared
    (same object references), keeping write overhead to O(k) objects.
    """
    new_node = _PrefixNode(
        worker_id=node.worker_id,
        children=dict(node.children),  # shallow copy — siblings are shared
    )
    if depth >= len(hashes):
        new_node.worker_id = worker_id
        return new_node

    h = hashes[depth]
    child = node.children.get(h, _PrefixNode())
    new_node.children[h] = _path_copy_insert(child, hashes, depth + 1, worker_id)
    return new_node


def _path_copy_evict(node: _PrefixNode, worker_id: str) -> _PrefixNode:
    """
    Return a new subtree with all nodes whose ``worker_id == worker_id``
    cleared to ``None``.  Empty subtrees are pruned to keep the tree compact.

    O(n) where n = total nodes.  Acceptable because eviction is a rare,
    background operation, not on the hot request path.
    """
    new_children: dict[str, _PrefixNode] = {}
    for h, child in node.children.items():
        new_child = _path_copy_evict(child, worker_id)
        # Prune nodes that carry no information (no worker_id and no children)
        if new_child.worker_id is not None or new_child.children:
            new_children[h] = new_child

    return _PrefixNode(
        worker_id=None if node.worker_id == worker_id else node.worker_id,
        children=new_children,
    )


# ─── Token hashing ────────────────────────────────────────────────────────────

def hash_prompt_prefix(prompt: str, depth: int) -> list[str]:
    """
    Convert a prompt into a list of position-aware hash strings.

    Each element corresponds to one "token" (whitespace-split word) with
    its depth encoded so that positional ordering is preserved.

    Args:
        prompt: Raw prompt string.
        depth:  Maximum number of tokens to hash (default: AEGIS_KV_PREFIX_MATCH_DEPTH).

    Returns:
        List of 16-char hex strings, length ≤ depth.
    """
    words = prompt.split()[:depth]
    return [
        hashlib.blake2s(f"{i}:{w}".encode(), digest_size=8).hexdigest()
        for i, w in enumerate(words)
    ]


# ─── Public index ─────────────────────────────────────────────────────────────

class PrefixCacheIndex:
    """
    Thread-safe radix tree mapping prompt prefix hash sequences → worker_id.

    The ``lookup`` method is designed for the hot request path and acquires
    NO LOCK — it reads from the COW-immutable live tree via an atomic Python
    reference load.

    The ``insert`` and ``evict_worker`` methods are called from the background
    ``worker_registry_loop`` coroutine (at most once per second) and execute
    under a ``threading.Lock`` to serialise concurrent writes.
    """

    def __init__(self) -> None:
        self._root: _PrefixNode = _PrefixNode()
        self._lock = threading.Lock()
        # Map worker_id → count of inserted sequences for monitoring
        self._insert_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Read path — no lock, O(k)
    # ------------------------------------------------------------------

    def lookup(self, token_hashes: list[str]) -> Optional[str]:
        """
        Find the worker_id with the longest matching prefix.

        Returns the worker_id at the deepest matched node, or ``None`` if the
        tree is empty or no prefix matches.

        Thread-safety: safe to call from any thread without a lock because:
        1. ``root = self._root`` is a GIL-atomic reference load.
        2. All nodes in the live tree are immutable after the COW swap.
        """
        root = self._root   # GIL-atomic: always a valid _PrefixNode reference
        node = root
        best: Optional[str] = None
        for h in token_hashes:
            child = node.children.get(h)
            if child is None:
                break
            node = child
            if node.worker_id is not None:
                best = node.worker_id
        return best

    # ------------------------------------------------------------------
    # Write path — under lock, path-copying COW
    # ------------------------------------------------------------------

    def insert(self, token_hashes: list[str], worker_id: str) -> None:
        """
        Insert or update a prefix → worker_id mapping.

        Uses path-copying COW: creates new node objects along the insertion
        path, then atomically swaps ``self._root``.  Unmodified subtrees are
        shared between the old and new trees.

        Args:
            token_hashes: Ordered list of hex hash strings (from
                          ``hash_prompt_prefix`` or worker-reported).
            worker_id:    ID of the worker that caches this prefix.
        """
        if not token_hashes:
            return
        with self._lock:
            new_root = _path_copy_insert(self._root, token_hashes, 0, worker_id)
            self._root = new_root   # GIL-atomic swap
            self._insert_counts[worker_id] = self._insert_counts.get(worker_id, 0) + 1
        logger.debug(
            "PrefixCacheIndex: inserted %d-level prefix for worker=%s "
            "(total inserts for this worker: %d).",
            len(token_hashes), worker_id, self._insert_counts[worker_id],
        )

    def evict_worker(self, worker_id: str) -> None:
        """
        Remove all prefix cache entries that point to ``worker_id``.

        Called by ``worker_registry_loop`` when it detects a KV cache
        eviction event (large drop in used_blocks) or worker failure.
        Runs the O(n) ``_path_copy_evict`` traversal under the write lock
        then atomically swaps the root — this is a background operation and
        the uvloop event-loop thread is never blocked.

        Args:
            worker_id: Worker whose entries should be purged from the index.
        """
        with self._lock:
            new_root = _path_copy_evict(self._root, worker_id)
            self._root = new_root   # GIL-atomic swap
            self._insert_counts.pop(worker_id, None)
        logger.info("PrefixCacheIndex: evicted all entries for worker=%s.", worker_id)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return a shallow copy of per-worker insert counts (for /healthz)."""
        with self._lock:
            return dict(self._insert_counts)
