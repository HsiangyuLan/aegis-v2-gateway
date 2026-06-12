"use client";

/**
 * LedgerView — FinOps 推理交易總帳（100% 真實 SQLite 資料）
 * ============================================================
 * 載入時 fetch `GET /api/ledger/history?limit=10&offset=0`，
 * 對接後端 aiosqlite finops_ledger.db。所有 Mock 假資料已全部清除。
 *
 * 動態特效
 * ─────────────────────────────────────────────────
 * ① 表格交錯淡入（Staggered Entrance）：
 *    Framer Motion variants + staggerChildren: 0.03s
 *    10 筆紀錄像骨牌般從下往上依序彈跳定位
 * ② Action 狀態高亮：
 *    BLOCK → --danger (紅)、ALLOW → --success (綠)、RATE_LIMIT → --warn (黃)
 * ③ 斷線動畫（Offline Glow）：
 *    fetch 失敗 → 面板邊框套用 offline-breath 呼吸動畫（暗紅色微弱呼吸）
 *    → 顯示 "DATABASE UNREACHABLE" 錯誤橫幅
 *
 * 型別定義與後端 Pydantic 100% 吻合：
 *   total_count, limit, offset, entries[{ id, timestamp, service,
 *   tokens, cost_usd, action, status }]
 */

import { useEffect, useState } from "react";
import { motion } from "framer-motion";

// ── Types（鏡像後端 Pydantic LedgerEntry / LedgerHistoryResponse）──────────────

interface LedgerEntry {
  /** 資料庫自動遞增主鍵 */
  id: number;
  /** ISO 8601 UTC 時間戳 */
  timestamp: string;
  /** 服務識別名稱，如 "secops_agent" */
  service: string;
  /** 本次推理消耗 tokens 數 */
  tokens: number;
  /** 換算 USD 成本（精確到小數第六位） */
  cost_usd: number;
  /** 防禦決策：BLOCK / ALLOW / RATE_LIMIT */
  action: string;
  /** 執行狀態："ok" / "error_fail_closed" */
  status: string;
}

interface LedgerHistoryResponse {
  /** 資料表總筆數（供分頁計算） */
  total_count: number;
  limit: number;
  offset: number;
  /** 本頁推理交易紀錄，依 timestamp DESC 排序 */
  entries: LedgerEntry[];
}

// ── Framer Motion Variants（Staggered Entrance）────────────────────────────────

const listVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.03,
      delayChildren: 0.05,
    },
  },
};

const rowVariants = {
  hidden: { opacity: 0, y: 18, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      type: "spring" as const,
      stiffness: 220,
      damping: 22,
    },
  },
};

// ── Action 樣式對照表（使用 Neon 設計系統 CSS 變數）──────────────────────────────

interface ActionStyle {
  bg: string;
  border: string;
  color: string;
}

const ACTION_STYLE: Record<string, ActionStyle> = {
  BLOCK: {
    bg:     "rgba(255,45,85,0.12)",
    border: "rgba(255,45,85,0.35)",
    color:  "var(--danger)",
  },
  ALLOW: {
    bg:     "rgba(0,255,136,0.08)",
    border: "rgba(0,255,136,0.25)",
    color:  "var(--success)",
  },
  RATE_LIMIT: {
    bg:     "rgba(255,204,0,0.10)",
    border: "rgba(255,204,0,0.30)",
    color:  "var(--warn)",
  },
};

const DEFAULT_ACTION_STYLE: ActionStyle = {
  bg:     "rgba(0,240,255,0.08)",
  border: "rgba(0,240,255,0.25)",
  color:  "var(--neon)",
};

/** 根據 action + status 決定 STATUS 欄位顯示色 */
function resolveStatusColor(status: string, action: string): string {
  if (status === "error_fail_closed") return "var(--warn)";
  switch (action) {
    case "BLOCK":      return "var(--danger)";
    case "ALLOW":      return "var(--success)";
    case "RATE_LIMIT": return "var(--warn)";
    default:            return "var(--neon)";
  }
}

/** 將 ISO 8601 時間戳格式化為 HH:MM:SS UTC */
function fmtTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour12: false,
      timeZone: "UTC",
    }) + " UTC";
  } catch {
    return iso.slice(11, 19);
  }
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function LedgerView() {
  const apiBase =
    (process.env.NEXT_PUBLIC_AEGIS_API_URL as string | undefined) ??
    "http://127.0.0.1:8000";

  const [response,   setResponse]   = useState<LedgerHistoryResponse | null>(null);
  const [offline,    setOffline]    = useState(false);
  const [loading,    setLoading]    = useState(true);
  // refreshKey 變更 → 觸發重新 fetch + 骨牌動畫重播
  const [refreshKey, setRefreshKey] = useState(0);

  // ── 監聽全域 refresh-ledger 事件（由 EXECUTE_SEQUENCE 按鈕觸發）──────────
  useEffect(() => {
    const handler = () => {
      setRefreshKey((k) => k + 1);
    };
    window.addEventListener("refresh-ledger", handler);
    return () => window.removeEventListener("refresh-ledger", handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    // 每次 refreshKey 變更時重置狀態，顯示骨架屏後以骨牌動畫呈現新資料
    setLoading(true);
    setOffline(false);

    const loadLedger = async () => {
      try {
        const res = await fetch(
          `${apiBase}/api/ledger/history?limit=10&offset=0`,
          { cache: "no-store" }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
        const data = (await res.json()) as LedgerHistoryResponse;
        if (!cancelled) {
          setResponse(data);
          setOffline(false);
        }
      } catch {
        if (!cancelled) setOffline(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void loadLedger();
    return () => { cancelled = true; };
  }, [apiBase, refreshKey]);

  // ── 從真實 entries 計算摘要統計 ────────────────────────────────────────────
  const entries = response?.entries ?? [];
  const blockedCount    = entries.filter((e) => e.action === "BLOCK").length;
  const allowedCount    = entries.filter((e) => e.action === "ALLOW").length;
  const totalCostOnPage = entries.reduce((acc, e) => acc + e.cost_usd, 0);

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
      {/* ── 標頭 ────────────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <motion.div
            animate={
              offline
                ? { opacity: [0.5, 1, 0.5], background: "var(--danger)" }
                : { opacity: 1, background: "var(--neon)" }
            }
            transition={offline ? { repeat: Infinity, duration: 2, ease: "easeInOut" } : {}}
            style={{
              width: 8,
              height: 8,
              boxShadow: offline ? "0 0 8px var(--danger)" : "0 0 8px var(--neon)",
            }}
          />
          <span
            className={offline ? "" : "neon-text"}
            style={{
              fontSize: 14,
              fontWeight: 700,
              letterSpacing: "0.18em",
              color: offline ? "var(--danger)" : undefined,
              textShadow: offline ? "0 0 10px var(--danger)" : undefined,
            }}
          >
            {offline ? "⚠ LEDGER OFFLINE" : "FINOPS COST LEDGER"}
          </span>
          <span className="sv-label" style={{ fontSize: 9, marginLeft: 4 }}>
            {offline
              ? "CANNOT REACH DATABASE"
              : "COMPUTE ARBITRAGE AUDIT · finops_ledger.db · SQLITE"}
          </span>
        </div>

        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {!offline && !loading && <span className="status-dot" />}
          <span
            style={{
              color: offline
                ? "var(--danger)"
                : loading
                ? "var(--text-muted)"
                : "var(--success)",
              fontSize: 9,
              letterSpacing: "0.15em",
            }}
          >
            {offline ? "OFFLINE" : loading ? "LOADING…" : `${response?.total_count ?? 0} TOTAL RECORDS`}
          </span>
        </div>
      </div>

      {/* ── 摘要統計（從真實 entries 計算）─────────────────────────────────── */}
      {response && !offline && (
        <motion.div
          className="sv-glass-panel"
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 200, damping: 20 }}
          style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 1 }}
        >
          {[
            {
              label: "TOTAL_DB_RECORDS",
              val:   response.total_count.toString(),
              color: "var(--text-primary)",
            },
            {
              label: "BLOCKED (PAGE)",
              val:   blockedCount.toString(),
              color: "var(--danger)",
            },
            {
              label: "ALLOWED (PAGE)",
              val:   allowedCount.toString(),
              color: "var(--success)",
            },
            {
              label: "PAGE_COST_USD",
              val:   `$${totalCostOnPage.toFixed(6)}`,
              color: "var(--neon)",
            },
          ].map((s, i) => (
            <div
              key={s.label}
              style={{
                padding: "10px 14px",
                borderRight: i < 3 ? "1px solid var(--border)" : "none",
              }}
            >
              <div className="sv-label" style={{ fontSize: 8, marginBottom: 4 }}>
                {s.label}
              </div>
              <div style={{ color: s.color, fontSize: 16, fontWeight: 700 }}>
                {s.val}
              </div>
            </div>
          ))}
        </motion.div>
      )}

      {/* ── 資料表 ──────────────────────────────────────────────────────────── */}
      <div
        className="sv-glass-panel"
        style={{
          flex: 1,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          border: "1px solid",
          borderColor: "rgba(0,240,255,0.14)",
          // 斷線時套用 offline-breath CSS keyframe
          animation: offline ? "offline-breath 2.4s ease-in-out infinite" : "none",
        }}
      >
        {/* 欄位標頭 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "110px 160px 70px 110px 110px 70px",
            padding: "10px 16px",
            borderBottom: "1px solid var(--border)",
            background: "rgba(0,240,255,0.04)",
            flexShrink: 0,
          }}
        >
          {["TIMESTAMP", "SERVICE", "TOKENS", "COST_USD", "ACTION", "STATUS"].map((h) => (
            <div key={h} className="sv-label" style={{ fontSize: 8 }}>
              {h}
            </div>
          ))}
        </div>

        {/* 內容區域 */}
        <div style={{ flex: 1, overflowY: "auto" }}>

          {/* 骨架屏載入中 */}
          {loading && (
            <div className="animate-pulse" style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 4 }}>
              {[...Array(6)].map((_, i) => (
                <div
                  key={i}
                  style={{
                    height: 34,
                    background: "rgba(0,240,255,0.04)",
                    border: "1px solid rgba(0,240,255,0.05)",
                  }}
                />
              ))}
            </div>
          )}

          {/* 空白狀態：資料庫無紀錄 */}
          {!loading && !offline && entries.length === 0 && (
            <div
              className="cursor-blink"
              style={{
                padding: "28px 16px",
                color: "var(--text-muted)",
                fontSize: 10,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
              }}
            >
              NO LEDGER ENTRIES — RUN A SECOPS INFERENCE TO POPULATE DATABASE
            </div>
          )}

          {/* ── 主體：交錯淡入骨牌動畫 ──────────────────────────────────── */}
          {!loading && !offline && entries.length > 0 && (
            <motion.div
              key={refreshKey}
              variants={listVariants}
              initial="hidden"
              animate="visible"
            >
              {entries.map((entry) => {
                const aStyle = ACTION_STYLE[entry.action] ?? DEFAULT_ACTION_STYLE;
                return (
                  <motion.div
                    key={entry.id}
                    variants={rowVariants}
                    whileHover={{ backgroundColor: "rgba(0,240,255,0.035)" }}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "110px 160px 70px 110px 110px 70px",
                      padding: "9px 16px",
                      borderBottom: "1px solid rgba(0,240,255,0.05)",
                      cursor: "default",
                      alignItems: "center",
                    }}
                  >
                    {/* 時間戳 */}
                    <span style={{ color: "var(--text-muted)", fontSize: 9, letterSpacing: "0.04em" }}>
                      {fmtTs(entry.timestamp)}
                    </span>

                    {/* 服務名稱 */}
                    <span
                      style={{
                        color: "var(--text-primary)",
                        fontSize: 10,
                        letterSpacing: "0.06em",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {entry.service}
                    </span>

                    {/* Tokens */}
                    <span
                      style={{
                        color: "var(--text-secondary)",
                        fontSize: 10,
                        textAlign: "right",
                        paddingRight: 12,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {entry.tokens.toLocaleString()}
                    </span>

                    {/* Cost USD */}
                    <span
                      style={{
                        color: "var(--text-secondary)",
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      ${entry.cost_usd.toFixed(6)}
                    </span>

                    {/* Action Badge — Neon 高亮 */}
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "2px 8px",
                        background: aStyle.bg,
                        border: `1px solid ${aStyle.border}`,
                        color: aStyle.color,
                        fontSize: 8,
                        letterSpacing: "0.15em",
                        fontWeight: 700,
                        maxWidth: "fit-content",
                      }}
                    >
                      {entry.action}
                    </span>

                    {/* Status */}
                    <span
                      style={{
                        color: resolveStatusColor(entry.status, entry.action),
                        fontSize: 9,
                        letterSpacing: "0.1em",
                        fontWeight: 700,
                        textTransform: "uppercase",
                      }}
                    >
                      {entry.status}
                    </span>
                  </motion.div>
                );
              })}
            </motion.div>
          )}

          {/* ── 斷線橫幅（offline-breath 邊框已由父層處理）──────────────── */}
          {offline && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              style={{
                padding: "24px 16px",
                display: "flex",
                alignItems: "center",
                gap: 14,
              }}
            >
              <div
                style={{
                  width: 3,
                  height: 48,
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
                  DATABASE UNREACHABLE — PANEL IN OFFLINE GLOW MODE
                </span>
                <span style={{ color: "var(--text-muted)", fontSize: 10, letterSpacing: "0.06em" }}>
                  Cannot reach {apiBase}/api/ledger/history · Check if FastAPI is running on port 8000
                </span>
              </div>
            </motion.div>
          )}

        </div>
      </div>

      {/* ── 頁尾資訊（真實分頁狀態）────────────────────────────────────────── */}
      {response && !offline && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            color: "var(--text-muted)",
            fontSize: 8,
            letterSpacing: "0.12em",
            paddingTop: 4,
          }}
        >
          <span>
            COST MODEL: GPT-4o OUTPUT $0.000267/1K TOKENS · SOURCE: finops_ledger.db (aiosqlite)
          </span>
          <span>
            PAGE 1 OF {Math.ceil((response.total_count || 1) / 10)} · SHOWING {entries.length} / {response.total_count} RECORDS
          </span>
        </div>
      )}
    </div>
  );
}
