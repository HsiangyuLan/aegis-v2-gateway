"use client";

/**
 * DashboardStats — SecOps 黃金指標即時輪詢元件
 * ================================================
 * 每 5 秒向 FastAPI `/api/dashboard/stats` 發送 fetch 請求，
 * 顯示三大黃金指標：total_blocked / total_cost_saved_usd / avg_confidence。
 *
 * 防禦性輪詢 (Defensive Polling) 設計原則
 * ─────────────────────────────────────────
 * - 後端掛掉或網路斷線時：保留最後一次成功的數據繼續渲染，
 *   右上角顯示「連線中斷」警示 badge，畫面絕不白屏。
 * - AbortController：元件卸載時立即中止進行中的 fetch，
 *   防止 unmounted 元件 setState 觸發 React 警告與 memory leak。
 * - clearInterval：元件卸載時清除計時器，確保輪詢徹底停止。
 *
 * 狀態機
 * ─────────────────────────────────────────
 * ① isLoading=true, data=null   → 骨架屏 (Tailwind animate-pulse)
 * ② data≠null, error≠null       → 舊數據 + 右上角斷線警示
 * ③ data=null, error≠null       → 內聯錯誤橫幅（不崩潰）
 * ④ data≠null, error=null       → 完整指標卡片
 *
 * 設計規範遵循 (spec.md)
 * ─────────────────────────────────────────
 * - 品牌色盤：#FF0000 / #FFFFFF / #000000
 * - border-radius: 0px（無圓角）
 * - 字型：Futura Heavy (--font-futura) / Inter Bold (--font-body)
 */

import { useCallback, useEffect, useRef, useState } from "react";

// ── API 資料合約（鏡像 app/api/dashboard.py DashboardStats）───────────────────

interface DashboardStatsData {
  /** 已攔截的 BLOCK 事件總數 */
  total_blocked: number;
  /** 節省的 USD 成本總和（精確到小數第二位） */
  total_cost_saved_usd: number;
  /** 防禦決策平均信心分數（0.0–1.0，精確到小數第二位） */
  avg_confidence: number;
}

// ── 輪詢間隔（毫秒）────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 5_000;

// ── 字型 CSS 變數（與設計規範對齊）────────────────────────────────────────────

const FONT_FUTURA =
  "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)";
const FONT_BODY = "var(--font-body, var(--font-mono, 'JetBrains Mono', monospace))";

// ── Sovereign Void 主題色盤（覆蓋原始黑白設計，與 page.tsx 暗色底融合）──────
const C_LABEL   = "var(--text-secondary, #4a8a9a)";
const C_MUTED   = "var(--text-muted,     #2a4a55)";
const C_PRIMARY = "var(--text-primary,   #c8eef5)";
const C_NEON    = "var(--neon,           #00F0FF)";
const C_DANGER  = "var(--danger,         #ff2d55)";
const C_SUCCESS = "var(--success,        #00ff88)";

// ── 骨架屏子元件（Tailwind animate-pulse，固定高度避免 CLS）──────────────────

function SkeletonCard() {
  return (
    <div
      className="animate-pulse"
      role="status"
      aria-label="載入指標中…"
    >
      {/* 標題列骨架 */}
      <div className="flex justify-between items-center mb-6">
        <div className="h-3 bg-white/10 w-36" />
        <div className="h-3 bg-white/10 w-20" />
      </div>

      {/* 三欄指標骨架 */}
      <div className="grid grid-cols-3 gap-6 mb-6">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <div className="h-2.5 bg-white/10 w-20" />
            <div className="h-9 bg-white/10 w-28" />
            <div className="h-2 bg-white/10 w-12" />
          </div>
        ))}
      </div>

      {/* 信心分數進度條骨架 */}
      <div className="space-y-1">
        <div className="h-2.5 bg-white/10 w-24" />
        <div className="h-1.5 bg-white/10 w-full" />
      </div>
    </div>
  );
}

// ── 斷線警示 Badge（疊加在右上角，不干擾正常數據渲染）─────────────────────────

function DisconnectBadge({ message }: { message: string }) {
  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: "4px 8px",
        background: "rgba(255,45,85,0.08)",
        border: "1px solid rgba(255,45,85,0.25)",
      }}
    >
      <span
        className="animate-pulse"
        style={{
          display: "inline-block",
          width: "6px",
          height: "6px",
          borderRadius: "50%",
          background: C_DANGER,
          flexShrink: 0,
        }}
        aria-hidden="true"
      />
      <span
        style={{
          fontFamily: FONT_BODY,
          fontWeight: 700,
          fontSize: "9px",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: C_DANGER,
        }}
      >
        連線中斷 — {message}
      </span>
    </div>
  );
}

// ── 單一指標卡片 ───────────────────────────────────────────────────────────────

function MetricBlock({
  label,
  value,
  unit,
  accent = false,
}: {
  label: string;
  value: string;
  unit?: string;
  /** 是否以 #FF0000 強調數值（用於關鍵指標） */
  accent?: boolean;
}) {
  return (
    <div>
      {/* 欄位標籤 */}
      <span
        style={{
          display: "block",
          fontFamily: FONT_BODY,
          fontWeight: 700,
          fontSize: "10px",
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: C_LABEL,
          marginBottom: "6px",
        }}
      >
        {label}
      </span>

      {/* 指標數值 */}
      <span
        style={{
          fontFamily: FONT_FUTURA,
          fontWeight: 800,
          fontSize: "clamp(1.5rem, 2.5vw, 2.25rem)",
          letterSpacing: "-0.02em",
          lineHeight: 1,
          color: accent ? C_DANGER : C_NEON,
          textShadow: accent
            ? `0 0 12px ${C_DANGER}`
            : `0 0 12px ${C_NEON}`,
        }}
      >
        {value}
      </span>

      {/* 單位標籤 */}
      {unit && (
        <span
          style={{
            display: "block",
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "9px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: C_MUTED,
            marginTop: "4px",
          }}
        >
          {unit}
        </span>
      )}
    </div>
  );
}

// ── 信心分數水平進度條 ──────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.min(Math.max(value * 100, 0), 100);
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: "6px",
        }}
      >
        <span
          style={{
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: C_LABEL,
          }}
        >
          AVG CONFIDENCE
        </span>
        <span
          style={{
            fontFamily: FONT_FUTURA,
            fontWeight: 800,
            fontSize: "10px",
            letterSpacing: "0.06em",
            color: C_NEON,
          }}
        >
          {(value * 100).toFixed(1)}%
        </span>
      </div>

      {/* 進度條軌道 */}
      <div
        style={{
          width: "100%",
          height: "4px",
          background: "rgba(0,240,255,0.08)",
          position: "relative",
        }}
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`平均信心分數 ${pct.toFixed(1)}%`}
      >
        {/* 填充條：CSS transition 保證平滑過渡 */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            height: "4px",
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${C_NEON} 0%, ${C_SUCCESS} 100%)`,
            boxShadow: `0 0 8px ${C_NEON}`,
            transition: "width 0.6s cubic-bezier(0.16, 1, 0.3, 1)",
          }}
        />
      </div>
    </div>
  );
}

// ── 主元件 ─────────────────────────────────────────────────────────────────────

export default function DashboardStats() {
  // 從環境變數讀取 API 基礎 URL，與 FinOpsDashboard 保持一致的設定來源。
  const apiBase =
    process.env.NEXT_PUBLIC_AEGIS_API_URL ?? "http://127.0.0.1:8000";

  const [data, setData] = useState<DashboardStatsData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // 使用 ref 儲存 AbortController，確保元件卸載時能立即中止進行中的 fetch。
  const abortRef = useRef<AbortController | null>(null);

  const fetchStats = useCallback(async () => {
    // 中止上一次尚未完成的 fetch（避免 race condition）
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${apiBase}/api/dashboard/stats`, {
        signal: controller.signal,
        // Cache 策略：不快取，每次輪詢均取最新數據。
        cache: "no-store",
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status} ${res.statusText}`);
      }

      const json = (await res.json()) as DashboardStatsData;

      // 成功：更新數據並清除錯誤狀態
      setData(json);
      setError(null);
    } catch (err: unknown) {
      // AbortError 代表元件已卸載，靜默忽略不更新 state（防止 React warning）
      if (err instanceof DOMException && err.name === "AbortError") return;

      // 其他錯誤：保留上一次成功的 data，僅標記錯誤（Fail-Closed 核心）
      const message =
        err instanceof Error ? err.message : "未知錯誤";
      setError(message);
    } finally {
      // 無論成敗，首次載入結束後關閉骨架屏
      setIsLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    // 立即執行首次 fetch
    void fetchStats();

    // 啟動 5 秒輪詢計時器
    const timerId = setInterval(() => {
      void fetchStats();
    }, POLL_INTERVAL_MS);

    // 元件卸載清理：取消計時器 + 中止進行中的 fetch
    return () => {
      clearInterval(timerId);
      abortRef.current?.abort();
    };
  }, [fetchStats]);

  // ── 狀態 ①：首次載入（尚無任何數據）→ 骨架屏 ───────────────────────────────
  if (isLoading && data === null) {
    return <SkeletonCard />;
  }

  // ── 狀態 ③：fetch 失敗且無歷史數據 → 內聯錯誤橫幅 ──────────────────────────
  if (error !== null && data === null) {
    return (
      <div
        role="alert"
        style={{
          padding: "16px",
          border: `1px solid rgba(255,45,85,0.25)`,
          background: "rgba(255,45,85,0.05)",
          display: "flex",
          alignItems: "center",
          gap: "12px",
        }}
      >
        {/* 左側警示縱線 */}
        <div
          style={{
            width: "3px",
            height: "40px",
            background: C_DANGER,
            boxShadow: `0 0 8px ${C_DANGER}`,
            flexShrink: 0,
          }}
          aria-hidden="true"
        />
        <div>
          <span
            style={{
              display: "block",
              fontFamily: FONT_BODY,
              fontWeight: 700,
              fontSize: "10px",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: C_DANGER,
              marginBottom: "4px",
            }}
          >
            DASHBOARD OFFLINE — 後端無回應
          </span>
          <span
            style={{
              fontFamily: FONT_BODY,
              fontSize: "10px",
              letterSpacing: "0.06em",
              color: C_MUTED,
            }}
          >
            {error} · 每 {POLL_INTERVAL_MS / 1000}s 自動重試中
          </span>
        </div>
      </div>
    );
  }

  // ── 狀態 ②④：有數據（可能帶舊數據 + 斷線警示）→ 完整指標 ──────────────────
  if (data === null) return null;

  return (
    <div style={{ position: "relative" }}>
      {/* ── 斷線警示：疊加於右上角，不遮擋指標內容 ────────────────────────── */}
      {error !== null && (
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
          }}
        >
          <DisconnectBadge message={error} />
        </div>
      )}

      {/* ── 標題列 ──────────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          paddingBottom: "10px",
          marginBottom: "20px",
          borderBottom: "1px solid rgba(0,240,255,0.1)",
          paddingRight: error !== null ? "160px" : "0",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            style={{
              width: "6px",
              height: "6px",
              background: C_NEON,
              boxShadow: `0 0 6px ${C_NEON}`,
            }}
          />
          <span
            style={{
              fontFamily: FONT_BODY,
              fontWeight: 700,
              fontSize: "10px",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: C_NEON,
            }}
          >
            SECOPS GOLDEN SIGNALS
          </span>
        </div>
        <span
          style={{
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "9px",
            letterSpacing: "0.12em",
            color: error !== null ? C_MUTED : C_SUCCESS,
            textTransform: "uppercase",
          }}
        >
          {error !== null ? "STALE DATA" : "LIVE · 5s"}
        </span>
      </div>

      {/* ── 三大黃金指標欄位（2 欄 + 信心分數條） ──────────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "40px",
          paddingBottom: "24px",
          marginBottom: "24px",
          borderBottom: "1px solid rgba(0,240,255,0.06)",
        }}
      >
        {/* 已攔截威脅數量（以紅色強調，因為是最重要的安全指標） */}
        <MetricBlock
          label="TOTAL BLOCKED"
          value={data.total_blocked.toLocaleString()}
          unit="THREATS INTERCEPTED"
          accent={true}
        />

        {/* 節省成本 */}
        <MetricBlock
          label="COST SAVED"
          value={`$${data.total_cost_saved_usd.toFixed(2)}`}
          unit="USD SAVED"
        />
      </div>

      {/* ── 平均信心分數進度條 ───────────────────────────────────────────── */}
      <ConfidenceBar value={data.avg_confidence} />

      {/* ── 底部時間戳記 ─────────────────────────────────────────────────── */}
      <div style={{ marginTop: "16px" }}>
        <span
          style={{
            fontFamily: FONT_BODY,
            fontWeight: 700,
            fontSize: "9px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: C_MUTED,
          }}
        >
          AUTO-REFRESH EVERY {POLL_INTERVAL_MS / 1000}S
          {error !== null && " · LAST KNOWN GOOD DATA SHOWN"}
        </span>
      </div>
    </div>
  );
}
