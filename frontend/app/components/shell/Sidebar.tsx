/**
 * Sidebar — Server Component
 * Fixed left navigation with icon-links and bottom action area.
 * Interactive buttons are delegated to SidebarActions (CC).
 */

import type { NavItem } from "@/app/types/dashboard";
import SidebarActions from "./SidebarActions";

const NAV_ITEMS: NavItem[] = [
  { icon: "terminal",              label: "TERMINAL",  href: "#", active: true },
  { icon: "account_balance",       label: "LEDGER",    href: "#" },
  { icon: "insights",              label: "TELEMETRY", href: "#" },
  { icon: "precision_manufacturing",label: "EXTRACTOR", href: "#" },
  { icon: "lock",                  label: "VAULT",     href: "#" },
  { icon: "history",               label: "LOGS",      href: "#" },
];

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-16 h-[calc(100vh-64px)] w-64 bg-[#020203]/60 phosphor-blur flex flex-col specular-highlights z-40 hidden md:flex">
      {/* Brand block */}
      <div className="p-6 border-b border-white/5">
        <div
          className="text-xl font-black text-white uppercase soft-glow-data"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          SOVEREIGN
        </div>
        <div
          className="text-[10px] tracking-[0.2em] text-stone-500 font-bold uppercase mt-1 secondary-label"
          style={{ fontFamily: "var(--font-headline)" }}
        >
          V2.5 INSTRUMENT
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 py-4 overflow-y-auto">
        {NAV_ITEMS.map((item) =>
          item.active ? (
            <a
              key={item.label}
              href={item.href}
              className="text-black bg-sky-400 flex items-center gap-4 px-6 py-3 w-full font-bold text-xs tracking-widest tabular uppercase"
              style={{ fontFamily: "var(--font-headline)" }}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              {item.label}
            </a>
          ) : (
            <a
              key={item.label}
              href={item.href}
              className="text-stone-500 secondary-label flex items-center gap-4 px-6 py-3 w-full font-bold text-xs tracking-widest tabular uppercase hover:text-white hover:bg-stone-800"
              style={{ fontFamily: "var(--font-headline)" }}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              {item.label}
            </a>
          )
        )}
      </nav>

      {/* Interactive bottom actions (CC boundary) */}
      <SidebarActions />
    </aside>
  );
}
