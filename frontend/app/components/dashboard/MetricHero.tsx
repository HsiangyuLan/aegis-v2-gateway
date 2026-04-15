"use client";

/**
 * MetricHero — Client Component
 * Displays total capital allocation with a micro-jitter translate3d effect.
 * Jitter runs via requestAnimationFrame, directly mutating the DOM style
 * property — zero React re-renders for the animation loop.
 * Data updates (React re-renders) are driven by SWR polling at 500ms.
 */

import { useRef, useEffect } from "react";
import { useLiveMetrics } from "@/app/hooks/useLiveMetrics";

function formatCapital(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function formatDelta(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export default function MetricHero() {
  const { data, isLive } = useLiveMetrics();
  const figureRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);

  // Micro-jitter loop — bypasses React render entirely via direct style mutation
  useEffect(() => {
    const jitter = () => {
      const el = figureRef.current;
      if (el) {
        const x = (Math.random() - 0.5) * (isLive ? 0.6 : 0.2);
        const y = (Math.random() - 0.5) * (isLive ? 0.6 : 0.2);
        el.style.transform = `translate3d(${x}px,${y}px,0)`;
      }
      rafRef.current = requestAnimationFrame(jitter);
    };
    rafRef.current = requestAnimationFrame(jitter);
    return () => cancelAnimationFrame(rafRef.current);
  }, [isLive]);

  return (
    <section className="col-span-12 lg:col-span-8 p-12 specular-highlights flex flex-col justify-center bg-transparent relative">
      {/* Section header */}
      <header className="flex items-center gap-4 mb-8">
        <span className="w-2 h-2 bg-primary-container shadow-[0_0_10px_rgba(56,189,248,0.5)]" />
        <h2
          className="text-[10px] font-bold tracking-[0.4em] uppercase text-on-surface-variant secondary-label"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          TOTAL_CAPITAL_ALLOCATION
        </h2>
      </header>

      {/* Large capital figure with jitter */}
      <div
        ref={figureRef}
        className="luminous-body text-[clamp(4rem,10vw,8rem)] font-black tabular text-primary leading-none will-change-transform"
        style={{ fontFamily: "var(--font-headline)" }}
      >
        {formatCapital(data.capitalAllocation)}
      </div>

      {/* Sub-metrics row */}
      <div className="mt-8 flex gap-12 flex-wrap">
        <div>
          <p
            className="text-[10px] tracking-widest text-stone-500 uppercase font-bold mb-1 secondary-label"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            DELTA_24H
          </p>
          <p
            className="text-2xl tabular soft-glow-data text-primary-container"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            {formatDelta(data.delta24h)}
          </p>
        </div>

        <div>
          <p
            className="text-[10px] tracking-widest text-stone-500 uppercase font-bold mb-1 secondary-label"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            VOLATILITY_INDEX
          </p>
          <p
            className="text-2xl tabular soft-glow-data text-on-surface"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            {data.volatilityIndex.toFixed(2)}
          </p>
        </div>

        <div>
          <p
            className="text-[10px] tracking-widest text-stone-500 uppercase font-bold mb-1 secondary-label"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            NODES_ONLINE
          </p>
          <p
            className="text-2xl tabular soft-glow-data text-on-surface"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            {data.nodesOnline.toLocaleString("en-US")}
          </p>
        </div>
      </div>

      {/* Corner pins */}
      <div className="pin absolute bottom-0 left-0" />
      <div className="pin absolute bottom-0 right-0" />
    </section>
  );
}
