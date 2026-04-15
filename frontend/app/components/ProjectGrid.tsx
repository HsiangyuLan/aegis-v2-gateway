/**
 * ProjectGrid — Server Component shell
 * ======================================
 * spec.md §2 Product Grid:
 *   margin-left: 200px; padding-right: 40px
 *   grid-template-columns: repeat(5, 1fr); gap: 20px
 *
 * spec.md §4.2 Responsive Degradation (via .supreme-grid CSS class):
 *   < 1024px → repeat(3, 1fr)
 *   <  768px → repeat(2, 1fr)
 *
 * ProjectCard components are CC and handle all click/selection logic.
 * This shell passes the onSelect callback down from the CC parent wrapper.
 */

"use client";

import type { Project } from "@/app/types/portfolio";
import ProjectCard from "./ProjectCard";

interface ProjectGridProps {
  projects: Project[];
  onSelect: (project: Project) => void;
}

export default function ProjectGrid({ projects, onSelect }: ProjectGridProps) {
  return (
    <section
      id="work"
      style={{ marginLeft: "var(--nav-offset)", paddingRight: "var(--content-pr)" }}
    >
      {/* Section label */}
      <div
        className="incision-b"
        style={{
          paddingBottom: "12px",
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-body, Inter, sans-serif)",
            fontWeight: 700,
            fontSize: "11px",
            letterSpacing: "0.12em",
            color: "#000000",
            textTransform: "uppercase",
          }}
        >
          SELECTED WORKS
        </span>
        <span
          style={{
            fontFamily: "var(--font-body, Inter, sans-serif)",
            fontWeight: 700,
            fontSize: "11px",
            letterSpacing: "0.06em",
            color: "#000000",
            opacity: 0.4,
          }}
        >
          {projects.length} PROJECTS
        </span>
      </div>

      {/* §2 5-column grid — responsive via .supreme-grid CSS class */}
      <div className="supreme-grid">
        {projects.map((project) => (
          <ProjectCard
            key={project.id}
            project={project}
            onSelect={onSelect}
          />
        ))}
      </div>
    </section>
  );
}
