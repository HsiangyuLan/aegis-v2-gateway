"use client";

/**
 * useTransactionStream — TOON Format v1.0 SSE hook
 *
 * Connects to /api/v1/transactions/stream which now emits "toon" typed SSE
 * events (event: toon / data: {ToonFrame JSON}).
 *
 * Design decisions
 * ─────────────────
 * 1. addEventListener("toon") instead of onmessage — named SSE event types
 *    are zero-overhead on the browser side and allow co-existing event types
 *    on the same EventSource without conditional parsing.
 *
 * 2. Two separate ring-buffers exposed:
 *    - transactions (Transaction[]) → DataLedger (backward-compatible)
 *    - frames       (ToonFrame[])   → ScrollyCanvas (new)
 *    Both update from the same SSE message; the tx extraction is O(1).
 *
 * 3. Fast path parsing:
 *    JSON.parse is called once per message. The resulting ToonFrame object is
 *    shallow-cloned into both buffers — no second parse, no serialisation.
 *
 * 4. Reconnection strategy:
 *    EventSource retries automatically on network errors. We only close()
 *    on component unmount, never on error, so the demo stays live.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type { Transaction, ToonFrame } from "@/app/types/dashboard";

const MAX_TRANSACTIONS = 20;
const MAX_TOON_FRAMES  = 300;   // ring-buffer for ScrollyCanvas

// ─── Demo data (shown before first SSE message arrives) ──────────────────────

const DEMO_FRAMES: ToonFrame[] = [
  {
    v: "1.0", f: 0, t: Date.now(),
    tx: { id: "t1", timestamp: "04:12:01", action: "INFERENCE_REQ",
          amount: "42 TOKENS @ 7.89ms", status: "SUCCESS", isNegative: false },
    hints: { x: 0.236, y: 0.618, r: 6, color: "#38BDF8", alpha: 0.9,
             glow: 15, vx: 0.01, vy: -0.005, layer: 0 },
  },
  {
    v: "1.0", f: 1, t: Date.now(),
    tx: { id: "t2", timestamp: "04:11:58", action: "EDGE_CASE_PROC",
          amount: "18 TOKENS @ 13.2ms", status: "PENDING", isNegative: false },
    hints: { x: 0.854, y: 0.146, r: 9, color: "#FBBF24", alpha: 0.55,
             glow: 22, vx: -0.02, vy: 0.01, layer: 1 },
  },
  {
    v: "1.0", f: 2, t: Date.now(),
    tx: { id: "t3", timestamp: "04:11:50", action: "THREAT_BLOCKED",
          amount: "5 TOKENS @ 4.1ms", status: "SUCCESS", isNegative: true },
    hints: { x: 0.472, y: 0.382, r: 3, color: "#F87171", alpha: 0.3,
             glow: 8, vx: 0.005, vy: 0.015, layer: 2 },
  },
  {
    v: "1.0", f: 3, t: Date.now(),
    tx: { id: "t4", timestamp: "04:11:42", action: "INFERENCE_REQ",
          amount: "67 TOKENS @ 9.5ms", status: "SUCCESS", isNegative: false },
    hints: { x: 0.090, y: 0.910, r: 7, color: "#38BDF8", alpha: 0.9,
             glow: 18, vx: 0.012, vy: -0.008, layer: 0 },
  },
];

// ─── Hook ─────────────────────────────────────────────────────────────────────

export interface TransactionStreamResult {
  /** Latest MAX_TRANSACTIONS rows — consumed by DataLedger */
  transactions: Transaction[];
  /** Latest MAX_TOON_FRAMES TOON frames — consumed by ScrollyCanvas */
  frames: ToonFrame[];
  /** True once first real SSE message arrives */
  isLive: boolean;
}

export function useTransactionStream(): TransactionStreamResult {
  const [transactions, setTransactions] = useState<Transaction[]>(
    DEMO_FRAMES.map((f) => f.tx)
  );
  const [frames, setFrames] = useState<ToonFrame[]>(DEMO_FRAMES);
  const [isLive, setIsLive] = useState(false);

  // Keep a mutable ref to the current frames length to avoid stale closure
  // inside the event listener — we never need to re-register on frame changes.
  const framesLenRef = useRef<number>(DEMO_FRAMES.length);

  const handleToonEvent = useCallback((event: MessageEvent<string>) => {
    try {
      const frame = JSON.parse(event.data) as ToonFrame;
      if (frame.v !== "1.0" || typeof frame.f !== "number") return;

      setIsLive(true);

      // Update transaction ring-buffer (DataLedger backward compat)
      setTransactions((prev) => [frame.tx, ...prev].slice(0, MAX_TRANSACTIONS));

      // Update TOON frame ring-buffer (ScrollyCanvas)
      setFrames((prev) => {
        const next = [...prev, frame];
        framesLenRef.current = next.length;
        return next.length > MAX_TOON_FRAMES
          ? next.slice(next.length - MAX_TOON_FRAMES)
          : next;
      });
    } catch {
      // Malformed frame — discard silently
    }
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;

    try {
      es = new EventSource("/api/v1/transactions/stream");

      // Named event type "toon" — matches `event: toon` in SSE payload
      es.addEventListener("toon", handleToonEvent as EventListener);

      // Fallback: legacy "message" events (unnamed) for backward compat
      es.onmessage = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          // If it looks like a bare Transaction (no 'v' or 'hints' field),
          // wrap it as a minimal ToonFrame so DataLedger still works.
          if (!data.v && !data.hints) {
            const tx = data as unknown as Transaction;
            setTransactions((prev) => [tx, ...prev].slice(0, MAX_TRANSACTIONS));
          }
        } catch {
          // Discard unparseable legacy messages
        }
      };

      es.onerror = () => {
        // EventSource auto-reconnects; we intentionally do NOT call es.close()
        // here so the reconnection loop continues.
        setIsLive(false);
      };
    } catch {
      // EventSource not supported (SSR context or blocked origin) — demo mode
    }

    return () => {
      es?.close();
    };
  }, [handleToonEvent]);

  return { transactions, frames, isLive };
}
