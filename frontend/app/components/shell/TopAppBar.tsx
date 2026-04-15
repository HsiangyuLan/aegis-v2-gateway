/**
 * TopAppBar — Server Component
 * Fixed header with logo, nav status badges, and operator controls.
 * All values are static props; live STATUS/LATENCY updates happen
 * via MetricHero's data broadcast in a future enhancement.
 */

interface TopAppBarProps {
  operatorId?: string;
  latencyMs?: number;
  uptimePct?: number;
}

export default function TopAppBar({
  operatorId = "OPERATOR_ID_001",
  latencyMs = 14,
  uptimePct = 99.9,
}: TopAppBarProps) {
  return (
    <header className="flex justify-between items-center w-full px-6 h-16 bg-[#020203]/40 phosphor-blur fixed top-0 z-50 specular-highlights">
      <div className="flex items-center gap-6">
        {/* Logo */}
        <div
          className="text-2xl font-black text-sky-400 tracking-tighter uppercase"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          AEGIS V2.5
        </div>

        {/* Nav status badges */}
        <nav className="hidden md:flex gap-8 items-center">
          <span
            className="uppercase tracking-tighter tabular text-sm text-sky-400 font-bold border-b-2 border-sky-400 pb-1"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            STATUS: ACTIVE
          </span>
          <span
            className="uppercase tracking-tighter tabular text-sm text-stone-400 secondary-label"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            LATENCY: {latencyMs}MS
          </span>
          <span
            className="uppercase tracking-tighter tabular text-sm text-stone-400 secondary-label"
            style={{ fontFamily: "var(--font-headline)" }}
          >
            UPTIME: {uptimePct}%
          </span>
        </nav>
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-4">
        <div
          className="px-3 py-1 bg-white/5 specular-highlights uppercase text-xs tracking-widest text-sky-400"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          {operatorId}
        </div>
        <span className="material-symbols-outlined text-stone-400 secondary-label hover:text-white cursor-pointer">
          settings
        </span>
        <span className="material-symbols-outlined text-stone-400 secondary-label hover:text-white cursor-pointer">
          terminal
        </span>
      </div>
    </header>
  );
}
