"use client";

/**
 * VaultView — 秘密金庫 / 加密狀態儀表板
 * 賽博龐克風格的金鑰存儲、加密狀態指示，以及存取層級警告。
 */

import { motion } from "framer-motion";

const VAULT_ENTRIES = [
  { id: "VLT-001", name: "GEMINI_API_KEY",        type: "API_KEY",     status: "ENCRYPTED",  algo: "AES-256-GCM", rotated: "2d ago",   access: 2  },
  { id: "VLT-002", name: "OPENAI_API_KEY",         type: "API_KEY",     status: "ENCRYPTED",  algo: "AES-256-GCM", rotated: "1d ago",   access: 1  },
  { id: "VLT-003", name: "JWT_SECRET",             type: "SIGNING_KEY", status: "ENCRYPTED",  algo: "HS-512",      rotated: "7d ago",   access: 3  },
  { id: "VLT-004", name: "DB_CONNECTION_STRING",   type: "CREDENTIAL",  status: "ENCRYPTED",  algo: "AES-256-GCM", rotated: "14d ago",  access: 1  },
  { id: "VLT-005", name: "RUST_FFI_SHARED_SECRET", type: "FFI_KEY",     status: "ENCRYPTED",  algo: "ChaCha20",    rotated: "3h ago",   access: 1  },
  { id: "VLT-006", name: "SENTRY_AUTH_TOKEN",      type: "TOKEN",       status: "EXPIRED",    algo: "AES-256-GCM", rotated: "30d ago",  access: 0  },
  { id: "VLT-007", name: "POSTHOG_API_KEY",        type: "API_KEY",     status: "ENCRYPTED",  algo: "AES-256-GCM", rotated: "5d ago",   access: 4  },
] as const;

const ENCRYPTION_LAYERS = [
  { layer: "L1 · APPLICATION",  algo: "AES-256-GCM",   status: "ACTIVE", coverage: 100 },
  { layer: "L2 · TRANSPORT",    algo: "TLS 1.3",       status: "ACTIVE", coverage: 100 },
  { layer: "L3 · STORAGE",      algo: "FIPS 140-2",    status: "ACTIVE", coverage: 100 },
  { layer: "L4 · KEY ROTATION", algo: "AUTOMATED",     status: "ACTIVE", coverage:  86 },
  { layer: "L5 · AUDIT LOG",    algo: "HMAC-SHA256",   status: "ACTIVE", coverage: 100 },
] as const;

const STATUS_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  ENCRYPTED: {
    color:  "var(--success)",
    bg:     "rgba(0,255,136,0.08)",
    border: "rgba(0,255,136,0.3)",
  },
  EXPIRED: {
    color:  "var(--danger)",
    bg:     "rgba(255,45,85,0.08)",
    border: "rgba(255,45,85,0.3)",
  },
  ROTATING: {
    color:  "var(--warn)",
    bg:     "rgba(255,204,0,0.08)",
    border: "rgba(255,204,0,0.3)",
  },
};

function CoverageBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={{ height: 4, background: "rgba(255,255,255,0.06)", flex: 1, position: "relative" }}>
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.7, ease: "easeOut" }}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          height: "100%",
          background: color,
          boxShadow: pct === 100 ? `0 0 6px ${color}` : "none",
        }}
      />
    </div>
  );
}

export default function VaultView() {
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
          <div style={{ width: 8, height: 8, background: "var(--success)", boxShadow: "0 0 8px var(--success)" }} />
          <span
            style={{
              color: "var(--success)",
              fontSize: 14,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textShadow: "0 0 10px var(--success)",
            }}
          >
            SECRET VAULT
          </span>
          <span className="sv-label" style={{ fontSize: 9 }}>ENCRYPTED KEY STORE · SOC2-CC6.7</span>
        </div>
        <motion.div
          animate={{ opacity: [1, 0.5, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
          style={{
            padding: "4px 12px",
            border: "1px solid rgba(0,255,136,0.4)",
            background: "rgba(0,255,136,0.06)",
            color: "var(--success)",
            fontSize: 9,
            letterSpacing: "0.18em",
            fontWeight: 700,
          }}
        >
          🔒 VAULT SEALED · AES-256-GCM
        </motion.div>
      </div>

      {/* Warning banner */}
      <motion.div
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        style={{
          padding: "10px 16px",
          background: "rgba(255,45,85,0.06)",
          border: "1px solid rgba(255,45,85,0.25)",
          borderLeft: "3px solid var(--danger)",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span style={{ color: "var(--danger)", fontSize: 14 }}>⛔</span>
        <div>
          <div style={{ color: "var(--danger)", fontSize: 10, fontWeight: 700, letterSpacing: "0.12em" }}>
            ACCESS RESTRICTED — CLEARANCE LEVEL ALPHA REQUIRED
          </div>
          <div style={{ color: "var(--text-muted)", fontSize: 9, letterSpacing: "0.1em", marginTop: 2 }}>
            Unauthorised inspection attempts will be logged and reported to OPERATOR_ID_001 · Session ID: {"{"}SID-4F9A-C3E1{"}"}
          </div>
        </div>
      </motion.div>

      <div style={{ display: "flex", gap: 16, flex: 1, minHeight: 0 }}>
        {/* Vault entries */}
        <div className="sv-glass-panel" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "70px 1fr 90px 110px 80px 70px 70px",
              padding: "10px 14px",
              borderBottom: "1px solid var(--border)",
              background: "rgba(0,240,255,0.04)",
              gap: 4,
            }}
          >
            {["ID", "SECRET_NAME", "TYPE", "ALGORITHM", "STATUS", "ROTATED", "ACCESS"].map(h => (
              <div key={h} className="sv-label" style={{ fontSize: 7 }}>{h}</div>
            ))}
          </div>

          <div style={{ overflowY: "auto", flex: 1 }}>
            {VAULT_ENTRIES.map((entry, i) => {
              const s = STATUS_STYLE[entry.status] ?? STATUS_STYLE.ENCRYPTED;
              return (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.06 }}
                  whileHover={{ backgroundColor: "rgba(0,240,255,0.03)" }}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "70px 1fr 90px 110px 80px 70px 70px",
                    padding: "10px 14px",
                    borderBottom: "1px solid rgba(0,240,255,0.05)",
                    alignItems: "center",
                    gap: 4,
                    cursor: "default",
                  }}
                >
                  <span style={{ color: "var(--neon-dim)", fontSize: 9 }}>{entry.id}</span>
                  <span style={{ color: "var(--text-primary)", fontSize: 10, letterSpacing: "0.06em" }}>
                    {/* Mask the key value */}
                    {entry.name.replace(/./g, (c, j) => j < 4 ? c : "•")}
                    <span style={{ color: "var(--text-muted)", fontSize: 8, marginLeft: 6 }}>
                      [{entry.name.length} chars]
                    </span>
                  </span>
                  <span style={{ color: "var(--text-secondary)", fontSize: 9 }}>{entry.type}</span>
                  <span style={{ color: "var(--neon)", fontSize: 9, fontFamily: "monospace" }}>{entry.algo}</span>
                  <span
                    style={{
                      padding: "2px 7px",
                      background: s.bg,
                      border: `1px solid ${s.border}`,
                      color: s.color,
                      fontSize: 8,
                      letterSpacing: "0.1em",
                      display: "inline-block",
                      maxWidth: "fit-content",
                    }}
                  >
                    {entry.status}
                  </span>
                  <span style={{ color: "var(--text-muted)", fontSize: 9 }}>{entry.rotated}</span>
                  <span style={{ color: "var(--text-secondary)", fontSize: 10, textAlign: "center" }}>
                    {entry.access}×
                  </span>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* Encryption layers panel */}
        <div style={{ width: 280, flexShrink: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="sv-glass-panel" style={{ padding: "14px 16px" }}>
            <div className="sv-label" style={{ marginBottom: 14 }}>ENCRYPTION LAYERS</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {ENCRYPTION_LAYERS.map((layer, i) => (
                <motion.div
                  key={layer.layer}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: i * 0.1 }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ color: "var(--text-primary)", fontSize: 9, letterSpacing: "0.06em" }}>{layer.layer}</span>
                    <span style={{ color: "var(--success)", fontSize: 9 }}>{layer.coverage}%</span>
                  </div>
                  <CoverageBar
                    pct={layer.coverage}
                    color={layer.coverage === 100 ? "var(--success)" : "var(--warn)"}
                  />
                  <div style={{ marginTop: 3, color: "var(--text-muted)", fontSize: 8 }}>{layer.algo}</div>
                </motion.div>
              ))}
            </div>
          </div>

          <div
            className="sv-glass-panel"
            style={{
              padding: "12px 14px",
              borderLeft: "3px solid var(--neon)",
            }}
          >
            <div className="sv-label" style={{ marginBottom: 8, color: "var(--neon)" }}>
              VAULT INTEGRITY
            </div>
            {[
              { label: "SEAL_HASH",    val: "SHA3-256:a4f9…c3e1" },
              { label: "LAST_AUDIT",   val: "2h 14m ago"          },
              { label: "KEY_ROTATION", val: "AUTO · 24h cycle"    },
              { label: "COMPLIANCE",   val: "SOC2 · FIPS 140-2"   },
            ].map(item => (
              <div key={item.label} style={{ marginBottom: 6 }}>
                <span className="sv-label" style={{ fontSize: 7, marginRight: 6 }}>{item.label}:</span>
                <span style={{ color: "var(--text-primary)", fontSize: 9 }}>{item.val}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
