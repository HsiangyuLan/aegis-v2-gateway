"use client";

/**
 * ProjectCard — Client Component
 * ================================
 * spec.md §4 Defensive Constraints:
 *
 * §4.1 Image Fallback:
 *   All <img> tags carry object-fit:cover + object-position:center.
 *   background-color:#F4F4F4 shows if image fails to load.
 *
 * §4.3 Null Intercept:
 *   If imageUrl is null/undefined, render an empty white box with
 *   border: 1px solid #000000 — NO src attribute set on img.
 *
 * §3 Aspect ratio: 1:1 enforced on the container.
 *
 * Clicking fires onSelect(project) — NO page navigation.
 */

import type { Project } from "@/app/types/portfolio";

interface ProjectCardProps {
  project: Project;
  onSelect: (project: Project) => void;
}

export default function ProjectCard({ project, onSelect }: ProjectCardProps) {
  const hasImage = Boolean(project.imageUrl);

  return (
    <article
      className="incision cursor-pointer group"
      onClick={() => onSelect(project)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(project);
        }
      }}
      role="button"
      tabIndex={0}
      aria-label={`Open ${project.title} details`}
    >
      {/* ── Image or null-intercept box ────────────────────────────────── */}
      {hasImage ? (
        <div className="supreme-img-shell">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={project.imageUrl!}
            alt={project.title}
            loading="lazy"
            /* spec §4.1: object-fit cover + object-position center enforced via CSS class */
            onError={(e) => {
              // Image load failure: hide broken img, show gray background
              const target = e.currentTarget;
              target.style.display = "none";
              const parent = target.parentElement;
              if (parent) {
                parent.style.backgroundColor = "#F4F4F4";
              }
            }}
          />
        </div>
      ) : (
        /* spec §4.3: null URL → empty white box with 1px black border */
        <div className="supreme-card-empty" aria-hidden="true" />
      )}

      {/* ── Card metadata ─────────────────────────────────────────────── */}
      <div
        className="incision-t"
        style={{
          padding: "8px 0 0 0",
          display: "flex",
          flexDirection: "column",
          gap: "2px",
        }}
      >
        <p
          style={{
            fontFamily: "var(--font-futura, 'Century Gothic', sans-serif)",
            fontWeight: 800,
            fontSize: "11px",
            letterSpacing: "0.04em",
            color: "#000000",
            textTransform: "uppercase",
            lineHeight: 1.2,
            /* Red reveal on hover — Group hover via inline style trick */
          }}
          className="group-hover:text-[#FF0000] transition-none"
        >
          {project.title}
        </p>
        <p
          style={{
            fontFamily: "var(--font-body, Inter, sans-serif)",
            fontWeight: 700,
            fontSize: "10px",
            letterSpacing: "0.03em",
            color: "#000000",
            opacity: 0.55,
            textTransform: "uppercase",
            lineHeight: 1.3,
          }}
        >
          {project.category} — {project.year}
        </p>
      </div>
    </article>
  );
}
