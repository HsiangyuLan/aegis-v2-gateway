"use client";

/**
 * useAssetPrices — SWR polling hook
 * Polls /api/v1/assets/prices every 1000ms.
 * Multiple AssetCard instances share a single in-flight request via
 * a module-level cache (mimics SWR deduplication without the dependency).
 */

import { useState, useEffect } from "react";
import type { AssetPrice } from "@/app/types/dashboard";

export const DEMO_PRICES: AssetPrice[] = [
  { symbol: "BTC/USD", price: 64102.11, spread: 0.0012, trend: "up" },
  { symbol: "ETH/USD", price: 3421.90,  spread: 0.0024, trend: "flat" },
  { symbol: "SOL/USD", price: 145.12,   spread: 0.0041, trend: "down" },
  { symbol: "LINK/USD",price: 18.94,    spread: 0.0008, trend: "up" },
];

const POLL_INTERVAL = 1000;

// Module-level cache — all hook instances share one pending promise
let inflightPromise: Promise<AssetPrice[]> | null = null;

async function fetchPrices(): Promise<AssetPrice[]> {
  if (inflightPromise) return inflightPromise;
  inflightPromise = fetch("/api/v1/assets/prices", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error(`prices fetch failed: ${r.status}`);
      return r.json() as Promise<AssetPrice[]>;
    })
    .finally(() => { inflightPromise = null; });
  return inflightPromise;
}

export function useAssetPrices(): AssetPrice[] {
  const [prices, setPrices] = useState<AssetPrice[]>(DEMO_PRICES);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;

    const poll = async () => {
      try {
        const fresh = await fetchPrices();
        setPrices(fresh);
      } catch {
        // Keep last known value on error
      }
    };

    void poll();
    timer = setInterval(() => { void poll(); }, POLL_INTERVAL);

    return () => clearInterval(timer);
  }, []);

  return prices;
}
