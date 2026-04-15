"use client";

/**
 * TickerTape — Client Component
 * Fixed-bottom scrolling event feed using the CSS animate-marquee class.
 * The marquee animation runs entirely on the compositor thread via
 * will-change: transform (set in globals.css .animate-marquee).
 * Live events are appended via EventSource SSE.
 */

import { useTickerEvents } from "@/app/hooks/useTickerEvents";
import type { TickerSeverity } from "@/app/types/dashboard";

const DOT_COLOR: Record<TickerSeverity, string> = {
  info:  "bg-primary shadow-[0_0_5px_rgba(56,189,248,0.5)]",
  warn:  "bg-amber-400 shadow-[0_0_5px_rgba(251,191,36,0.5)]",
  error: "bg-error shadow-[0_0_5px_rgba(255,180,171,0.5)]",
};

const TEXT_COLOR: Record<TickerSeverity, string> = {
  info:  "text-on-surface",
  warn:  "text-amber-400",
  error: "text-error",
};

export default function TickerTape() {
  const events = useTickerEvents();

  return (
    <footer className="fixed bottom-0 left-0 right-0 h-8 bg-[#0e0e10]/40 phosphor-blur flex items-center z-50 md:pl-64 overflow-hidden specular-highlights">
      <div className="flex gap-12 px-6 items-center whitespace-nowrap animate-marquee">
        {events.map((evt) => (
          <div key={evt.id} className="flex gap-2 items-center">
            <span className={`w-1.5 h-1.5 ${DOT_COLOR[evt.severity]}`} />
            <span
              className={`text-[10px] font-mono uppercase tracking-widest secondary-label ${TEXT_COLOR[evt.severity]}`}
            >
              {evt.message}
            </span>
          </div>
        ))}
      </div>
    </footer>
  );
}
