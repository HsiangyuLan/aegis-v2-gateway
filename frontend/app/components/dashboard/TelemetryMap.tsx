"use client";

/**
 * TelemetryMap — Client Component
 * World map panel with live node coordinates and regional latency data.
 * The ping animation dot is pure CSS (animate-ping in globals.css).
 * Latency values poll /api/v1/telemetry/nodes every 5s.
 */

import { useState, useEffect } from "react";
import type { TelemetryNodes } from "@/app/types/dashboard";

const DEMO_NODES: TelemetryNodes = {
  location: "40.7128° N, 74.0060° W",
  latencyAsia: 142,
  latencyEu: 28,
  coordinates: [40.7128, -74.006],
};

const POLL_INTERVAL = 5000;

function useTelemetryNodes(): TelemetryNodes {
  const [data, setData] = useState<TelemetryNodes>(DEMO_NODES);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;

    const poll = async () => {
      try {
        const res = await fetch("/api/v1/telemetry/nodes", { cache: "no-store" });
        if (!res.ok) throw new Error(`telemetry fetch failed: ${res.status}`);
        setData(await (res.json() as Promise<TelemetryNodes>));
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

export default function TelemetryMap() {
  const nodes = useTelemetryNodes();

  return (
    <section className="col-span-12 lg:col-span-5 p-8 specular-highlights bg-surface-container-low/20 relative">
      <div className="h-full flex flex-col">
        <h2
          className="text-[10px] font-bold tracking-[0.4em] uppercase text-on-surface-variant mb-8 secondary-label"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          GLOBAL_EXTRACTION_MAP
        </h2>

        {/* Map image */}
        <div className="flex-1 bg-black/40 specular-highlights overflow-hidden relative group">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="w-full h-full object-cover opacity-40 grayscale hover:grayscale-0 transition-all duration-1000"
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuAOMnvPHRH_YDPjDJBg_9gDNSAYifZOZXguCqqpHyDZv9VuFkyyORT0S9-SLg4yJRf15Q-75eahkRXp9o90ctiLiLx0bcAqcJWt73MFQTc4rvSxlejZWzjDyLrEEulY7dmk9hrjXncnm2DMnD8VaCvRpoy6B_KaYYw_Aa10ZeC1ykxecakIE-YvthQAoRCgYb4i9pIIdQJeLT85dcQ6yL1YSgGefjEJfYWVuvTWWYFrCH8JdRoeqtoFRl_XDibtovjUZAUCUMb5XjIR"
            alt="Global extraction map"
          />

          {/* Coordinate overlay */}
          <div
            className="absolute top-4 left-4 p-2 bg-black/80 text-[10px] font-mono text-primary specular-highlights"
          >
            LOC: {nodes.location}
          </div>

          {/* Pulsing node marker */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <div className="w-4 h-4 bg-primary animate-ping opacity-75" />
            <div className="w-2 h-2 bg-primary absolute top-1 left-1" />
          </div>
        </div>

        {/* Regional latency grid */}
        <div className="mt-6 grid grid-cols-2 gap-4">
          <div className="p-4 bg-white/5 specular-highlights">
            <div
              className="text-[8px] text-stone-500 uppercase tracking-widest font-bold secondary-label"
              style={{ fontFamily: "var(--font-headline)" }}
            >
              LATENCY_ASIA
            </div>
            <div
              className="text-xl tabular soft-glow-data"
              style={{ fontFamily: "var(--font-headline)" }}
            >
              {nodes.latencyAsia}ms
            </div>
          </div>

          <div className="p-4 bg-white/5 specular-highlights">
            <div
              className="text-[8px] text-stone-500 uppercase tracking-widest font-bold secondary-label"
              style={{ fontFamily: "var(--font-headline)" }}
            >
              LATENCY_EU
            </div>
            <div
              className="text-xl tabular soft-glow-data"
              style={{ fontFamily: "var(--font-headline)" }}
            >
              {nodes.latencyEu}ms
            </div>
          </div>
        </div>
      </div>

      <div className="pin absolute top-0 left-0" />
    </section>
  );
}
