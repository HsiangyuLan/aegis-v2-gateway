"use client";

/**
 * useSlaTimeseries — SWR polling hook
 * Polls /api/v1/sla/timeseries every 1000ms.
 * Returns SlaTimeseries; bar height updates are applied via direct
 * CSS custom property mutation in SlaMonitor (no React re-render).
 */

import { useState, useEffect } from "react";
import type { SlaTimeseries } from "@/app/types/dashboard";

const DEMO: SlaTimeseries = {
  heights: [90, 85, 95, 80, 88, 92, 82, 75, 98, 90, 84, 86, 91, 88, 94, 78],
  slaPercent: 99.998,
  coreStatus: "OPERATIONAL",
  memLeakPct: 0.0,
};

const POLL_INTERVAL = 1000;

async function fetchSla(): Promise<SlaTimeseries> {
  const res = await fetch("/api/v1/sla/timeseries", { cache: "no-store" });
  if (!res.ok) throw new Error(`sla fetch failed: ${res.status}`);
  return res.json() as Promise<SlaTimeseries>;
}

export function useSlaTimeseries(): SlaTimeseries {
  const [data, setData] = useState<SlaTimeseries>(DEMO);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;

    const poll = async () => {
      try {
        const fresh = await fetchSla();
        setData(fresh);
      } catch {
        // Keep last known value
      }
    };

    void poll();
    timer = setInterval(() => { void poll(); }, POLL_INTERVAL);

    return () => clearInterval(timer);
  }, []);

  return data;
}
