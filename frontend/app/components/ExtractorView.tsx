"use client";

/**
 * ExtractorView — 資料提取器 / 存取控制警告面板
 * 顯示 PII 提取規則、RBAC 角色政策，以及賽博龐克風格的存取授權矩陣。
 */

import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";

const EXTRACTION_RULES = [
  { id: "EXT-001", pattern: "\\b[A-Z0-9]{4}-\\d{4}\\b",     type: "TRANSACTION_ID",    hits: 1204, action: "REDACT",   risk: "MED"  },
  { id: "EXT-002", pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b",   type: "SSN_US",            hits:    3, action: "BLOCK",    risk: "CRIT" },
  { id: "EXT-003", pattern: "(?:4|5[1-5])[\\d ]{15}",       type: "CREDIT_CARD",       hits:    7, action: "BLOCK",    risk: "CRIT" },
  { id: "EXT-004", pattern: "[a-z0-9._%+]+@[a-z0-9.-]+",   type: "EMAIL_ADDR",        hits:  289, action: "REDACT",   risk: "LOW"  },
  { id: "EXT-005", pattern: "\\b(?:192\\.168|10\\.)\\S+",    type: "INTERNAL_IP",       hits:   92, action: "TOKENIZE", risk: "MED"  },
  { id: "EXT-006", pattern: "Bearer\\s[A-Za-z0-9+/=]{20,}", type: "BEARER_TOKEN",      hits:    0, action: "BLOCK",    risk: "CRIT" },
  { id: "EXT-007", pattern: "sk-[A-Za-z0-9]{32,}",          type: "API_SECRET_KEY",    hits:    0, action: "BLOCK",    risk: "CRIT" },
] as const;

const ACCESS_MATRIX = [
  { role: "OPERATOR_ID_001", read: true,  write: true,  exec: true,  admin: true,  tier: "ALPHA"  },
  { role: "SECOPS_AGENT",    read: true,  write: true,  exec: true,  admin: false, tier: "BETA"   },
  { role: "FINOPS_ANALYST",  read: true,  write: false, exec: false, admin: false, tier: "GAMMA"  },
  { role: "AUDIT_OBSERVER",  read: true,  write: false, exec: false, admin: false, tier: "DELTA"  },
  { role: "EXTERNAL_PROBE",  read: false, write: false, exec: false, admin: false, tier: "DENIED" },
] as const;

const RISK_COLOR: Record<string, string> = {
  CRIT: "var(--danger)",
  MED:  "var(--warn)",
  LOW:  "var(--text-secondary)",
};

const TIER_COLOR: Record<string, string> = {
  ALPHA:  "var(--neon)",
  BETA:   "var(--success)",
  GAMMA:  "var(--warn)",
  DELTA:  "var(--text-secondary)",
  DENIED: "var(--danger)",
};

function AccessCell({ allowed }: { allowed: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: 18,
        height: 18,
        background: allowed ? "rgba(0,255,136,0.15)" : "rgba(255,45,85,0.12)",
        border: `1px solid ${allowed ? "rgba(0,255,136,0.4)" : "rgba(255,45,85,0.3)"}`,
        color: allowed ? "var(--success)" : "var(--danger)",
        fontSize: 9,
        textAlign: "center",
        lineHeight: "18px",
      }}
    >
      {allowed ? "✓" : "✗"}
    </span>
  );
}

export default function ExtractorView() {
  const [selectedRule, setSelectedRule] = useState<string | null>("EXT-002");

  const selected = EXTRACTION_RULES.find(r => r.id === selectedRule);

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
          <div style={{ width: 8, height: 8, background: "var(--warn)", boxShadow: "0 0 8px var(--warn)" }} />
          <span
            style={{
              color: "var(--warn)",
              fontSize: 14,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textShadow: "0 0 10px var(--warn)",
            }}
          >
            DATA EXTRACTOR ENGINE
          </span>
        </div>
        <div
          style={{
            padding: "4px 12px",
            border: "1px solid rgba(255,45,85,0.4)",
            background: "rgba(255,45,85,0.08)",
            color: "var(--danger)",
            fontSize: 9,
            letterSpacing: "0.18em",
            fontWeight: 700,
          }}
        >
          ⚠ 4 CRITICAL PATTERNS ACTIVE
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, flex: 1, minHeight: 0 }}>
        {/* Left: extraction rules */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
          <div className="sv-glass-panel" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", background: "rgba(0,240,255,0.04)" }}>
              <span className="sv-label">EXTRACTION RULE REGISTRY · {EXTRACTION_RULES.length} ACTIVE</span>
            </div>

            <div style={{ overflowY: "auto", flex: 1 }}>
              {EXTRACTION_RULES.map((rule, i) => (
                <motion.div
                  key={rule.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: i * 0.05 }}
                  onClick={() => setSelectedRule(rule.id === selectedRule ? null : rule.id)}
                  whileHover={{ backgroundColor: "rgba(0,240,255,0.04)" }}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "70px 1fr 50px 80px 50px",
                    padding: "10px 14px",
                    borderBottom: "1px solid rgba(0,240,255,0.05)",
                    cursor: "pointer",
                    background: selectedRule === rule.id ? "rgba(0,240,255,0.07)" : "transparent",
                    borderLeft: selectedRule === rule.id ? "2px solid var(--neon)" : "2px solid transparent",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <span style={{ color: "var(--neon-dim)", fontSize: 9 }}>{rule.id}</span>
                  <span style={{ color: "var(--text-primary)", fontSize: 10, letterSpacing: "0.06em" }}>{rule.type}</span>
                  <span style={{ color: "var(--text-secondary)", fontSize: 10, textAlign: "right" }}>{rule.hits}</span>
                  <span
                    style={{
                      fontSize: 8,
                      letterSpacing: "0.12em",
                      color:
                        rule.action === "BLOCK"
                          ? "var(--danger)"
                          : rule.action === "REDACT"
                          ? "var(--warn)"
                          : "var(--text-secondary)",
                      textAlign: "center",
                    }}
                  >
                    {rule.action}
                  </span>
                  <span
                    style={{
                      fontSize: 8,
                      fontWeight: 700,
                      color: RISK_COLOR[rule.risk] ?? "var(--text-secondary)",
                      textAlign: "right",
                    }}
                  >
                    {rule.risk}
                  </span>
                </motion.div>
              ))}
            </div>
          </div>

          {/* Detail panel */}
          <AnimatePresence>
            {selected && (
              <motion.div
                className="sv-glass-panel"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                style={{ padding: "12px 14px", overflow: "hidden" }}
              >
                <div className="sv-label" style={{ marginBottom: 8 }}>RULE DETAIL · {selected.id}</div>
                <div
                  style={{
                    padding: "8px 12px",
                    background: "rgba(0,240,255,0.04)",
                    border: "1px solid var(--border)",
                    color: "var(--neon)",
                    fontSize: 10,
                    fontFamily: "monospace",
                    letterSpacing: "0.08em",
                    wordBreak: "break-all",
                  }}
                >
                  REGEX: {selected.pattern}
                </div>
                {selected.risk === "CRIT" && (
                  <div
                    style={{
                      marginTop: 8,
                      padding: "6px 10px",
                      background: "rgba(255,45,85,0.08)",
                      border: "1px solid rgba(255,45,85,0.3)",
                      color: "var(--danger)",
                      fontSize: 9,
                      letterSpacing: "0.12em",
                    }}
                  >
                    ⛔ CRITICAL — PAYLOAD MATCHED THIS PATTERN WILL HARD BLOCK UPSTREAM REQUEST
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Right: access control matrix */}
        <div className="sv-glass-panel" style={{ width: 340, flexShrink: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", background: "rgba(0,240,255,0.04)" }}>
            <span className="sv-label">RBAC ACCESS MATRIX</span>
          </div>

          {/* Matrix header */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 30px 30px 30px 30px 60px",
              padding: "8px 14px",
              borderBottom: "1px solid var(--border)",
              gap: 6,
            }}
          >
            {["ROLE", "R", "W", "X", "ADM", "TIER"].map(h => (
              <div key={h} className="sv-label" style={{ fontSize: 7, textAlign: h === "ROLE" ? "left" : "center" }}>{h}</div>
            ))}
          </div>

          {ACCESS_MATRIX.map((row, i) => (
            <motion.div
              key={row.role}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: i * 0.08 }}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 30px 30px 30px 30px 60px",
                padding: "9px 14px",
                borderBottom: i < ACCESS_MATRIX.length - 1 ? "1px solid rgba(0,240,255,0.05)" : "none",
                alignItems: "center",
                gap: 6,
                background: row.tier === "DENIED" ? "rgba(255,45,85,0.04)" : "transparent",
              }}
            >
              <span style={{ color: "var(--text-primary)", fontSize: 9, letterSpacing: "0.06em" }}>{row.role}</span>
              <div style={{ textAlign: "center" }}><AccessCell allowed={row.read}  /></div>
              <div style={{ textAlign: "center" }}><AccessCell allowed={row.write} /></div>
              <div style={{ textAlign: "center" }}><AccessCell allowed={row.exec}  /></div>
              <div style={{ textAlign: "center" }}><AccessCell allowed={row.admin} /></div>
              <span
                style={{
                  color: TIER_COLOR[row.tier] ?? "var(--text-secondary)",
                  fontSize: 8,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textAlign: "center",
                }}
              >
                {row.tier}
              </span>
            </motion.div>
          ))}

          <div
            style={{
              margin: 12,
              padding: "8px 10px",
              background: "rgba(255,204,0,0.06)",
              border: "1px solid rgba(255,204,0,0.25)",
              color: "var(--warn)",
              fontSize: 8,
              letterSpacing: "0.1em",
              lineHeight: 1.6,
            }}
          >
            ⚠ ACCESS POLICY ENFORCED AT ag-gateway LAYER · ZERO-TRUST MODEL · SOC2-CC6.1 COMPLIANT
          </div>
        </div>
      </div>
    </div>
  );
}
