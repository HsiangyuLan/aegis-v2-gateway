"use client";

/**
 * DataLedger — Client Component
 * Real-time transaction feed via SSE (EventSource).
 * The entropy-mask-log CSS fade is static (pure gradient mask),
 * requiring zero JS to maintain its visual effect.
 */

import { useTransactionStream } from "@/app/hooks/useTransactionStream";
import type { TransactionStatus } from "@/app/types/dashboard";

const STATUS_COLOR: Record<TransactionStatus, string> = {
  SUCCESS: "text-stone-500",
  PENDING: "text-stone-500",
  FAILED:  "text-red-500",
};

export default function DataLedger() {
  // Destructure the new TransactionStreamResult — transactions is backward-compatible
  const { transactions: rows } = useTransactionStream();

  return (
    <section className="col-span-12 lg:col-span-7 p-8 specular-highlights bg-surface-container-lowest/10 relative overflow-hidden">
      <h2
        className="text-[10px] font-bold tracking-[0.4em] uppercase text-on-surface-variant mb-8 secondary-label relative z-10"
        style={{ fontFamily: "var(--font-headline)" }}
      >
        TRANSACTION_LEDGER_REALTIME
      </h2>

      {/* Scrollable list with top-fade mask */}
      <div className="space-y-4 relative z-0 entropy-mask-log pb-4">
        {rows.map((tx, idx) => (
          <div
            key={tx.id}
            className={`flex items-center justify-between p-4 bg-white/5 specular-highlights ${
              tx.status === "PENDING" ? "opacity-50" : ""
            }`}
          >
            <div className="flex gap-4 items-center">
              <span className="text-[10px] font-mono text-stone-600 secondary-label">
                {tx.timestamp}
              </span>
              <span
                className="text-xs font-bold tracking-widest soft-glow-data"
                style={{ fontFamily: "var(--font-headline)" }}
              >
                {tx.action}
              </span>
            </div>

            <div className="text-right">
              <div
                className={`text-sm tabular soft-glow-data ${
                  tx.isNegative ? "text-error" : idx === 0 ? "text-primary" : ""
                }`}
                style={{ fontFamily: "var(--font-headline)" }}
              >
                {tx.amount}
              </div>
              <div className={`text-[10px] font-mono secondary-label ${STATUS_COLOR[tx.status]}`}>
                {tx.status}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="pin absolute top-0 right-0" />
    </section>
  );
}
