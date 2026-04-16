"use client";

/**
 * AEGIS V2.5 — Project Sovereign
 * Cyber-FinOps Command Center
 * ─────────────────────────────────────────────────────────────────────────────
 * Layout:
 *   TopBar      — status strip (version, latency, uptime, operator ID, clock)
 *   LeftSidebar — tactical navigation + EXECUTE_SEQUENCE button
 *   Center      — R3F 3D wireframe sphere (mouse-tracked) + capital overlay
 *   RightTop    — system integrity bar chart
 *   AssetBar    — 4 Framer Motion asset cards (BTC / ETH / SOL / LINK)
 *   BottomLeft  — transaction feed
 *   BottomRight — PII scan log (live → NEXT_PUBLIC_AEGIS_API_URL)
 *   StatusBar   — ticker tape
 *
 * 3D Strategy:
 *   Mouse X/Y mapped to sphere rotation via frame-based lerp inside useFrame.
 *   mouseRef avoids React re-renders on every mousemove — only the rAF loop
 *   reads it.  This keeps the rest of the UI at 60 fps.
 */

import {
  useRef,
  useEffect,
  useState,
  useCallback,
  Suspense,
} from "react";
import { ArbitrageOverview } from "./components/command/ArbitrageOverview";
import { Canvas, useFrame } from "@react-three/fiber";
import { Edges, Stars } from "@react-three/drei";
import { motion, AnimatePresence } from "framer-motion";
import useSWR from "swr";
import * as THREE from "three";

// ── Environment ───────────────────────────────────────────────────────────────

const API =
  (process.env.NEXT_PUBLIC_AEGIS_API_URL as string | undefined) ??
  "http://localhost:8080";

// ── Static data ───────────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { id: "terminal",  label: "TERMINAL",  icon: "▶" },
  { id: "ledger",    label: "LEDGER",    icon: "≡" },
  { id: "telemetry", label: "TELEMETRY", icon: "⟁" },
  { id: "extractor", label: "EXTRACTOR", icon: "⌗" },
  { id: "vault",     label: "VAULT",     icon: "⊕" },
  { id: "logs",      label: "LOGS",      icon: "⊚" },
] as const;

const ASSETS = [
  { pair: "BTC/USD",  price: "$64,102.11", spread: "0.0012%", trend: "▲", up: true  as boolean | null },
  { pair: "ETH/USD",  price: "$3,421.90",  spread: "0.0024%", trend: "→", up: null  as boolean | null },
  { pair: "SOL/USD",  price: "$145.12",    spread: "0.0041%", trend: "▼", up: false as boolean | null },
  { pair: "LINK/USD", price: "$18.94",     spread: "0.0008%", trend: "▲", up: true  as boolean | null },
];

const MOCK_TXS = [
  { time: "04:12:01", action: "BUY BTC",  value: "0.0412 BTC", usd: null,         ok: true  },
  { time: "04:11:58", action: "STAKE SOL", value: "104.00 SOL", usd: null,         ok: true  },
  { time: "04:11:58", action: "WITHDRAW",  value: null,          usd: "-$2,000.00", ok: false },
];

const TICKER_ITEMS = [
  "■ SYS_EVENT: BLOCK_19283746_VERIFIED",
  "■ ARB_EXEC: FLASH_LOAN_ACTIVE_3.2M",
  "■ NODE_OFFLINE: SHARD_004_PING_FAIL",
  "■ LIQUIDITY_DEPTH: +0.42%",
  "■ ENTROPY_SCORE: 0.312 → LOCAL_EDGE",
  "■ CIRCUIT_BREAKER: CLOSED [3/3]",
  "■ PII_SCAN: 2 MATCHES DETECTED",
];

// SSR-safe static bar heights (no Math.random in render)
const INTEGRITY_BARS = [60,72,55,80,90,75,88,65,78,92,70,85,58,95,82,74,88,62,91,77];

// ── SWR fetcher ───────────────────────────────────────────────────────────────

const jsonFetcher = (url: string) =>
  fetch(url).then(r => r.json()).catch(() => null);

// ─────────────────────────────────────────────────────────────────────────────
// 3D Wireframe Sphere (must live inside <Canvas>)
// ─────────────────────────────────────────────────────────────────────────────

interface WireframeSphereProps {
  mouseRef: React.MutableRefObject<{ x: number; y: number }>;
}

function WireframeSphere({ mouseRef }: WireframeSphereProps) {
  const groupRef = useRef<THREE.Group>(null!);
  const geo = new THREE.SphereGeometry(1.75, 28, 28);

  useFrame((_state, delta) => {
    if (!groupRef.current) return;
    const t = mouseRef.current;
    // Exponential lerp: speed = 1 - 0.04^delta ≈ 12% per frame at 60fps
    const k = 1 - Math.pow(0.04, delta);
    groupRef.current.rotation.y +=
      (t.x * Math.PI * 0.6 - groupRef.current.rotation.y) * k;
    groupRef.current.rotation.x +=
      (-t.y * Math.PI * 0.35 - groupRef.current.rotation.x) * k;
    // Slow auto-drift when cursor is near centre
    if (Math.abs(t.x) < 0.05 && Math.abs(t.y) < 0.05) {
      groupRef.current.rotation.y += delta * 0.07;
    }
  });

  return (
    <group ref={groupRef}>
      {/* Inner depth shell */}
      <mesh geometry={geo}>
        <meshBasicMaterial
          color="#001820"
          transparent
          opacity={0.45}
          side={THREE.BackSide}
        />
      </mesh>

      {/* Sparse wireframe grid */}
      <mesh geometry={geo}>
        <meshBasicMaterial
          color="#00F0FF"
          wireframe
          transparent
          opacity={0.18}
        />
      </mesh>

      {/* High-contrast edge lines via Edges helper */}
      <Edges geometry={geo} threshold={10}>
        <lineBasicMaterial color="#00F0FF" transparent opacity={0.55} />
      </Edges>

      {/* Equatorial ring */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.75, 0.006, 8, 80]} />
        <meshBasicMaterial color="#00F0FF" transparent opacity={0.75} />
      </mesh>

      {/* Polar ring */}
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <torusGeometry args={[1.75, 0.004, 8, 80]} />
        <meshBasicMaterial color="#00F0FF" transparent opacity={0.35} />
      </mesh>

      {/* Core glow light */}
      <pointLight color="#00F0FF" intensity={3} distance={5} decay={2} />
    </group>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TopBar
// ─────────────────────────────────────────────────────────────────────────────

function TopBar() {
  const [time, setTime] = useState("--:--:--");

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      setTime(`${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      style={{
        height: 40,
        background: "rgba(0,10,18,0.95)",
        borderBottom: "1px solid rgba(0,240,255,0.18)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
        flexShrink: 0,
        zIndex: 10,
      }}
    >
      {/* Left cluster */}
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <span
          style={{
            color: "#00F0FF",
            fontWeight: 700,
            fontSize: 13,
            letterSpacing: "0.15em",
          }}
        >
          AEGIS V2.5
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="status-dot" />
          <span style={{ color: "#00ff88", fontSize: 10, letterSpacing: "0.18em" }}>
            STATUS: ACTIVE
          </span>
        </div>
        <span style={{ color: "#4a8a9a", fontSize: 10, letterSpacing: "0.12em" }}>
          LATENCY: 14MS
        </span>
        <span style={{ color: "#4a8a9a", fontSize: 10, letterSpacing: "0.12em" }}>
          UPTIME: 99.9%
        </span>
      </div>

      {/* Right cluster */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span
          style={{ color: "#2a6a7a", fontSize: 10, letterSpacing: "0.1em" }}
          suppressHydrationWarning
        >
          {time}
        </span>
        <div
          style={{
            border: "1px solid rgba(0,240,255,0.3)",
            padding: "2px 10px",
            fontSize: 10,
            letterSpacing: "0.12em",
            color: "#00F0FF",
          }}
        >
          OPERATOR_ID_001
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LeftSidebar
// ─────────────────────────────────────────────────────────────────────────────

interface LeftSidebarProps {
  activeNav: string;
  setActiveNav: (id: string) => void;
}

function LeftSidebar({ activeNav, setActiveNav }: LeftSidebarProps) {
  return (
    <div
      style={{
        width: 200,
        flexShrink: 0,
        borderRight: "1px solid rgba(0,240,255,0.1)",
        display: "flex",
        flexDirection: "column",
        background: "rgba(0,6,12,0.8)",
      }}
    >
      {/* Brand mark */}
      <div
        style={{
          padding: "20px 16px 16px",
          borderBottom: "1px solid rgba(0,240,255,0.08)",
        }}
      >
        <div
          style={{
            color: "#c8eef5",
            fontWeight: 700,
            fontSize: 14,
            letterSpacing: "0.12em",
          }}
        >
          SOVEREIGN
        </div>
        <div
          style={{
            color: "#2a6a7a",
            fontSize: 9,
            letterSpacing: "0.2em",
            marginTop: 2,
          }}
        >
          V2.5 INSTRUMENT
        </div>
      </div>

      {/* Navigation */}
      <nav style={{ flex: 1, paddingTop: 12 }}>
        {NAV_ITEMS.map(item => (
          <motion.button
            key={item.id}
            onClick={() => setActiveNav(item.id)}
            whileHover={{ x: 3 }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              width: "100%",
              padding: "10px 16px",
              background:
                activeNav === item.id ? "rgba(0,240,255,0.1)" : "transparent",
              border: "none",
              borderLeft:
                activeNav === item.id
                  ? "2px solid #00F0FF"
                  : "2px solid transparent",
              color: activeNav === item.id ? "#00F0FF" : "#4a8a9a",
              fontSize: 11,
              letterSpacing: "0.15em",
              cursor: "pointer",
              fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
              textAlign: "left",
            }}
          >
            <span style={{ fontSize: 13, opacity: 0.8 }}>{item.icon}</span>
            {item.label}
          </motion.button>
        ))}
      </nav>

      {/* Execute button + reboot/exit */}
      <div style={{ padding: 12 }}>
        <motion.button
          whileHover={{
            boxShadow:
              "0 0 20px rgba(0,240,255,0.5), inset 0 0 12px rgba(0,240,255,0.1)",
            backgroundColor: "rgba(0,240,255,0.15)",
          }}
          whileTap={{ scale: 0.97 }}
          transition={{ duration: 0.15 }}
          style={{
            width: "100%",
            padding: "10px 0",
            background: "rgba(0,240,255,0.06)",
            border: "1px solid rgba(0,240,255,0.4)",
            color: "#00F0FF",
            fontSize: 10,
            letterSpacing: "0.2em",
            cursor: "pointer",
            fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
            fontWeight: 700,
          }}
        >
          EXECUTE_SEQUENCE
        </motion.button>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: 8,
          }}
        >
          {["↺ REBOOT", "→ EXIT"].map(label => (
            <button
              key={label}
              style={{
                background: "none",
                border: "none",
                color: "#2a6a7a",
                fontSize: 9,
                letterSpacing: "0.12em",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// System Integrity Chart
// ─────────────────────────────────────────────────────────────────────────────

function SystemIntegrityChart() {
  return (
    <div style={{ height: "100%" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 10,
        }}
      >
        <span className="sv-label">SYSTEM_INTEGRITY</span>
        <span style={{ color: "#00ff88", fontSize: 10, letterSpacing: "0.15em" }}>
          SLA: 99.998%
        </span>
      </div>

      {/* Bar chart */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 3,
          height: 70,
        }}
      >
        {INTEGRITY_BARS.map((h, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height: `${h}%`,
              background:
                "linear-gradient(to top, rgba(0,240,255,0.85) 0%, rgba(0,240,255,0.3) 100%)",
              boxShadow:
                h > 80 ? "0 0 4px rgba(0,240,255,0.6)" : "none",
              transformOrigin: "bottom",
              animation: `bar-rise 0.35s ease-out ${i * 0.025}s both`,
            }}
          />
        ))}
      </div>

      {/* Mini stats */}
      <div
        style={{
          marginTop: 10,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
        }}
      >
        {[
          { label: "CORE_ENGINE", val: "OPERATIONAL", ok: true  },
          { label: "MEM_LEAK",    val: "0.00%",       ok: true  },
        ].map(r => (
          <div key={r.label}>
            <div
              style={{
                color: "#2a6a7a",
                fontSize: 9,
                letterSpacing: "0.12em",
              }}
            >
              {r.label}
            </div>
            <div
              style={{
                color: r.ok ? "#00ff88" : "#ff2d55",
                fontSize: 10,
                letterSpacing: "0.08em",
                marginTop: 1,
              }}
            >
              {r.val}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Asset Card
// ─────────────────────────────────────────────────────────────────────────────

interface AssetCardProps {
  pair: string;
  price: string;
  spread: string;
  trend: string;
  up: boolean | null;
}

function AssetCard({ pair, price, spread, trend, up }: AssetCardProps) {
  const trendColor =
    up === true ? "#00ff88" : up === false ? "#ff2d55" : "#4a8a9a";

  return (
    <motion.div
      whileHover={{
        y: -3,
        boxShadow:
          "0 0 18px rgba(0,240,255,0.25), inset 0 0 12px rgba(0,240,255,0.06)",
        borderColor: "rgba(0,240,255,0.4)",
      }}
      transition={{ type: "spring", stiffness: 450, damping: 28 }}
      style={{
        padding: "14px 16px",
        background: "var(--bg-panel)",
        border: "1px solid rgba(0,240,255,0.1)",
        cursor: "pointer",
        height: "100%",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <span className="sv-label" style={{ fontSize: 9 }}>
          {pair}
        </span>
        <span style={{ color: trendColor, fontSize: 11 }}>{trend}</span>
      </div>

      <div
        style={{
          color: "#c8eef5",
          fontSize: 18,
          fontWeight: 700,
          letterSpacing: "-0.01em",
          marginBottom: 6,
        }}
      >
        {price}
      </div>

      <div
        style={{
          color: "#2a6a7a",
          fontSize: 9,
          letterSpacing: "0.12em",
        }}
      >
        SPREAD: {spread}
      </div>

      {/* Spread indicator bar */}
      <div
        style={{
          marginTop: 8,
          height: 1,
          background: "rgba(0,240,255,0.08)",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: "45%",
            height: 1,
            background: trendColor,
            boxShadow: `0 0 4px ${trendColor}`,
          }}
        />
      </div>
    </motion.div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Transaction Feed
// ─────────────────────────────────────────────────────────────────────────────

function TransactionFeed() {
  return (
    <div
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <span className="sv-label" style={{ marginBottom: 12 }}>
        TRANSACTION_FEED
      </span>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {MOCK_TXS.map((tx, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}
            whileHover={{
              borderColor: "rgba(0,240,255,0.3)",
              backgroundColor: "rgba(0,240,255,0.04)",
            }}
            style={{
              padding: "10px 14px",
              background: "rgba(0,12,20,0.8)",
              border: "1px solid rgba(0,240,255,0.08)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              cursor: "default",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <span style={{ color: "#2a6a7a", fontSize: 9 }}>{tx.time}</span>
              <span
                style={{
                  color: "#c8eef5",
                  fontSize: 10,
                  letterSpacing: "0.1em",
                  fontWeight: 700,
                }}
              >
                {tx.action}
              </span>
            </div>
            <div style={{ textAlign: "right" }}>
              <div
                style={{
                  color:
                    tx.usd && tx.usd.startsWith("-")
                      ? "#ff2d55"
                      : "#c8eef5",
                  fontSize: 11,
                  letterSpacing: "0.05em",
                  fontWeight: 700,
                }}
              >
                {tx.value ?? tx.usd}
              </div>
              <div
                style={{
                  color: tx.ok ? "#00ff88" : "#ff2d55",
                  fontSize: 8,
                  letterSpacing: "0.15em",
                }}
              >
                SUCCESS
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PII Scan Feed
// ─────────────────────────────────────────────────────────────────────────────

interface PiiMatch {
  pii_type: string;
  start: number;
  end: number;
}

interface ScanEntry {
  ts: number;
  input: string;
  pii_matches: PiiMatch[];
  status: string;
}

interface FinOpsData {
  total_requests?: number;
  total_cost_saved_usd?: number;
  p99_latency_ms?: number;
}

function PiiScanFeed() {
  const [scanInput, setScanInput] = useState("");
  const [log, setLog]             = useState<ScanEntry[]>([]);
  const [loading, setLoading]     = useState(false);

  const { data: finops } = useSWR<FinOpsData>(
    `${API}/v1/analytics/finops`,
    jsonFetcher,
    {
      refreshInterval: 8000,
      fallbackData: {
        total_requests:       1337,
        total_cost_saved_usd: 0.004182,
        p99_latency_ms:       12.4,
      },
    }
  );

  const doScan = useCallback(async () => {
    if (!scanInput.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/v1/analytics/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: scanInput }),
      });
      const data = await res.json() as { pii_matches?: PiiMatch[]; status?: string };
      setLog(prev =>
        [
          {
            ts: Date.now(),
            input: scanInput,
            pii_matches: data.pii_matches ?? [],
            status: data.status ?? "ok",
          },
          ...prev,
        ].slice(0, 14)
      );
    } catch {
      setLog(prev =>
        [
          {
            ts: Date.now(),
            input: scanInput,
            pii_matches: [],
            status: "ENGINE_OFFLINE",
          },
          ...prev,
        ].slice(0, 14)
      );
    } finally {
      setLoading(false);
    }
  }, [scanInput]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") doScan();
  };

  return (
    <div
      style={{ height: "100%", display: "flex", flexDirection: "column", gap: 10 }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <span className="sv-label">PII_SCAN_ENGINE</span>
        <span
          style={{
            color: finops ? "#00ff88" : "#ff2d55",
            fontSize: 8,
            letterSpacing: "0.15em",
          }}
        >
          {finops ? "LIVE" : "OFFLINE"}
        </span>
      </div>

      {/* FinOps mini-stats */}
      {finops && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3,1fr)",
            gap: 4,
          }}
        >
          {[
            {
              label: "REQUESTS",
              val: finops.total_requests?.toLocaleString() ?? "—",
            },
            {
              label: "SAVED_USD",
              val: `$${(finops.total_cost_saved_usd ?? 0).toFixed(4)}`,
            },
            {
              label: "P99_MS",
              val: `${finops.p99_latency_ms ?? 0}ms`,
            },
          ].map(s => (
            <div
              key={s.label}
              style={{
                background: "rgba(0,10,18,0.8)",
                border: "1px solid rgba(0,240,255,0.1)",
                padding: "5px 7px",
              }}
            >
              <div
                style={{
                  color: "#2a6a7a",
                  fontSize: 8,
                  letterSpacing: "0.15em",
                }}
              >
                {s.label}
              </div>
              <div
                style={{
                  color: "#00F0FF",
                  fontSize: 11,
                  fontWeight: 700,
                  marginTop: 1,
                }}
              >
                {s.val}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Input */}
      <div style={{ display: "flex", gap: 6 }}>
        <input
          value={scanInput}
          onChange={e => setScanInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="INJECT PAYLOAD…"
          style={{
            flex: 1,
            background: "rgba(0,6,12,0.9)",
            border: "1px solid rgba(0,240,255,0.2)",
            color: "#c8eef5",
            fontSize: 10,
            letterSpacing: "0.08em",
            padding: "6px 10px",
            fontFamily:
              "var(--font-mono, 'JetBrains Mono', monospace)",
          }}
        />
        <motion.button
          whileHover={{ boxShadow: "0 0 12px rgba(0,240,255,0.4)" }}
          whileTap={{ scale: 0.96 }}
          onClick={() => { void doScan(); }}
          disabled={loading}
          style={{
            padding: "0 14px",
            background: loading
              ? "rgba(0,240,255,0.04)"
              : "rgba(0,240,255,0.1)",
            border: "1px solid rgba(0,240,255,0.35)",
            color: "#00F0FF",
            fontSize: 9,
            letterSpacing: "0.18em",
            cursor: loading ? "wait" : "pointer",
            fontFamily: "inherit",
            fontWeight: 700,
          }}
        >
          {loading ? "…" : "SCAN"}
        </motion.button>
      </div>

      {/* Log entries */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 3,
        }}
      >
        <AnimatePresence>
          {log.map(entry => (
            <motion.div
              key={entry.ts}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              style={{
                padding: "7px 10px",
                background:
                  entry.pii_matches.length > 0
                    ? "rgba(255,45,85,0.06)"
                    : "rgba(0,10,18,0.7)",
                border: `1px solid ${
                  entry.pii_matches.length > 0
                    ? "rgba(255,45,85,0.2)"
                    : "rgba(0,240,255,0.07)"
                }`,
                fontSize: 9,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  marginBottom: 3,
                }}
              >
                <span style={{ color: "#2a6a7a" }}>
                  {new Date(entry.ts).toLocaleTimeString("en-US", {
                    hour12: false,
                  })}
                </span>
                <span
                  style={{
                    color:
                      entry.pii_matches.length > 0
                        ? "#ff2d55"
                        : "#00ff88",
                    letterSpacing: "0.12em",
                  }}
                >
                  {entry.pii_matches.length > 0
                    ? `${entry.pii_matches.length} MATCH(ES)`
                    : "CLEAN"}
                </span>
              </div>

              <div
                style={{
                  color: "#4a8a9a",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {entry.input}
              </div>

              {entry.pii_matches.length > 0 && (
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 4,
                    marginTop: 4,
                  }}
                >
                  {entry.pii_matches.map((m, j) => (
                    <span
                      key={j}
                      style={{
                        background: "rgba(255,45,85,0.12)",
                        border: "1px solid rgba(255,45,85,0.3)",
                        color: "#ff2d55",
                        padding: "1px 5px",
                        fontSize: 8,
                        letterSpacing: "0.12em",
                      }}
                    >
                      {m.pii_type} [{m.start}:{m.end}]
                    </span>
                  ))}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {log.length === 0 && (
          <div
            className="cursor-blink"
            style={{
              color: "#2a6a7a",
              fontSize: 9,
              letterSpacing: "0.12em",
              padding: "8px 0",
            }}
          >
            AWAITING INPUT
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Status Ticker
// ─────────────────────────────────────────────────────────────────────────────

function StatusTicker() {
  const doubled = [...TICKER_ITEMS, ...TICKER_ITEMS];
  return (
    <div
      style={{
        height: 26,
        background: "rgba(0,4,8,0.95)",
        borderTop: "1px solid rgba(0,240,255,0.1)",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 40,
          whiteSpace: "nowrap",
          animation: "ticker-scroll 24s linear infinite",
          willChange: "transform",
        }}
      >
        {doubled.map((item, i) => (
          <span
            key={i}
            style={{
              color:
                item.includes("OFFLINE") || item.includes("FAIL")
                  ? "#ff2d55"
                  : "#2a6a7a",
              fontSize: 9,
              letterSpacing: "0.15em",
            }}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────────────────────────────────

export default function SovereignPage() {
  const [activeNav, setActiveNav] = useState("terminal");
  const mouseRef = useRef({ x: 0, y: 0 });

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      mouseRef.current = {
        x: (e.clientX / window.innerWidth  - 0.5) * 2,
        y: (e.clientY / window.innerHeight - 0.5) * 2,
      };
    },
    []
  );

  return (
    <div
      onMouseMove={handleMouseMove}
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        fontFamily:
          "var(--font-mono, 'JetBrains Mono', monospace)",
        background: "var(--bg-void, #050505)",
        color: "var(--text-primary, #c8eef5)",
        userSelect: "none",
      }}
    >
      <TopBar />

      {/* ── Body row ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <LeftSidebar activeNav={activeNav} setActiveNav={setActiveNav} />

        {/* ── Main content column ── */}
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {/* ── Top row: 3D Globe + Integrity ── */}
          <div
            style={{
              flexShrink: 0,
              display: "flex",
              borderBottom: "1px solid rgba(0,240,255,0.08)",
            }}
          >
            {/* Center: globe + capital */}
            <div
              style={{
                flex: 1,
                position: "relative",
                height: 260,
                borderRight: "1px solid rgba(0,240,255,0.08)",
                overflow: "hidden",
                background:
                  "radial-gradient(ellipse at center, #020d18 0%, #050505 70%)",
              }}
            >
              {/* Section label */}
              <div
                style={{
                  position: "absolute",
                  top: 14,
                  left: 18,
                  zIndex: 2,
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <div
                  style={{
                    width: 6,
                    height: 6,
                    background: "#00F0FF",
                    boxShadow: "0 0 6px #00F0FF",
                  }}
                />
                <span className="sv-label">TOTAL_CAPITAL_ALLOCATION</span>
              </div>

              {/* R3F Canvas */}
              <Suspense fallback={null}>
                <Canvas
                  camera={{ position: [0, 0, 5.5], fov: 42 }}
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: "transparent",
                  }}
                  gl={{ alpha: true, antialias: true }}
                >
                  <Stars
                    radius={90}
                    depth={60}
                    count={2500}
                    factor={3}
                    fade
                    speed={0.4}
                  />
                  <ambientLight intensity={0.03} />
                  <WireframeSphere mouseRef={mouseRef} />
                </Canvas>
              </Suspense>

              {/* Capital text overlay */}
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  pointerEvents: "none",
                  zIndex: 2,
                }}
              >
                <div
                  className="neon-text-lg"
                  style={{
                    fontSize: "clamp(36px, 5vw, 62px)",
                    fontWeight: 700,
                    letterSpacing: "-0.02em",
                    lineHeight: 1,
                    animation: "neon-pulse 3s ease-in-out infinite",
                  }}
                >
                  $14,892.44
                </div>
              </div>

              {/* Bottom stats row */}
              <div
                style={{
                  position: "absolute",
                  bottom: 14,
                  left: 18,
                  right: 18,
                  display: "flex",
                  gap: 28,
                  zIndex: 3,
                  pointerEvents: "none",
                }}
              >
                {[
                  { label: "DELTA_24H",       val: "+12.42%", color: "#00ff88" },
                  { label: "VOLATILITY_INDEX", val: "0.14",   color: "#c8eef5" },
                  { label: "NODES_ONLINE",     val: "1,402",  color: "#c8eef5" },
                ].map(s => (
                  <div key={s.label}>
                    <div
                      className="sv-label"
                      style={{ fontSize: 8, marginBottom: 2 }}
                    >
                      {s.label}
                    </div>
                    <div
                      style={{
                        color: s.color,
                        fontSize: 14,
                        fontWeight: 700,
                        letterSpacing: "0.02em",
                      }}
                    >
                      {s.val}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: system integrity */}
            <div
              style={{
                width: 280,
                flexShrink: 0,
                padding: "14px 16px",
                background: "var(--bg-panel)",
              }}
            >
              <SystemIntegrityChart />
            </div>
          </div>

          <ArbitrageOverview apiBase={API} />

          {/* ── Asset bar ── */}
          <div
            style={{
              flexShrink: 0,
              display: "flex",
              borderBottom: "1px solid rgba(0,240,255,0.08)",
            }}
          >
            {ASSETS.map((a, i) => (
              <div
                key={a.pair}
                style={{
                  flex: 1,
                  borderRight:
                    i < ASSETS.length - 1
                      ? "1px solid rgba(0,240,255,0.08)"
                      : "none",
                }}
              >
                <AssetCard {...a} />
              </div>
            ))}
          </div>

          {/* ── Bottom row: transactions + PII feed ── */}
          <div
            style={{
              flex: 1,
              display: "flex",
              overflow: "hidden",
              minHeight: 0,
            }}
          >
            {/* Transactions */}
            <div
              style={{
                flex: 1,
                padding: "14px 16px",
                borderRight: "1px solid rgba(0,240,255,0.08)",
                overflow: "hidden",
              }}
            >
              <TransactionFeed />
            </div>

            {/* PII scan */}
            <div
              style={{
                width: 380,
                flexShrink: 0,
                padding: "14px 16px",
                overflow: "hidden",
                background: "rgba(0,4,8,0.5)",
              }}
            >
              <PiiScanFeed />
            </div>
          </div>
        </div>
      </div>

      <StatusTicker />
    </div>
  );
}
