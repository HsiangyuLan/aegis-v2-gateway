/**
 * Aegis V2 Dashboard — TypeScript Interface Definitions
 * Shared across Server Components (props) and Client Component hooks.
 */

/* ─── MetricHero ─────────────────────────────────────────────────────────── */
export interface LiveMetrics {
  capitalAllocation: number;  // USD, e.g. 14892.44
  delta24h: number;           // percentage, e.g. 12.42
  volatilityIndex: number;    // e.g. 0.14
  nodesOnline: number;        // e.g. 1402
  latencyMs: number;          // current system latency ms, e.g. 14
  uptimePct: number;          // e.g. 99.9
}

/* ─── AssetCard / AssetMatrix ────────────────────────────────────────────── */
export type AssetTrend = "up" | "flat" | "down";

export interface AssetPrice {
  symbol: string;      // e.g. "BTC/USD"
  price: number;       // e.g. 64102.11
  spread: number;      // basis points fraction, e.g. 0.0012
  trend: AssetTrend;
}

/* ─── SlaMonitor ─────────────────────────────────────────────────────────── */
export type CoreStatus = "OPERATIONAL" | "DEGRADED" | "OFFLINE";

export interface SlaTimeseries {
  heights: number[];       // 16 values 0–100 (bar heights %)
  slaPercent: number;      // e.g. 99.998
  coreStatus: CoreStatus;
  memLeakPct: number;      // e.g. 0.00
}

/* ─── DataLedger ─────────────────────────────────────────────────────────── */
export type TransactionStatus = "SUCCESS" | "PENDING" | "FAILED";

export interface Transaction {
  id: string;
  timestamp: string;    // ISO or HH:MM:SS, e.g. "04:12:01"
  action: string;       // e.g. "BUY BTC", "STAKE SOL"
  amount: string;       // display string, e.g. "0.0412 BTC"
  status: TransactionStatus;
  isNegative?: boolean; // for withdrawal / sell colouring
}

/* ─── TelemetryMap ───────────────────────────────────────────────────────── */
export interface TelemetryNodes {
  location: string;           // e.g. "40.7128° N, 74.0060° W"
  latencyAsia: number;        // ms
  latencyEu: number;          // ms
  coordinates: [number, number]; // [lat, lon]
}

/* ─── TickerTape ─────────────────────────────────────────────────────────── */
export type TickerSeverity = "info" | "warn" | "error";

export interface TickerEvent {
  id: string;
  severity: TickerSeverity;
  message: string;   // e.g. "SYS_EVENT: BLOCK_19283746_VERIFIED"
}

/* ─── Sidebar Nav ────────────────────────────────────────────────────────── */
export interface NavItem {
  icon: string;   // Material Symbols ligature name, e.g. "terminal"
  label: string;  // e.g. "TERMINAL"
  href: string;
  active?: boolean;
}

/* ─── TOON Format v1.0 ───────────────────────────────────────────────────── */
// Transaction Object Output Notation — enriches Transaction with canvas hints.
// Emitted by /api/v1/transactions/stream as SSE event type "toon".

export interface ToonHints {
  /** Normalised x position 0–1 (golden-ratio stable per prompt_id) */
  x: number;
  /** Normalised y position 0–1 */
  y: number;
  /** Particle radius px (entropy-scaled 2–10) */
  r: number;
  /** Hex colour — cyan=standard, amber=edge_case, red=jailbreak */
  color: string;
  /** Opacity 0–1 — dims on breach/jailbreak */
  alpha: number;
  /** Glow radius px — proportional to AEI value */
  glow: number;
  /** x velocity for trail rendering (FFI-overhead-driven) */
  vx: number;
  /** y velocity for trail rendering (ONNX-cost-driven) */
  vy: number;
  /** z-layer: 0=standard 1=edge_case 2=jailbreak 3=breach */
  layer: number;
}

export interface ToonFrame {
  /** TOON format version — always "1.0" */
  v: "1.0";
  /** Monotonically increasing frame index */
  f: number;
  /** Unix timestamp milliseconds */
  t: number;
  /** Transaction payload (backward-compatible with DataLedger) */
  tx: Transaction;
  /** Canvas draw hints for ScrollyCanvas */
  hints: ToonHints;
}
