"use client";

/**
 * FinOpsDashboard — Live Impact Metrics for Aegis V2
 * ====================================================
 * Fetches /v1/analytics/finops from the Aegis V2 FastAPI backend using SWR
 * (Stale-While-Revalidate).  Renders real-time FinOps aggregates without
 * blocking the main page rendering or the ScrollyCanvas CSS animation sequence.
 *
 * ASGI invariant: all Polars computation runs in asyncio.to_thread() on the
 * backend; this component only receives the pre-computed JSON payload.
 *
 * Design system compliance (spec.md):
 * - Brand palette: #FF0000 / #FFFFFF / #000000 only
 * - Inter-Bold body text via var(--font-body)
 * - Futura Heavy labels via var(--font-futura)
 * - border-radius: 0px throughout
 * - incision-b / incision-t classes for section dividers
 *
 * States handled:
 * 1. isLoading && !data → SkeletonLayout (fixed height → zero CLS)
 * 2. error && !data     → ErrorBanner (inline, page does not crash)
 * 3. data.data_available=false → EmptyState
 * 4. data.data_available=true  → full MetricsLayout
 *
 * SWR stale-while-revalidate: if a background revalidation fails, the
 * previous successful data continues to display — no flash to skeleton.
 */

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";

// ── Data contract (mirrors app/observability/analytics.py FinOpsReport) ───────

interface FinOpsReport {
  total_requests: number;
  routing_distribution: Record<string, number>;
  total_cost_saved_usd: number;
  p99_latency_ms: number;
  data_available: boolean;
}

// ── SWR fetcher ───────────────────────────────────────────────────────────────

const fetcher = (url: string): Promise<FinOpsReport> =>
  fetch(url).then((res) => {
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json() as Promise<FinOpsReport>;
  });

// ── Typography helpers (spec.md compliant) ────────────────────────────────────

const FONT_FUTURA =
  "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)";
const FONT_BODY = "var(--font-body, Inter, sans-serif)";

// ── Animated KPI counter ──────────────────────────────────────────────────────

function KpiCounter({ target }: { target: number }) {
  const [display, setDisplay] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const DURATION_MS = 1200;

  useEffect(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    startTimeRef.current = null;

    const startValue = display;
    const delta = target - startValue;

    const step = (timestamp: number) => {
      if (startTimeRef.current === null) startTimeRef.current = timestamp;
      const elapsed = timestamp - startTimeRef.current;
      const progress = Math.min(elapsed / DURATION_MS, 1);
      // Ease-out cubic for a natural deceleration feel.
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(startValue + delta * eased);
      if (progress < 1) rafRef.current = requestAnimationFrame(step);
    };

    rafRef.current = requestAnimationFrame(step);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return (
    <span>
      <span style={{ color: "#FF0000" }}>$</span>
      {display.toFixed(6)}
    </span>
  );
}

// ── Skeleton layout (same DOM height as populated state → zero CLS) ───────────

function SkeletonBlock({ width, height }: { width: string; height: string }) {
  return (
    <div
      style={{
        width,
        height,
        background: "rgba(0,0,0,0.06)",
        marginBottom: "4px",
      }}
      aria-hidden="true"
    />
  );
}

function SkeletonLayout() {
  return (
    <div aria-label="Loading metrics…" role="status">
      {/* Eyebrow */}
      <SkeletonBlock width="180px" height="10px" />
      <div style={{ height: "20px" }} />

      {/* KPI Hero */}
      <SkeletonBlock width="220px" height="56px" />
      <div style={{ height: "4px" }} />
      <SkeletonBlock width="120px" height="10px" />
      <div style={{ height: "32px" }} />

      {/* Metrics grid */}
      <div style={{ display: "flex", gap: "40px", marginBottom: "32px" }}>
        {[0, 1].map((i) => (
          <div key={i}>
            <SkeletonBlock width="80px" height="10px" />
            <div style={{ height: "4px" }} />
            <SkeletonBlock width="120px" height="32px" />
          </div>
        ))}
      </div>

      {/* Bar chart */}
      <SkeletonBlock width="100px" height="10px" />
      <div style={{ height: "12px" }} />
      {[0, 1].map((i) => (
        <div key={i} style={{ marginBottom: "12px" }}>
          <SkeletonBlock width="60px" height="10px" />
          <div style={{ height: "4px" }} />
          <SkeletonBlock width={i === 0 ? "65%" : "35%"} height="4px" />
        </div>
      ))}
    </div>
  );
}

// ── Routing bar chart (pure CSS, no charting library) ─────────────────────────

const DESTINATION_LABELS: Record<string, string> = {
  local_edge: "LOCAL EDGE",
  cloud_gemini: "CLOUD GEMINI",
};

const DESTINATION_COLORS: Record<string, string> = {
  local_edge: "#FF0000",
  cloud_gemini: "#000000",
};

function RoutingBarChart({
  distribution,
}: {
  distribution: Record<string, number>;
}) {
  const total = Object.values(distribution).reduce((s, n) => s + n, 0);
  if (total === 0) return null;

  // Sort: local_edge first, then cloud_gemini, then any future destinations.
  const entries = Object.entries(distribution).sort(([a], [b]) => {
    const order: Record<string, number> = { local_edge: 0, cloud_gemini: 1 };
    return (order[a] ?? 99) - (order[b] ?? 99);
  });

  return (
    <div>
      <span
        style={{
          display: "block",
          fontFamily: FONT_BODY,
          fontWeight: 700,
          fontSize: "10px",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "#000000",
          opacity: 0.45,
          marginBottom: "12px",
        }}
      >
        ROUTING DISTRIBUTION
      </span>

      {entries.map(([key, count]) => {
        const pct = (count / total) * 100;
        const label = DESTINATION_LABELS[key] ?? key.toUpperCase();
        const color = DESTINATION_COLORS[key] ?? "#000000";

        return (
          <div key={key} style={{ marginBottom: "14px" }}>
            {/* Label + count */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: "4px",
              }}
            >
              <span
                style={{
                  fontFamily: FONT_BODY,
                  fontWeight: 700,
                  fontSize: "10px",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color,
                }}
              >
                {label}
              </span>
              <span
                style={{
                  fontFamily: FONT_BODY,
                  fontWeight: 700,
                  fontSize: "10px",
                  letterSpacing: "0.04em",
                  color: "#000000",
                  opacity: 0.55,
                }}
              >
                {count.toLocaleString()} ({pct.toFixed(1)}%)
              </span>
            </div>

            {/* Track */}
            <div
              style={{
                width: "100%",
                height: "4px",
                background: "rgba(0,0,0,0.08)",
                position: "relative",
              }}
            >
              {/* Fill — uses calc() so the browser paints it in one pass */}
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  height: "4px",
                  width: `${pct}%`,
                  background: color,
                  transition: "width 0.6s cubic-bezier(0.16, 1, 0.3, 1)",
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Metric cell ───────────────────────────────────────────────────────────────

function MetricCell({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div>
      <span
        style={{
          display: "block",
          fontFamily: FONT_BODY,
          fontWeight: 700,
          fontSize: "10px",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "#000000",
          opacity: 0.45,
          marginBottom: "4px",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: FONT_FUTURA,
          fontWeight: 800,
          fontSize: "28px",
          letterSpacing: "-0.02em",
          color: "#000000",
          lineHeight: 1,
        }}
      >
        {value}
      </span>
      {unit && (
        <span
          style={{
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.08em",
            color: "#000000",
            opacity: 0.45,
            marginLeft: "4px",
            textTransform: "uppercase",
          }}
        >
          {unit}
        </span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function FinOpsDashboard() {
  const apiUrl = process.env.NEXT_PUBLIC_AEGIS_API_URL ?? "http://localhost:8080";

  const { data, error, isLoading } = useSWR<FinOpsReport>(
    `${apiUrl}/v1/analytics/finops`,
    fetcher,
    {
      refreshInterval: 30_000,     // 30s auto-revalidation
      revalidateOnFocus: true,
      shouldRetryOnError: true,
      errorRetryCount: 3,
      errorRetryInterval: 5_000,
    },
  );

  // ── Loading (no stale data available yet) ────────────────────────────────
  if (isLoading && !data) {
    return <SkeletonLayout />;
  }

  // ── Error (fetch failed, no stale data to show) ──────────────────────────
  if (error && !data) {
    return (
      <div
        style={{
          padding: "20px 0",
          display: "flex",
          alignItems: "center",
          gap: "12px",
        }}
        role="alert"
      >
        <div
          style={{
            width: "4px",
            height: "36px",
            background: "rgba(0,0,0,0.15)",
            flexShrink: 0,
          }}
        />
        <div>
          <span
            style={{
              display: "block",
              fontFamily: FONT_BODY,
              fontWeight: 700,
              fontSize: "10px",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "#000000",
              opacity: 0.35,
            }}
          >
            METRICS UNAVAILABLE — AEGIS V2 OFFLINE
          </span>
          <span
            style={{
              fontFamily: FONT_BODY,
              fontWeight: 700,
              fontSize: "10px",
              letterSpacing: "0.06em",
              color: "#000000",
              opacity: 0.25,
              textTransform: "uppercase",
            }}
          >
            Start the backend to see live FinOps data.
          </span>
        </div>
      </div>
    );
  }

  // ── No data yet (backend running but no Parquet files written yet) ────────
  if (data && !data.data_available) {
    return (
      <div style={{ padding: "20px 0" }}>
        <span
          style={{
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#000000",
            opacity: 0.35,
          }}
        >
          NO DATA YET — SEND REQUESTS TO /v1/infer TO POPULATE METRICS
        </span>
      </div>
    );
  }

  // ── Full metrics layout ───────────────────────────────────────────────────
  if (!data) return null;

  return (
    <div>
      {/* Section eyebrow */}
      <div
        className="incision-b"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          paddingBottom: "10px",
          marginBottom: "32px",
        }}
      >
        <span
          style={{
            fontFamily: FONT_FUTURA,
            fontWeight: 800,
            fontSize: "10px",
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "#000000",
          }}
        >
          LIVE IMPACT METRICS
        </span>
        <span
          style={{
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.08em",
            color: "#FF0000",
            textTransform: "uppercase",
          }}
        >
          AEGIS V2 — REALTIME
        </span>
      </div>

      {/* KPI Hero: total_cost_saved_usd */}
      <div className="incision-b" style={{ paddingBottom: "28px", marginBottom: "28px" }}>
        <span
          style={{
            display: "block",
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#000000",
            opacity: 0.45,
            marginBottom: "8px",
          }}
        >
          TOTAL COST SAVED
        </span>
        <span
          style={{
            fontFamily: FONT_FUTURA,
            fontWeight: 800,
            fontSize: "clamp(2rem, 4vw, 3.5rem)",
            letterSpacing: "-0.03em",
            lineHeight: 1,
            color: "#000000",
          }}
        >
          <KpiCounter target={data.total_cost_saved_usd} />
        </span>
        <span
          style={{
            display: "block",
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "#000000",
            opacity: 0.35,
            marginTop: "6px",
          }}
        >
          USD SAVED VS. FULL CLOUD ROUTING
        </span>
      </div>

      {/* Metrics grid: p99 + total_requests */}
      <div
        className="incision-b"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "40px",
          paddingBottom: "28px",
          marginBottom: "28px",
        }}
      >
        <MetricCell
          label="P99 LATENCY"
          value={data.p99_latency_ms.toFixed(1)}
          unit="ms"
        />
        <MetricCell
          label="TOTAL REQUESTS"
          value={data.total_requests.toLocaleString()}
        />
      </div>

      {/* Routing distribution bar chart */}
      <RoutingBarChart distribution={data.routing_distribution} />
    </div>
  );
}
