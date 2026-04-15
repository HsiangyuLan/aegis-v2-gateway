/**
 * Portfolio project data — spec.md §4.3 null-intercept applied in ProjectCard.
 *
 * Narrative principle: frame every project around measurable engineering output,
 * latency SLA, cost arbitrage, and systems impact — not academic context.
 */

export interface Project {
  id: string;
  title: string;
  subtitle: string;
  year: string;
  category: string;
  tags: string[];
  description: string;
  /** One-line authority metric displayed under the title in the drawer */
  metric?: string;
  tech: string[];
  /** null → spec §4.3: render 1px black border empty box */
  imageUrl: string | null | undefined;
  accentColor?: string;
}

export const PROJECTS: Project[] = [
  {
    id: "aegis-v2",
    title: "AEGIS V2",
    subtitle: "COMPUTE SOVEREIGNTY PLATFORM",
    year: "2024–25",
    category: "AI INFRASTRUCTURE",
    tags: ["Rust", "FastAPI", "ONNX", "Next.js", "Tailwind v4"],
    metric: "87% cloud cost reduction · sub-15ms P99 SLA",
    description:
      "Production inference gateway that routes 300+ concurrent LLM requests " +
      "between a Rust FFI edge node and cloud APIs at HFT-grade latency. " +
      "A semantic entropy probe (INT8 MiniLM via PyO3) classifies each request " +
      "in <1ms and routes to the lowest-cost compliant backend — delivering " +
      "87% cost reduction versus GPT-4o class APIs while holding a 15ms P99 SLA. " +
      "Real-time FinOps telemetry streams AEI (Arbitrage Efficiency Index) data " +
      "to a Bloomberg-style terminal dashboard and a Next.js live frontend " +
      "over TOON-format SSE. Sovereign whitepaper auto-generated on every run.",
    tech: [
      "Rust 1.83 / PyO3",
      "FastAPI + SSE",
      "ONNX Runtime INT8",
      "Polars Parquet",
      "framer-motion 12",
      "Tailwind CSS v4",
      "Clerk + Sentry",
    ],
    imageUrl: null,
    accentColor: "#FF0000",
  },
  {
    id: "cse-2111",
    title: "CSE 2111",
    subtitle: "ALGORITHM ENGINEERING",
    year: "2024",
    category: "SYSTEMS FOUNDATIONS",
    tags: ["Java", "Red-Black Trees", "Graph Algorithms", "Amortised Analysis"],
    metric:
      "O(log n) ordered index · Dijkstra SSSP · NP-completeness reductions",
    description:
      "Engineered and formally verified a suite of production-class data structures " +
      "and graph algorithms — red-black trees for O(log n) ordered key access, " +
      "Dijkstra SSSP and Floyd–Warshall for cost-optimal routing, and amortised " +
      "analysis of dynamic array resizing. Techniques directly underpin Aegis V2's " +
      "entropy-weighted request priority queue and the Pareto-frontier cost " +
      "optimiser in the FinOps pipeline. NP-completeness reductions confirmed " +
      "that routing optimisation is in the tractable subset for practical SLA budgets.",
    tech: ["Java 21", "JUnit 5", "IntelliJ IDEA"],
    imageUrl: null,
    accentColor: "#000000",
  },
  {
    id: "finops-dashboard",
    title: "FINOPS DASHBOARD",
    subtitle: "COST ARBITRAGE INTELLIGENCE ENGINE",
    year: "2024",
    category: "DATA ENGINEERING",
    tags: ["Python", "Seaborn", "Polars", "WeasyPrint", "asyncio"],
    metric: "95.7% asset compression · 12-month arbitrage forecast",
    description:
      "End-to-end FinOps intelligence pipeline that simulates 300 concurrent " +
      "inference requests, aggregates cost/latency Parquet data in real time, " +
      "and auto-generates publication-quality artefacts: a Pareto-frontier " +
      "scatter plot proving Aegis V2 operates in the globally cost-optimal zone, " +
      "a violin-plot SLA Fortress confirming 99%+ requests inside the 10ms boundary, " +
      "and a 6-page sovereign whitepaper with 12-month speculative-decoding " +
      "arbitrage growth forecast. Asset pipeline achieves 95.7% compression " +
      "(84 MB PNG → 3.65 MB WebP) at 42 fps throughput.",
    tech: ["Python 3.13", "Polars 1.x", "Seaborn", "WeasyPrint", "asyncio"],
    imageUrl: null,
  },
  {
    id: "rust-ffi-engine",
    title: "RUST FFI ENGINE",
    subtitle: "SUB-MILLISECOND INFERENCE CORE",
    year: "2024",
    category: "SYSTEMS PROGRAMMING",
    tags: ["Rust", "PyO3", "ONNX", "maturin", "ARM64"],
    metric: "<1ms FFI boundary · INT8 MiniLM · ARM64 + x86-64",
    description:
      "Zero-overhead Rust extension that exposes a cascading semantic entropy " +
      "probe to Python with sub-millisecond FFI crossing cost. The cascade runs " +
      "a fast INT8-quantised MiniLM sentinel first; only ambiguous requests " +
      "escalate to a higher-quality ONNX model, minimising compute spend per " +
      "classification. Built with PyO3 + maturin for native wheel distribution. " +
      "Compiled for Apple Silicon (ARM64) and x86-64 — the same binary runs " +
      "in local development and Linux cloud VMs without recompilation.",
    tech: ["Rust 1.83", "PyO3", "maturin 1.5", "ort (ONNX Runtime 2.0)"],
    imageUrl: null,
  },
  {
    id: "sovereign-pdf",
    title: "SOVEREIGN PDF",
    subtitle: "PROGRAMMATIC DOCUMENT INFRASTRUCTURE",
    year: "2024",
    category: "DOCUMENT SYSTEMS",
    tags: ["WeasyPrint", "CSS Paged Media", "Python", "clip-path"],
    metric: "6 pages · zero static assets · diagonal watermark per page",
    description:
      "Automated report-generation system that produces a fully-formatted " +
      "6-page technical whitepaper from live simulation data on every pipeline run. " +
      "CSS Paged Media specification drives the layout: diagonal " +
      "'HIGHLY CONFIDENTIAL' watermarks via fixed positioning, a clip-path " +
      "hexagonal shield logo with CSS box-shadow glow, specular-highlight borders, " +
      "and a tabular 12-month arbitrage forecast derived from the S-curve " +
      "speculative-decoding adoption model. Zero static assets — every graphic " +
      "is generated from pure CSS geometry at render time.",
    tech: ["Python 3.13", "WeasyPrint 62", "CSS Paged Media"],
    imageUrl: null,
  },
  {
    id: "project-antigravity",
    title: "PROJECT ANTIGRAVITY",
    subtitle: "16-CRATE RUST AGENTIC COMMERCE GATEWAY",
    year: "2025",
    category: "SYSTEMS ARCHITECTURE",
    tags: ["Rust", "PyO3", "Arc<[u8]>", "FastAPI", "Zero-Copy FFI"],
    metric: "Zero-copy FFI · Arc<[u8]> cross-GIL · 16-crate workspace",
    description:
      "High-frequency Agentic Commerce gateway built as a 16-crate Cargo workspace. " +
      "The core crate (antigravity_core) implements zero-copy memory transmission: " +
      "Python bytes are read via PyO3's PyBuffer<u8> buffer protocol — physically " +
      "zero Python-side allocations — then transferred across the GIL boundary as " +
      "Arc<[u8]>, requiring exactly one Rust-side copy to achieve Send semantics. " +
      "GIL is released via py.allow_threads for CPU-intensive routing logic. " +
      "FastAPI Circuit Breakers (CLOSED → OPEN → HALF-OPEN state machine) guard " +
      "every upstream LLM call, preventing cascade failures under 500+ concurrent " +
      "users. Chaos engineering validated via Locust: pool exhaustion at " +
      "max_connections=100 triggers CloudInferenceTimeoutError → CB OPEN in <3s.",
    tech: [
      "Rust 1.94 / PyO3 0.22",
      "maturin 1.12",
      "FastAPI + asyncio",
      "httpx connection pool",
      "Circuit Breaker (asyncio.Lock)",
      "Locust chaos engineering",
      "Polars Parquet FinOps",
    ],
    imageUrl: null,
    accentColor: "#FF0000",
  },
];
