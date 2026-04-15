"use client";

/**
 * useLiveMetrics — SWR polling hook
 * Polls /api/v1/metrics/live every 500ms.
 * Falls back to static demo data when the endpoint is unavailable.
 */

import { useState, useEffect } from "react";
import type { LiveMetrics } from "@/app/types/dashboard";

const DEMO_METRICS: LiveMetrics = {
  capitalAllocation: 14892.44,
  delta24h: 12.42,
  volatilityIndex: 0.14,
  nodesOnline: 1402,
  latencyMs: 14,
  uptimePct: 99.9,
};

const POLL_INTERVAL = 500;

async function fetchMetrics(): Promise<LiveMetrics> {
  const res = await fetch("/api/v1/metrics/live", { cache: "no-store" });
  if (!res.ok) throw new Error(`metrics fetch failed: ${res.status}`);
  return res.json() as Promise<LiveMetrics>;
}

export function useLiveMetrics(): { data: LiveMetrics; isLive: boolean } {
  const [data, setData] = useState<LiveMetrics>(DEMO_METRICS);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;

    const poll = async () => {
      try {
        const fresh = await fetchMetrics();
        setData(fresh);
        setIsLive(true);
      } catch {
        // Silently fall back to demo / last known value
        setIsLive(false);
      }
    };

    void poll();
    timer = setInterval(() => { void poll(); }, POLL_INTERVAL);

    return () => clearInterval(timer);
  }, []);

  return { data, isLive };
}
