"use client";

/**
 * ProjectDrawer — Slide-in Drawer
 * ==================================
 * Slides in from the RIGHT edge with framer-motion AnimatePresence.
 * NO page navigation — project detail stays in the same viewport.
 *
 * Performance target: perceived 10ms response.
 * - onClick → state update is synchronous (React batching → <1 frame)
 * - framer-motion uses CSS transform (compositor layer, no layout cost)
 * - Initial x: 480 → 0: hardware-accelerated slide, ~200ms at ease-out
 *
 * Spec §1 Design Language:
 * - Background: #FFFFFF, Border-left: 1px solid #000000
 * - All text: Inter-Bold, #000000
 * - Accent red (#FF0000) used only for the category label and close ×
 * - Zero border-radius throughout (enforced by .supreme-root parent)
 */

import { useEffect, useCallback } from "react";
import { AnimatePresence, motion, type Variants, type Easing } from "framer-motion";
import type { Project } from "@/app/types/portfolio";

interface ProjectDrawerProps {
  project: Project | null;
  onClose: () => void;
}

const EASE_OUT: Easing = [0.16, 1, 0.3, 1];
const EASE_IN:  Easing = [0.7,  0, 0.84, 0];

const SLIDE_VARIANTS: Variants = {
  hidden:  { x: "100%" },
  visible: {
    x: 0,
    transition: { type: "tween" as const, ease: EASE_OUT, duration: 0.28 },
  },
  exit: {
    x: "100%",
    transition: { type: "tween" as const, ease: EASE_IN, duration: 0.22 },
  },
};

export default function ProjectDrawer({ project, onClose }: ProjectDrawerProps) {
  // Keyboard escape to close
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!project) return;
    window.addEventListener("keydown", handleKeyDown);
    // Prevent body scroll while drawer is open
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [project, handleKeyDown]);

  return (
    <AnimatePresence>
      {project && (
        <>
          {/* Backdrop */}
          <motion.div
            className="supreme-drawer-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden="true"
          />

          {/* Drawer panel */}
          <motion.aside
            className="supreme-drawer"
            variants={SLIDE_VARIANTS}
            initial="hidden"
            animate="visible"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-label={`${project.title} project details`}
          >
            {/* ── Header ─────────────────────────────────────────────── */}
            <div
              className="incision-b"
              style={{
                padding: "24px 28px 20px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: "16px",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                <span
                  style={{
                    fontFamily: "var(--font-body, Inter, sans-serif)",
                    fontWeight: 700,
                    fontSize: "10px",
                    letterSpacing: "0.12em",
                    color: "#FF0000",
                    textTransform: "uppercase",
                  }}
                >
                  {project.category}
                </span>
                <h2
                  style={{
                    fontFamily:
                      "var(--font-futura, 'Century Gothic', 'Trebuchet MS', sans-serif)",
                    fontWeight: 800,
                    fontSize: "22px",
                    letterSpacing: "-0.01em",
                    color: "#000000",
                    lineHeight: 1.1,
                    textTransform: "uppercase",
                  }}
                >
                  {project.title}
                </h2>
                <p
                  style={{
                    fontFamily: "var(--font-body, Inter, sans-serif)",
                    fontWeight: 700,
                    fontSize: "11px",
                    letterSpacing: "0.04em",
                    color: "#000000",
                    opacity: 0.55,
                    textTransform: "uppercase",
                  }}
                >
                  {project.subtitle}
                </p>
              </div>

              {/* Close button */}
              <button
                onClick={onClose}
                aria-label="Close drawer"
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: "0",
                  fontFamily: "var(--font-body, Inter, sans-serif)",
                  fontWeight: 700,
                  fontSize: "22px",
                  color: "#FF0000",
                  lineHeight: 1,
                  flexShrink: 0,
                }}
              >
                ×
              </button>
            </div>

            {/* ── Image / null-intercept ─────────────────────────────── */}
            <div
              style={{
                margin: "20px 28px",
                aspectRatio: "16 / 9",
                backgroundColor: project.imageUrl ? "transparent" : "#F4F4F4",
                border: project.imageUrl ? "none" : "1px solid #000000",
                overflow: "hidden",
              }}
            >
              {project.imageUrl && (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={project.imageUrl}
                  alt={project.title}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    objectPosition: "center",
                    display: "block",
                  }}
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                    const parent = e.currentTarget.parentElement;
                    if (parent) {
                      parent.style.backgroundColor = "#F4F4F4";
                      parent.style.border = "1px solid #000000";
                    }
                  }}
                />
              )}
            </div>

            {/* ── Body ───────────────────────────────────────────────── */}
            <div style={{ padding: "0 28px 28px", display: "flex", flexDirection: "column", gap: "20px" }}>
              {/* Year */}
              <div className="incision-b" style={{ paddingBottom: "12px" }}>
                <span
                  style={{
                    fontFamily: "var(--font-body, Inter, sans-serif)",
                    fontWeight: 700,
                    fontSize: "11px",
                    letterSpacing: "0.08em",
                    color: "#000000",
                    opacity: 0.45,
                    textTransform: "uppercase",
                  }}
                >
                  {project.year}
                </span>
              </div>

              {/* Description */}
              <p
                style={{
                  fontFamily: "var(--font-body, Inter, sans-serif)",
                  fontWeight: 700,
                  fontSize: "13px",
                  lineHeight: 1.65,
                  color: "#000000",
                  letterSpacing: "0.01em",
                }}
              >
                {project.description}
              </p>

              {/* Tech stack */}
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <span
                  className="incision-b"
                  style={{
                    display: "block",
                    paddingBottom: "8px",
                    fontFamily: "var(--font-body, Inter, sans-serif)",
                    fontWeight: 700,
                    fontSize: "10px",
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: "#000000",
                    opacity: 0.45,
                  }}
                >
                  TECH STACK
                </span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {project.tech.map((t) => (
                    <span
                      key={t}
                      className="incision"
                      style={{
                        padding: "3px 7px",
                        fontFamily: "var(--font-body, Inter, sans-serif)",
                        fontWeight: 700,
                        fontSize: "10px",
                        letterSpacing: "0.05em",
                        textTransform: "uppercase",
                        color: "#000000",
                      }}
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>

              {/* Tags */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                {project.tags.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      padding: "2px 6px",
                      backgroundColor: "#000000",
                      fontFamily: "var(--font-body, Inter, sans-serif)",
                      fontWeight: 700,
                      fontSize: "9px",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      color: "#FFFFFF",
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
