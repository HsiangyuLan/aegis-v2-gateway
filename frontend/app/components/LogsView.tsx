"use client";

/**
 * LogsView — Agent 推理日誌瀏覽器
 * 仿 agent_inference.jsonl 格式的終端機風格日誌檢視器。
 */

import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";

const MOCK_LOGS = [
  {
    ts: 1781080184327,
    action: "BLOCK",
    simulated_tokens: 150,
    confidence: 0.95,
    elapsed_ms: 3320.76,
    suspicious_ip: "192.168.1.105",
    event_type: "unknown",
    reasoning_steps: [
      "Step 1: The raw_log contains a SQL injection pattern ('OR 1=1--'), a common technique to bypass auth.",
      "Step 2: The suspicious IP (192.168.1.105) is flagged; request_count is 0 but payload indicates malicious intent.",
      "Step 3: event_type is 'unknown' but payload strongly suggests an attack attempt. BLOCK.",
    ],
  },
  {
    ts: 1781070874407,
    action: "BLOCK",
    simulated_tokens: 150,
    confidence: 0.95,
    elapsed_ms: 2336.98,
    suspicious_ip: "192.168.1.105",
    event_type: "unknown",
    reasoning_steps: [
      "Step 1: raw_log SQL injection pattern ('OR 1=1--') detected.",
      "Step 2: event_type 'unknown' — activity does not align with typical traffic patterns.",
      "Step 3: request_count is 0, but SQL injection payload is sufficient for high-confidence malicious classification.",
    ],
  },
  {
    ts: 1781070655483,
    action: "ALLOW",
    simulated_tokens: 75,
    confidence: 0.90,
    elapsed_ms: 3712.23,
    suspicious_ip: "",
    event_type: "unknown",
    reasoning_steps: [
      "Step 1: 'suspicious_ip' is empty — no specific IP flagged.",
      "Step 2: event_type is 'unknown', no additional context or evidence of malicious activity.",
      "Step 3: request_count is 0, raw_log is empty. Insufficient evidence to block. ALLOW.",
    ],
  },
  {
    ts: 1780964111001,
    action: "RATE_LIMIT",
    simulated_tokens: 360,
    confidence: 0.85,
    elapsed_ms: 2.44,
    suspicious_ip: "192.168.1.105",
    event_type: "SQL_INJECTION_ATTACK",
    reasoning_steps: [
      "[Step 1 / SOP 检索] event_type='SQL_INJECTION_ATTACK' → SOC2-CC6.1, NIST-IR.2 controls retrieved.",
      "[Step 2 / Payload 分析] IP=192.168.1.105, request_count=500, risk_level=HIGH",
      "[Step 3 / 決策] action=RATE_LIMIT, confidence=0.85",
    ],
  },
] as const;

const ACTION_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  BLOCK:      { color: "var(--danger)",         bg: "rgba(255,45,85,0.08)",    border: "rgba(255,45,85,0.3)"    },
  ALLOW:      { color: "var(--success)",        bg: "rgba(0,255,136,0.06)",    border: "rgba(0,255,136,0.25)"   },
  RATE_LIMIT: { color: "var(--warn)",           bg: "rgba(255,204,0,0.06)",    border: "rgba(255,204,0,0.25)"   },
  DEFAULT:    { color: "var(--text-secondary)", bg: "rgba(0,240,255,0.05)",    border: "rgba(0,240,255,0.2)"    },
};

function fmtTs(ms: number): string {
  return new Date(ms).toISOString().replace("T", " ").substring(0, 23);
}

export default function LogsView() {
  const [expanded, setExpanded] = useState<number | null>(0);

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
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 8, height: 8, background: "var(--neon)", boxShadow: "0 0 8px var(--neon)" }} />
          <span
            className="neon-text"
            style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.18em" }}
          >
            AGENT INFERENCE LOG
          </span>
          <span className="sv-label" style={{ fontSize: 9 }}>
            logs/finops/agent_inference.jsonl · {MOCK_LOGS.length} ENTRIES
          </span>
        </div>
        <div style={{ display: "flex", gap: 16 }}>
          {[
            { label: "BLOCK",      count: 2, color: "var(--danger)"  },
            { label: "ALLOW",      count: 1, color: "var(--success)" },
            { label: "RATE_LIMIT", count: 1, color: "var(--warn)"    },
          ].map(s => (
            <div key={s.label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  background: s.color,
                  boxShadow: `0 0 4px ${s.color}`,
                  flexShrink: 0,
                }}
              />
              <span style={{ color: s.color, fontSize: 9, letterSpacing: "0.1em" }}>
                {s.label} ×{s.count}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Log entries */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {MOCK_LOGS.map((log, i) => {
          const style = ACTION_STYLE[log.action] ?? ACTION_STYLE.DEFAULT;
          const isOpen = expanded === i;

          return (
            <motion.div
              key={log.ts}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.07 }}
              className="sv-glass-panel"
              style={{
                borderLeft: `3px solid ${style.color}`,
                overflow: "hidden",
                cursor: "pointer",
              }}
              onClick={() => setExpanded(isOpen ? null : i)}
            >
              {/* Summary row */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "220px 110px 80px 90px 100px 1fr 20px",
                  padding: "10px 16px",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span style={{ color: "var(--text-muted)", fontSize: 9, fontFamily: "monospace" }}>
                  {fmtTs(log.ts)}
                </span>

                <span
                  style={{
                    padding: "2px 8px",
                    background: style.bg,
                    border: `1px solid ${style.border}`,
                    color: style.color,
                    fontSize: 9,
                    letterSpacing: "0.12em",
                    fontWeight: 700,
                    display: "inline-block",
                    maxWidth: "fit-content",
                  }}
                >
                  {log.action}
                </span>

                <span style={{ color: "var(--text-secondary)", fontSize: 9 }}>
                  conf: <span style={{ color: "var(--neon)", fontWeight: 700 }}>{log.confidence}</span>
                </span>

                <span style={{ color: "var(--text-secondary)", fontSize: 9 }}>
                  {log.simulated_tokens} tok
                </span>

                <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
                  {log.elapsed_ms.toFixed(1)} ms
                </span>

                <span
                  style={{
                    color: log.suspicious_ip ? "var(--warn)" : "var(--text-muted)",
                    fontSize: 9,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {log.suspicious_ip ? `IP: ${log.suspicious_ip}` : "no suspicious IP"}
                  {log.event_type !== "unknown" && (
                    <span style={{ color: "var(--danger)", marginLeft: 8 }}>· {log.event_type}</span>
                  )}
                </span>

                <span
                  style={{
                    color: "var(--text-secondary)",
                    fontSize: 10,
                    textAlign: "right",
                    transition: "transform 0.2s",
                    transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
                    display: "inline-block",
                  }}
                >
                  ▶
                </span>
              </div>

              {/* Expanded reasoning steps */}
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    style={{ overflow: "hidden" }}
                  >
                    <div
                      style={{
                        padding: "10px 16px 14px",
                        borderTop: "1px solid var(--border)",
                        background: "rgba(0,0,0,0.25)",
                      }}
                    >
                      <div className="sv-label" style={{ fontSize: 8, marginBottom: 8 }}>
                        REASONING CHAIN · {log.reasoning_steps.length} STEPS
                      </div>
                      {log.reasoning_steps.map((step, j) => (
                        <motion.div
                          key={j}
                          initial={{ opacity: 0, x: -6 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: j * 0.06 }}
                          style={{
                            display: "flex",
                            gap: 10,
                            marginBottom: 6,
                            fontSize: 9,
                            lineHeight: 1.6,
                          }}
                        >
                          <span
                            style={{
                              color: style.color,
                              flexShrink: 0,
                              width: 14,
                              textAlign: "right",
                              fontWeight: 700,
                              marginTop: 1,
                            }}
                          >
                            {j + 1}.
                          </span>
                          <span style={{ color: "var(--text-secondary)" }}>{step}</span>
                        </motion.div>
                      ))}

                      {/* Raw JSON snippet */}
                      <details style={{ marginTop: 10 }}>
                        <summary
                          style={{
                            color: "var(--neon-dim)",
                            fontSize: 8,
                            letterSpacing: "0.1em",
                            cursor: "pointer",
                            userSelect: "none",
                          }}
                        >
                          RAW JSON ↓
                        </summary>
                        <pre
                          style={{
                            marginTop: 6,
                            padding: "8px 12px",
                            background: "rgba(0,0,0,0.4)",
                            border: "1px solid var(--border)",
                            color: "var(--neon-dim)",
                            fontSize: 8,
                            lineHeight: 1.5,
                            overflowX: "auto",
                            fontFamily: "monospace",
                          }}
                        >
                          {JSON.stringify(
                            {
                              timestamp_ms: log.ts,
                              action: log.action,
                              simulated_tokens: log.simulated_tokens,
                              confidence: log.confidence,
                              elapsed_ms: log.elapsed_ms,
                              suspicious_ip: log.suspicious_ip,
                              event_type: log.event_type,
                            },
                            null,
                            2
                          )}
                        </pre>
                      </details>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>

      {/* Footer */}
      <div
        style={{
          paddingTop: 4,
          display: "flex",
          justifyContent: "space-between",
          color: "var(--text-muted)",
          fontSize: 8,
          letterSpacing: "0.12em",
        }}
      >
        <span>SOURCE: logs/finops/agent_inference.jsonl</span>
        <span className="cursor-blink">LIVE · AUTO-REFRESH 30s</span>
      </div>
    </div>
  );
}
