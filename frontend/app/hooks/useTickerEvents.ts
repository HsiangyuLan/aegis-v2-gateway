"use client";

/**
 * useTickerEvents — native EventSource hook
 * Connects to /api/v1/events/stream (SSE).
 * Maintains a circular buffer of the latest MAX_EVENTS items.
 * Falls back to static demo events on error.
 */

import { useState, useEffect } from "react";
import type { TickerEvent } from "@/app/types/dashboard";

const MAX_EVENTS = 12;

const DEMO_EVENTS: TickerEvent[] = [
  { id: "e1", severity: "info",  message: "SYS_EVENT: BLOCK_19283746_VERIFIED" },
  { id: "e2", severity: "info",  message: "ARB_EXEC: FLASH_LOAN_ACTIVE_3.2M" },
  { id: "e3", severity: "error", message: "NODE_OFFLINE: SHARD_004_PING_FAIL" },
  { id: "e4", severity: "info",  message: "LIQUIDITY_DEPTH: +0.42%" },
  // Duplicate set for seamless marquee loop
  { id: "e5", severity: "info",  message: "SYS_EVENT: BLOCK_19283746_VERIFIED" },
  { id: "e6", severity: "info",  message: "ARB_EXEC: FLASH_LOAN_ACTIVE_3.2M" },
  { id: "e7", severity: "error", message: "NODE_OFFLINE: SHARD_004_PING_FAIL" },
  { id: "e8", severity: "info",  message: "LIQUIDITY_DEPTH: +0.42%" },
];

export function useTickerEvents(): TickerEvent[] {
  const [events, setEvents] = useState<TickerEvent[]>(DEMO_EVENTS);

  useEffect(() => {
    let es: EventSource;

    try {
      es = new EventSource("/api/v1/events/stream");

      es.onmessage = (event: MessageEvent<string>) => {
        try {
          const evt = JSON.parse(event.data) as TickerEvent;
          setEvents((prev) => [...prev, evt].slice(-MAX_EVENTS));
        } catch {
          // Malformed payload — discard
        }
      };

      es.onerror = () => {
        es.close();
      };
    } catch {
      // SSE unavailable — stay on demo
    }

    return () => {
      es?.close();
    };
  }, []);

  return events;
}
