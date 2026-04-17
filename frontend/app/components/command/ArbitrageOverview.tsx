"use client";

/**
 * Visa & TCO Arbitrage Overview — Cyber-FinOps narrative KPIs (portfolio display).
 * Data from GET /v1/analytics/finops (Rust ag-gateway or FastAPI).
 */

import useSWR from "swr";

const jsonFetcher = (url: string) =>
  fetch(url).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });

export interface FinOpsArbitragePayload {
  visa_tariff_exemption_usd?: number;
  compute_arbitrage_annual_usd?: number;
  assumptions?: {
    cache_hit_rate?: number;
    baseline_hourly_gpu_usd?: number;
    rust_speedup_factor?: number;
  };
}

interface ArbitrageOverviewProps {
  apiBase: string;
}

export function ArbitrageOverview({ apiBase }: ArbitrageOverviewProps) {
  const { data, error, isLoading } = useSWR<FinOpsArbitragePayload>(
    `${apiBase}/v1/analytics/finops`,
    jsonFetcher,
    { refreshInterval: 12_000 }
  );

  const visa = data?.visa_tariff_exemption_usd ?? 100_000;
  const arb = data?.compute_arbitrage_annual_usd ?? 90_000;
  const hit = data?.assumptions?.cache_hit_rate ?? 0.8;
  const gpu = data?.assumptions?.baseline_hourly_gpu_usd ?? 3.5;
  const speed = data?.assumptions?.rust_speedup_factor ?? 2.5;

  return (
    <div
      className="sv-glass-panel sv-glow-purple"
      style={{
        flexShrink: 0,
        padding: "14px 20px",
        borderBottom: "1px solid rgba(0,240,255,0.14)",
        background:
          "linear-gradient(105deg, rgba(0,24,40,0.88) 0%, rgba(24,8,40,0.55) 45%, rgba(0,8,16,0.92) 100%)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 10,
        }}
      >
        <div
          style={{
            width: 6,
            height: 6,
            background: "#ff2d55",
            boxShadow: "0 0 8px #ff2d55",
          }}
        />
        <span
          className="sv-label"
          style={{ letterSpacing: "0.22em", color: "#ff2d55" }}
        >
          VISA &amp; TCO ARBITRAGE OVERVIEW
        </span>
        {error && (
          <span style={{ color: "#2a6a7a", fontSize: 9, marginLeft: 8 }}>
            OFFLINE — STATIC KPI
          </span>
        )}
        {isLoading && !data && (
          <span style={{ color: "#2a6a7a", fontSize: 9, marginLeft: 8 }}>
            SYNC…
          </span>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr minmax(200px, 1fr)",
          gap: 14,
          alignItems: "stretch",
        }}
      >
        <div
          style={{
            border: "1px solid rgba(0,240,255,0.28)",
            padding: "14px 16px",
            background: "rgba(0,12,22,0.75)",
            boxShadow: "0 0 24px rgba(0, 240, 255, 0.06), inset 0 1px 0 rgba(255,255,255,0.04)",
          }}
        >
          <div
            style={{
              color: "#2a6a7a",
              fontSize: 9,
              letterSpacing: "0.18em",
              marginBottom: 6,
            }}
          >
            $100K H-1B TARIFF EXEMPTION (F-1 COS NARRATIVE)
          </div>
          <div
            style={{
              color: "#00F0FF",
              fontSize: "clamp(22px, 3vw, 32px)",
              fontWeight: 800,
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            ${visa.toLocaleString("en-US", { maximumFractionDigits: 0 })}
          </div>
          <div
            style={{
              color: "#4a8a9a",
              fontSize: 9,
              marginTop: 8,
              letterSpacing: "0.08em",
              lineHeight: 1.4,
            }}
          >
            F-1 COS applicant portfolio thesis — illustrative only, not legal or tax advice.
          </div>
        </div>

        <div
          style={{
            border: "1px solid rgba(192,132,252,0.35)",
            padding: "14px 16px",
            background: "rgba(12,8,22,0.75)",
            boxShadow: "0 0 28px rgba(168, 85, 247, 0.12), inset 0 1px 0 rgba(255,255,255,0.04)",
          }}
        >
          <div
            style={{
              color: "#2a6a7a",
              fontSize: 9,
              letterSpacing: "0.18em",
              marginBottom: 6,
            }}
          >
            &gt;$90K/YR ANNUAL COMPUTE ARBITRAGE
          </div>
          <div
            style={{
              color: "#00ff88",
              fontSize: "clamp(22px, 3vw, 32px)",
              fontWeight: 800,
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            &gt;${arb.toLocaleString("en-US", { maximumFractionDigits: 0 })}/yr
          </div>
          <div
            style={{
              color: "#4a8a9a",
              fontSize: 9,
              marginTop: 8,
              letterSpacing: "0.08em",
            }}
          >
            Model: 80% cache hit + Rust FFI speedup vs GPU baseline (see assumptions).
          </div>
        </div>

        <div
          style={{
            border: "1px solid rgba(0,240,255,0.12)",
            padding: "10px 12px",
            fontSize: 9,
            color: "#4a8a9a",
            letterSpacing: "0.1em",
            lineHeight: 1.6,
            fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
          }}
        >
          <div style={{ color: "#2a6a7a", marginBottom: 4 }}>ASSUMPTIONS</div>
          <div>CACHE_HIT_RATE: {(hit * 100).toFixed(0)}%</div>
          <div>BASELINE_GPU_USD_HR: ${gpu.toFixed(2)}</div>
          <div>RUST_SPEEDUP_FACTOR: {speed.toFixed(2)}×</div>
        </div>
      </div>
    </div>
  );
}
