"use client";

/**
 * Portfolio Homepage — Supreme-style Sovereign Compute
 * ======================================================
 * spec.md §1–§4 compliant:
 * - Brand: #FF0000 / #FFFFFF / #000000
 * - Futura Heavy headers, Inter-Bold body
 * - 1440px container, absolute left nav 180px (text-align:right)
 * - 5-col project grid → 3-col @<1024px → 2-col @<768px
 * - ScrollyCanvas hero with rotateY + particle disintegration
 * - Slide-in drawer for project details (NO page navigation)
 * - spec §4 defensive: image fallback, null intercept, grid degradation
 */

import { useState, useCallback } from "react";
import LeftNav           from "@/app/components/LeftNav";
import ScrollyCanvas     from "@/app/components/ScrollyCanvas";
import ProjectGrid       from "@/app/components/ProjectGrid";
import ProjectDrawer     from "@/app/components/ProjectDrawer";
import FinOpsDashboard   from "@/app/components/FinOpsDashboard";
import { PROJECTS }      from "@/app/types/portfolio";
import type { Project }  from "@/app/types/portfolio";

// ─── Live Timestamp ───────────────────────────────────────────────────────────

function LiveTimestamp() {
  // Static for SSR; hydrates on client
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const dateStr =
    `${now.getFullYear()}.${pad(now.getMonth() + 1)}.${pad(now.getDate())}` +
    ` — ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())} UTC`;
  return (
    <p className="supreme-timestamp" suppressHydrationWarning>
      {dateStr}
    </p>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PortfolioHome() {
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  const handleSelect = useCallback((project: Project) => {
    setSelectedProject(project);
  }, []);

  const handleClose = useCallback(() => {
    setSelectedProject(null);
  }, []);

  return (
    /* supreme-root activates spec.md brand token scope */
    <div className="supreme-root" style={{ maxWidth: "1440px", margin: "0 auto" }}>

      {/* ══ HEADER ══════════════════════════════════════════════════════════ */}
      <header
        className="incision-b"
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "center",
          flexDirection: "column",
          padding: "20px 40px 16px",
        }}
      >
        {/* §2 Logo Box: 130×40, red, italic Futura centered */}
        <div className="supreme-logo-box">
          <span className="supreme-logo-text">HL</span>
        </div>

        {/* §2 Timestamp */}
        <LiveTimestamp />
      </header>

      {/* ══ BODY LAYOUT ═════════════════════════════════════════════════════ */}
      <div
        style={{ position: "relative" }}
      >
        {/* §2 Left Navigation — 180px, text-align:right, absolute */}
        <LeftNav />

        {/* ══ HERO — ScrollyCanvas ══════════════════════════════════════════ */}
        <div
          style={{
            marginLeft: "var(--nav-offset)",
            paddingRight: "var(--content-pr)",
            paddingTop: "40px",
          }}
        >
          {/* Section eyebrow */}
          <div
            className="incision-b"
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              paddingBottom: "10px",
              marginBottom: "0",
            }}
          >
            <span
              style={{
                fontFamily:
                  "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)",
                fontWeight: 800,
                fontSize: "10px",
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: "#000000",
              }}
            >
              SOVEREIGN COMPUTE — SCROLL TO EXPLORE
            </span>
            <span
              style={{
                fontFamily: "var(--font-body, Inter, sans-serif)",
                fontWeight: 700,
                fontSize: "10px",
                letterSpacing: "0.08em",
                color: "#000000",
                opacity: 0.4,
                textTransform: "uppercase",
              }}
            >
              120 FRAMES · 3.65 MB
            </span>
          </div>

          {/* The hero canvas — rotates + disintegrates on scroll */}
          <ScrollyCanvas />
        </div>

        {/* ══ IDENTITY BLOCK ═══════════════════════════════════════════════ */}
        <div
          className="incision-b"
          style={{
            marginLeft: "var(--nav-offset)",
            paddingRight: "var(--content-pr)",
            paddingTop: "40px",
            paddingBottom: "40px",
            display: "grid",
            gridTemplateColumns: "1fr auto",
            gap: "40px",
            alignItems: "end",
          }}
        >
          {/* Name block */}
          <div>
            <h1
              style={{
                fontFamily:
                  "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)",
                fontWeight: 800,
                fontSize: "clamp(2.5rem, 5vw, 5rem)",
                letterSpacing: "-0.03em",
                lineHeight: 0.95,
                color: "#000000",
                textTransform: "uppercase",
                margin: 0,
              }}
            >
              HSIANGYU
              <br />
              <span style={{ color: "#FF0000" }}>LAN</span>
            </h1>
            <p
              style={{
                fontFamily: "var(--font-body, Inter, sans-serif)",
                fontWeight: 700,
                fontSize: "11px",
                letterSpacing: "0.14em",
                color: "#000000",
                textTransform: "uppercase",
                marginTop: "12px",
                opacity: 0.55,
              }}
            >
              MIS · FISHER COLLEGE OF BUSINESS · HFT INFRASTRUCTURE · RUST · FINOPS
            </p>
          </div>

          {/* Manifesto */}
          <div style={{ maxWidth: "260px" }}>
            <p
              style={{
                fontFamily: "var(--font-body, Inter, sans-serif)",
                fontWeight: 700,
                fontSize: "11px",
                lineHeight: 1.7,
                color: "#000000",
                letterSpacing: "0.02em",
              }}
            >
              MIS graduate from Fisher College of Business architecting
              sovereign compute infrastructure — Rust FFI performance,
              HFT-grade inference engines, and FinOps arbitrage intelligence.
            </p>
          </div>
        </div>

        {/* ══ PROJECT GRID ═════════════════════════════════════════════════ */}
        <div
          style={{
            paddingTop: "0",
            paddingBottom: "80px",
          }}
        >
          <ProjectGrid projects={PROJECTS} onSelect={handleSelect} />
        </div>

        {/* ══ LIVE IMPACT METRICS — AEGIS V2 ══════════════════════════════ */}
        {/*
          FinOpsDashboard is a "use client" component that fetches
          /v1/analytics/finops via SWR (30s revalidation).  It renders a
          skeleton placeholder during load so page height is stable and
          ScrollyCanvas CSS animations are never interrupted.
        */}
        <div
          className="incision-b"
          style={{
            marginLeft: "var(--nav-offset)",
            paddingRight: "var(--content-pr)",
            paddingTop: "48px",
            paddingBottom: "48px",
          }}
        >
          <FinOpsDashboard />
        </div>

        {/* ══ LOOKBOOK CAROUSEL §3 ════════════════════════════════════════ */}
        <div
          className="incision-t incision-b"
          style={{
            marginLeft: "var(--nav-offset)",
            paddingRight: "0",
            paddingTop: "0",
            paddingBottom: "0",
          }}
        >
          <div
            style={{
              padding: "10px 0",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              paddingRight: "var(--content-pr)",
            }}
          >
            <span
              style={{
                fontFamily:
                  "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)",
                fontWeight: 800,
                fontSize: "10px",
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                color: "#000000",
              }}
            >
              STACK ARCHIVE
            </span>
          </div>

          {/* §3 Lookbook: 15vw wide, 1:5 aspect ratio, 0px gap */}
          <div className="supreme-lookbook">
            {[
              { label: "RUST", accent: "#FF0000" },
              { label: "ONNX", accent: "#000000" },
              { label: "NEXT.JS", accent: "#FF0000" },
              { label: "POLARS", accent: "#000000" },
              { label: "TAILWIND", accent: "#FF0000" },
              { label: "FASTAPI", accent: "#000000" },
              { label: "FRAMER", accent: "#FF0000" },
              { label: "SENTRY", accent: "#000000" },
            ].map(({ label, accent }) => (
              <div
                key={label}
                className="supreme-lookbook-item"
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  justifyContent: "flex-start",
                  padding: "12px 8px",
                  backgroundColor: accent === "#FF0000" ? "#FF0000" : "#000000",
                  borderRight: "1px solid rgba(255,255,255,0.1)",
                }}
              >
                <span
                  style={{
                    fontFamily:
                      "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)",
                    fontWeight: 800,
                    fontSize: "9px",
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: "#FFFFFF",
                    writingMode: "vertical-rl",
                    textOrientation: "mixed",
                    transform: "rotate(180deg)",
                  }}
                >
                  {label}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ══ INFO / CONTACT §3 ════════════════════════════════════════════ */}
        <div
          id="info"
          className="incision-b"
          style={{
            marginLeft: "var(--nav-offset)",
            paddingRight: "var(--content-pr)",
            paddingTop: "48px",
            paddingBottom: "48px",
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "40px",
          }}
        >
          <div id="contact" style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            <span
              style={{
                fontFamily: "var(--font-body, Inter, sans-serif)",
                fontWeight: 700,
                fontSize: "10px",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "#FF0000",
                marginBottom: "8px",
              }}
            >
              CONTACT
            </span>
            {[
              { label: "GITHUB",   href: "https://github.com/hsiangyulan" },
              { label: "LINKEDIN", href: "https://www.linkedin.com/in/hsiangyu1230/" },
              { label: "EMAIL",    href: "mailto:hsiangyulan1230@gmail.com" },
            ].map(({ label, href }) => (
              <a
                key={label}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontFamily: "var(--font-body, Inter, sans-serif)",
                  fontWeight: 700,
                  fontSize: "13px",
                  letterSpacing: "0.04em",
                  color: "#000000",
                  textDecoration: "none",
                  textTransform: "uppercase",
                  lineHeight: 1.8,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = "#FF0000"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = "#000000"; }}
              >
                {label} →
              </a>
            ))}
          </div>

          <div>
            <span
              style={{
                fontFamily: "var(--font-body, Inter, sans-serif)",
                fontWeight: 700,
                fontSize: "10px",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "#FF0000",
                display: "block",
                marginBottom: "8px",
              }}
            >
              STATUS
            </span>
            <p
              style={{
                fontFamily: "var(--font-body, Inter, sans-serif)",
                fontWeight: 700,
                fontSize: "13px",
                lineHeight: 1.7,
                color: "#000000",
                letterSpacing: "0.01em",
              }}
            >
              Available for infrastructure engineering roles, AI systems architecture, and Rust/Python
              full-stack contracts. Open to remote-first sovereign compute projects.
            </p>
          </div>
        </div>

        {/* ══ FOOTER ═══════════════════════════════════════════════════════ */}
        <footer
          style={{
            marginLeft: "var(--nav-offset)",
            paddingRight: "var(--content-pr)",
            paddingTop: "20px",
            paddingBottom: "32px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-body, Inter, sans-serif)",
              fontWeight: 700,
              fontSize: "10px",
              letterSpacing: "0.08em",
              color: "#000000",
              opacity: 0.35,
              textTransform: "uppercase",
            }}
          >
            © {new Date().getFullYear()} HSIANGYU LAN — ALL RIGHTS RESERVED
          </span>
          <span
            style={{
              fontFamily: "var(--font-body, Inter, sans-serif)",
              fontWeight: 700,
              fontSize: "10px",
              letterSpacing: "0.08em",
              color: "#FF0000",
              textTransform: "uppercase",
            }}
          >
            BUILT WITH AEGIS V2
          </span>
        </footer>

      </div>

      {/* ══ SLIDE-IN DRAWER — no page navigation ════════════════════════════ */}
      <ProjectDrawer project={selectedProject} onClose={handleClose} />

    </div>
  );
}
