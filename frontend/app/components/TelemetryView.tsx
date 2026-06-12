"use client";

/**
 * TelemetryView — 實時主機遙測監控儀表板
 * ================================================
 * 每 1000ms 向 FastAPI `/api/telemetry/live` 輪詢真實 psutil 指標。
 * 所有 Mock 假資料已全部清除。
 *
 * 動態特效
 * ─────────────────────────────────────────────────
 * ① 物理彈簧長條圖：motion.div animate={{ height }}
 *    transition={{ type:"spring", stiffness:100, damping:15 }} — 產生 Overshoot 慣性感
 * ② 能量流體特效：linear-gradient(to top, …) + flow-ribbon-v CSS keyframe
 *    最新一根長條圖持續向上充能流動
 * ③ 數字滾動動畫：useMotionValue → useSpring → useMotionValueEvent → state
 *    數字不生硬跳字，與長條彈簧同步流暢滾動
 * ④ 斷線倒塌：try-catch 捕捉 fetch 失敗
 *    → 整個面板邊框轉為暗紅色 offline-breath CSS animation
 *    → 所有長條圖 history 清零（spring 緩慢降至 0%）
 *    → 顯示 "OFFLINE" 文字 + 自動重試提示
 */

import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, useSpring, useMotionValueEvent } from "framer-motion";

// ── Types（鏡像後端 Pydantic LiveTelemetry）─────────────────────────────────────

interface LiveTelemetry {
  /** 真實 CPU 使用率（0.0–100.0） */
  cpu_percent: number;
  /** 已使用 RAM（MiB） */
  memory_used_mb: number;
  /** 總 RAM（MiB） */
  memory_total_mb: number;
  /** 自系統啟動後累計發送位元組數 */
  network_bytes_sent: number;
  /** 自系統啟動後累計接收位元組數 */
  network_bytes_recv: number;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const API_BASE =
  (process.env.NEXT_PUBLIC_AEGIS_API_URL as string | undefined) ??
  "http://127.0.0.1:8000";
const POLL_MS   = 1_000;
const HIST      = 20; // rolling window 筆數

/** Framer Motion 物理彈簧設定（Overshoot 慣性效果） */
const SPRING_BAR: Parameters<typeof motion.div>[0]["transition"] = {
  type: "spring",
  stiffness: 100,
  damping: 15,
};
/** 數字滾動彈簧（略硬，避免數值過度震盪） */
const SPRING_NUM = { stiffness: 80, damping: 18 };

const FONT_MONO = "var(--font-mono, 'JetBrains Mono', monospace)";

// ── AnimatedNumber ─────────────────────────────────────────────────────────────
// useMotionValue + useSpring + useMotionValueEvent 三層架構
// 確保每次 value 變更時，顯示數字以物理彈簧流暢滾動，不生硬跳字。

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  style?: React.CSSProperties;
}

function AnimatedNumber({ value, decimals = 1, style }: AnimatedNumberProps) {
  const mv     = useMotionValue(value);
  const spring = useSpring(mv, SPRING_NUM);
  const [displayed, setDisplayed] = useState(value.toFixed(decimals));

  // 每當外部 value 變更，推進 motion value → spring 追蹤
  useEffect(() => {
    mv.set(value);
  }, [value, mv]);

  // 訂閱 spring 變化，同步更新顯示文字（避免 MotionValue 作為 children 的型別問題）
  useMotionValueEvent(spring, "change", (v) => {
    setDisplayed(v.toFixed(decimals));
  });

  return <span style={style}>{displayed}</span>;
}

// ── MetricPanel ───────────────────────────────────────────────────────────────
// 單一指標面板：大數字 + 20 根物理彈簧長條圖 + 能量流體漸層特效

interface MetricPanelProps {
  label: string;
  unit: string;
  /** 以 big number 顯示的實際數值 */
  displayValue: number;
  displayDecimals: number;
  displaySuffix: string;
  /** 歷史數值陣列（長條圖自動對最大值等比縮放） */
  history: number[];
  barColor: string;
  glowColor: string;
  gradientFrom: string;
  gradientTo: string;
  offline: boolean;
}

function MetricPanel({
  label,
  unit,
  displayValue,
  displayDecimals,
  displaySuffix,
  history,
  barColor,
  glowColor,
  gradientFrom,
  gradientTo,
  offline,
}: MetricPanelProps) {
  const maxVal = Math.max(...history, 0.001);

  return (
    <div
      className="sv-glass-panel"
      style={{
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        // 斷線時套用 offline-breath CSS keyframe
        animation: offline ? "offline-breath 2.4s ease-in-out infinite" : "none",
        border: "1px solid",
        borderColor: offline ? "rgba(255,45,85,0.3)" : "rgba(0,240,255,0.14)",
      }}
    >
      {/* 標頭：指標標籤 + 單位 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span
          className="sv-label"
          style={{ color: offline ? "var(--danger)" : barColor }}
        >
          {offline ? "OFFLINE" : label}
        </span>
        <span style={{ color: "var(--text-muted)", fontSize: 8, letterSpacing: "0.1em" }}>
          {unit}
        </span>
      </div>

      {/* 大數字 + 彈簧滾動 */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <AnimatedNumber
          value={displayValue}
          decimals={displayDecimals}
          style={{
            fontFamily: FONT_MONO,
            fontWeight: 700,
            fontSize: 26,
            letterSpacing: "-0.02em",
            lineHeight: 1,
            color: offline ? "var(--danger)" : barColor,
            textShadow: offline
              ? "0 0 10px var(--danger)"
              : `0 0 10px ${glowColor}`,
          }}
        />
        <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: "var(--text-muted)" }}>
          {displaySuffix}
        </span>
      </div>

      {/* 20 根物理彈簧長條圖 + 能量流體特效 */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 2,
          height: 68,
        }}
      >
        {history.map((val, i) => {
          const pct        = (val / maxVal) * 100;
          const isLatest   = i === history.length - 1;
          const isHighload = pct > 72;

          return (
            <motion.div
              key={i}
              // 物理彈簧高度動畫：Overshoot 慣性效果
              animate={{ height: `${pct}%` }}
              transition={SPRING_BAR}
              style={{
                flex: 1,
                minHeight: 1,
                transformOrigin: "bottom",
                // 最新一根：能量流體漸層 + flow-ribbon-v 動畫
                background: isLatest
                  ? `linear-gradient(to top, ${gradientFrom}, ${gradientTo}, ${gradientFrom})`
                  : `linear-gradient(to top, ${gradientFrom}cc, ${gradientTo}44)`,
                backgroundSize: isLatest ? "100% 300%" : "100% 100%",
                animation: isLatest && !offline
                  ? "flow-ribbon-v 2s linear infinite"
                  : "none",
                boxShadow: isHighload
                  ? `0 0 5px ${glowColor}`
                  : "none",
              }}
            />
          );
        })}
      </div>

      {/* 底部進度軌跡 */}
      <div style={{ width: "100%", height: 1, background: "rgba(255,255,255,0.05)" }}>
        <motion.div
          animate={{ width: `${Math.min((history[history.length - 1] / maxVal) * 100, 100)}%` }}
          transition={SPRING_BAR}
          style={{
            height: 1,
            background: `linear-gradient(90deg, ${gradientFrom}, ${gradientTo})`,
            boxShadow: `0 0 4px ${glowColor}`,
          }}
        />
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function TelemetryView() {
  const [data,    setData]    = useState<LiveTelemetry | null>(null);
  const [offline, setOffline] = useState(false);

  // 20-sample 滾動歷史 — 全部從 0 開始（等待第一筆真實數據）
  const [cpuHist,     setCpuHist]     = useState<number[]>(new Array(HIST).fill(0));
  const [memHist,     setMemHist]     = useState<number[]>(new Array(HIST).fill(0));
  const [netSentHist, setNetSentHist] = useState<number[]>(new Array(HIST).fill(0));
  const [netRecvHist, setNetRecvHist] = useState<number[]>(new Array(HIST).fill(0));

  // 網路流量 KB/s 顯示值（每秒差值）
  const [netSentKBs, setNetSentKBs] = useState(0);
  const [netRecvKBs, setNetRecvKBs] = useState(0);

  // 前一次網路計數器（用於計算 delta）
  const prevNetRef = useRef<{ sent: number; recv: number } | null>(null);

  const pushHist = <T,>(setter: React.Dispatch<React.SetStateAction<T[]>>, val: T) => {
    setter((prev) => [...prev.slice(-(HIST - 1)), val]);
  };

  useEffect(() => {
    let cancelled = false;

    const fetchTelemetry = async () => {
      const ctrl = new AbortController();
      try {
        const res = await fetch(`${API_BASE}/api/telemetry/live`, {
          signal: ctrl.signal,
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const d = (await res.json()) as LiveTelemetry;
        if (cancelled) return;

        const memPct = (d.memory_used_mb / d.memory_total_mb) * 100;

        // 計算網路流量差值（KB/s）
        let sentDelta = 0;
        let recvDelta = 0;
        if (prevNetRef.current) {
          sentDelta = Math.max(0, (d.network_bytes_sent - prevNetRef.current.sent) / 1024);
          recvDelta = Math.max(0, (d.network_bytes_recv - prevNetRef.current.recv) / 1024);
        }
        prevNetRef.current = { sent: d.network_bytes_sent, recv: d.network_bytes_recv };

        setData(d);
        setOffline(false);
        setNetSentKBs(sentDelta);
        setNetRecvKBs(recvDelta);

        pushHist(setCpuHist,     d.cpu_percent);
        pushHist(setMemHist,     memPct);
        pushHist(setNetSentHist, sentDelta);
        pushHist(setNetRecvHist, recvDelta);

      } catch (err: unknown) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;

        // ── 斷線倒塌：所有長條圖 spring 緩降至 0 ──────────────────────────
        setOffline(true);
        setData(null);
        setCpuHist(new Array(HIST).fill(0));
        setMemHist(new Array(HIST).fill(0));
        setNetSentHist(new Array(HIST).fill(0));
        setNetRecvHist(new Array(HIST).fill(0));
        setNetSentKBs(0);
        setNetRecvKBs(0);
      }
    };

    void fetchTelemetry();
    const timer = setInterval(() => void fetchTelemetry(), POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const memPct = data ? (data.memory_used_mb / data.memory_total_mb) * 100 : 0;

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        padding: "20px 24px",
        gap: 16,
        overflowY: "auto",
        minHeight: 0,
      }}
    >
      {/* ── 標頭列 ────────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <motion.div
            animate={
              offline
                ? { opacity: [0.5, 1, 0.5], background: "var(--danger)" }
                : { opacity: 1, background: "var(--neon-purple)" }
            }
            transition={offline ? { repeat: Infinity, duration: 1.6, ease: "easeInOut" } : {}}
            style={{
              width: 8,
              height: 8,
              boxShadow: offline ? "0 0 8px var(--danger)" : "0 0 8px var(--neon-purple)",
            }}
          />
          <span
            style={{
              color: offline ? "var(--danger)" : "var(--neon-purple)",
              fontSize: 14,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textShadow: offline
                ? "0 0 10px var(--danger)"
                : "0 0 10px var(--neon-purple)",
            }}
          >
            {offline ? "⚠ TELEMETRY OFFLINE" : "TELEMETRY DASHBOARD"}
          </span>
          {!offline && (
            <span className="sv-label" style={{ fontSize: 9 }}>
              REAL-TIME psutil · {POLL_MS}MS POLL · HOST SYSTEM
            </span>
          )}
        </div>

        {/* 即時摘要數字 */}
        {data && !offline ? (
          <div style={{ display: "flex", gap: 28 }}>
            {[
              { label: "CPU",     val: data.cpu_percent,           unit: "%",  dec: 1 },
              { label: "MEM%",    val: memPct,                      unit: "%",  dec: 1 },
              { label: "RAM_USED",val: data.memory_used_mb / 1024,  unit: "GB", dec: 2 },
            ].map((s) => (
              <div key={s.label} style={{ textAlign: "center" }}>
                <div className="sv-label" style={{ fontSize: 8 }}>{s.label}</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 2, marginTop: 2 }}>
                  <AnimatedNumber
                    value={s.val}
                    decimals={s.dec}
                    style={{
                      color: "var(--neon)",
                      fontSize: 15,
                      fontWeight: 700,
                      fontFamily: FONT_MONO,
                    }}
                  />
                  <span style={{ color: "var(--text-muted)", fontSize: 9 }}>{s.unit}</span>
                </div>
              </div>
            ))}
          </div>
        ) : offline ? (
          <motion.div
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
            style={{
              padding: "4px 14px",
              border: "1px solid rgba(255,45,85,0.4)",
              background: "rgba(255,45,85,0.08)",
              color: "var(--danger)",
              fontSize: 9,
              letterSpacing: "0.2em",
              fontFamily: FONT_MONO,
              fontWeight: 700,
            }}
          >
            OFFLINE — RETRYING EVERY {POLL_MS}MS
          </motion.div>
        ) : (
          <span style={{ color: "var(--text-muted)", fontSize: 9, letterSpacing: "0.12em" }}>
            WAITING FOR FIRST SAMPLE…
          </span>
        )}
      </div>

      {/* ── 四格指標面板（2×2 grid）──────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>

        {/* CPU 使用率 */}
        <MetricPanel
          label="CPU_UTILISATION"
          unit="% · 1S SAMPLE"
          displayValue={data?.cpu_percent ?? 0}
          displayDecimals={1}
          displaySuffix="%"
          history={cpuHist}
          barColor="var(--neon)"
          glowColor="rgba(0,240,255,0.55)"
          gradientFrom="rgba(0,240,255,0.95)"
          gradientTo="rgba(0,240,255,0.2)"
          offline={offline}
        />

        {/* 記憶體壓力 */}
        <MetricPanel
          label="MEMORY_PRESSURE"
          unit="MiB · VIRTUAL"
          displayValue={data?.memory_used_mb ?? 0}
          displayDecimals={0}
          displaySuffix="MiB"
          history={memHist}
          barColor="var(--neon-purple)"
          glowColor="rgba(192,132,252,0.55)"
          gradientFrom="rgba(192,132,252,0.95)"
          gradientTo="rgba(192,132,252,0.2)"
          offline={offline}
        />

        {/* 網路發送 KB/s */}
        <MetricPanel
          label="NET_BYTES_SENT"
          unit="KB/s · Δ1S"
          displayValue={netSentKBs}
          displayDecimals={1}
          displaySuffix="KB/s"
          history={netSentHist}
          barColor="var(--success)"
          glowColor="rgba(0,255,136,0.55)"
          gradientFrom="rgba(0,255,136,0.95)"
          gradientTo="rgba(0,255,136,0.2)"
          offline={offline}
        />

        {/* 網路接收 KB/s */}
        <MetricPanel
          label="NET_BYTES_RECV"
          unit="KB/s · Δ1S"
          displayValue={netRecvKBs}
          displayDecimals={1}
          displaySuffix="KB/s"
          history={netRecvHist}
          barColor="var(--warn)"
          glowColor="rgba(255,204,0,0.55)"
          gradientFrom="rgba(255,204,0,0.95)"
          gradientTo="rgba(255,204,0,0.2)"
          offline={offline}
        />
      </div>

      {/* ── 累計計數器底欄（真實主機資料）──────────────────────────────────── */}
      {data && !offline && (
        <div
          className="sv-glass-panel"
          style={{
            padding: "10px 16px",
            display: "flex",
            gap: 32,
            flexWrap: "wrap",
          }}
        >
          {[
            { label: "TOTAL_NET_SENT",  val: `${(data.network_bytes_sent  / 1_073_741_824).toFixed(3)} GB` },
            { label: "TOTAL_NET_RECV",  val: `${(data.network_bytes_recv  / 1_073_741_824).toFixed(3)} GB` },
            { label: "MEM_TOTAL",        val: `${(data.memory_total_mb     / 1024).toFixed(2)} GB` },
            { label: "MEM_FREE",          val: `${((data.memory_total_mb - data.memory_used_mb) / 1024).toFixed(2)} GB` },
          ].map((s) => (
            <div key={s.label}>
              <div className="sv-label" style={{ fontSize: 8, marginBottom: 2 }}>{s.label}</div>
              <div style={{ color: "var(--text-secondary)", fontSize: 11, fontWeight: 700 }}>{s.val}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── 斷線橫幅（僅 offline 時顯示）──────────────────────────────────── */}
      {offline && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            padding: "16px",
            border: "1px solid rgba(255,45,85,0.25)",
            background: "rgba(255,45,85,0.05)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div
            style={{
              width: 3,
              height: 44,
              background: "var(--danger)",
              boxShadow: "0 0 8px var(--danger)",
              flexShrink: 0,
            }}
          />
          <div>
            <span
              style={{
                display: "block",
                color: "var(--danger)",
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                marginBottom: 4,
              }}
            >
              HOST TELEMETRY OFFLINE — ALL METRICS ZEROED
            </span>
            <span style={{ color: "var(--text-muted)", fontSize: 10, letterSpacing: "0.06em" }}>
              Cannot reach {API_BASE}/api/telemetry/live · Bars slowly settling to 0% · Auto-retry every {POLL_MS}ms
            </span>
          </div>
        </motion.div>
      )}
    </div>
  );
}
