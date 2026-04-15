"use client";

/**
 * SlaMonitor — Client Component
 * 16-bar SLA visualisation using entropy-mask-v gradient bars.
 * Bar heights are updated by directly writing CSS custom properties
 * on each bar DOM element — zero React re-renders for height updates.
 */

import { useRef, useEffect } from "react";
import { useSlaTimeseries } from "@/app/hooks/useSlaTimeseries";

const BAR_COUNT = 16;

export default function SlaMonitor() {
  const data = useSlaTimeseries();
  // One ref per bar — typed as array of nullable elements
  const barRefs = useRef<(HTMLDivElement | null)[]>(
    Array.from({ length: BAR_COUNT }, () => null)
  );

  // On each data update, mutate CSS custom properties directly — no re-render
  useEffect(() => {
    data.heights.slice(0, BAR_COUNT).forEach((h, i) => {
      const el = barRefs.current[i];
      if (el) {
        el.style.setProperty("--bar-h", `${h}%`);
      }
    });
  }, [data.heights]);

  const statusColor =
    data.coreStatus === "OPERATIONAL"
      ? "text-stone-500"
      : data.coreStatus === "DEGRADED"
      ? "text-amber-500"
      : "text-red-500";

  return (
    <section className="col-span-12 lg:col-span-4 p-8 specular-highlights bg-[#020203]/20 flex flex-col relative">
      <header className="flex justify-between items-center mb-12">
        <h2
          className="text-[10px] font-bold tracking-[0.4em] uppercase text-on-surface-variant secondary-label"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          SYSTEM_INTEGRITY
        </h2>
        <span
          className="text-[10px] tabular text-primary secondary-label"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          SLA: {data.slaPercent.toFixed(3)}%
        </span>
      </header>

      <div className="flex-1 flex flex-col">
        {/* Bar chart — heights driven by CSS var --bar-h */}
        <div className="flex items-end justify-between flex-1 gap-1 relative overflow-hidden">
          {Array.from({ length: BAR_COUNT }, (_, i) => (
            <div
              key={i}
              ref={(el) => { barRefs.current[i] = el; }}
              className="flex-1 entropy-mask-v w-2"
              style={{ height: "var(--bar-h, 90%)" }}
            />
          ))}
        </div>

        {/* Status text */}
        <div className="mt-8">
          <p
            className={`text-[10px] font-mono secondary-label ${statusColor}`}
          >
            CORE_ENGINE: {data.coreStatus}
          </p>
          <p className="text-[10px] text-stone-500 font-mono mt-1 secondary-label">
            MEM_LEAK: {data.memLeakPct.toFixed(2)}%
          </p>

          {/* Three-segment indicator bar */}
          <div className="mt-4 flex gap-2">
            <span className="w-full h-1 bg-stone-800" />
            <span className="w-full h-1 bg-primary" />
            <span className="w-full h-1 bg-stone-800" />
          </div>
        </div>
      </div>

      {/* Corner pins */}
      <div className="pin absolute bottom-0 right-0" />
      <div className="pin absolute top-0 left-0" />
    </section>
  );
}
