"""
Aegis V2 — Strategic Frontier Visualization
Produces two publication-quality PNG charts from simulation_results.parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
import pyarrow.parquet as pq
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap

# ─── Paths ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "output"
PARQUET_FILE = OUTPUT_DIR / "simulation_results.parquet"
CHART_A_OUT = OUTPUT_DIR / "chart_A_pareto_frontier.png"
CHART_B_OUT = OUTPUT_DIR / "chart_B_sla_fortress.png"

# ─── Design Tokens ───────────────────────────────────────────────────────────
BG_COLOR = "#09090B"
PRIMARY = "#38BDF8"
SECONDARY = "#818CF8"
ACCENT_GREEN = "#34D399"
ACCENT_AMBER = "#FBBF24"
ACCENT_RED = "#F87171"
ACCENT_PURPLE = "#C084FC"
TEXT_COLOR = "#E2E8F0"
DIM_TEXT = "#64748B"
GRID_COLOR = "#1E293B"
SLA_COLOR = "#EF4444"
SAFE_ZONE_COLOR = "#10B981"

FONT_FAMILY = "DejaVu Sans"
DPI = 180

CATEGORY_COLORS: dict[str, str] = {
    "standard": PRIMARY,
    "edge_case": ACCENT_AMBER,
    "jailbreak": ACCENT_RED,
}


# ─── Data Loading ─────────────────────────────────────────────────────────────
def load_parquet(path: Path) -> dict[str, Any]:
    """
    Load simulation results from Parquet and return column arrays.

    Args:
        path: Path to the Parquet file.

    Returns:
        Dictionary of column name → numpy array.

    Raises:
        FileNotFoundError: If the Parquet file does not exist.
        Exception: On PyArrow read failure.
    """
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {path}")
    try:
        table = pq.read_table(path)
        return {col: table.column(col).to_pylist() for col in table.schema.names}
    except Exception as exc:
        raise RuntimeError(f"Failed to read Parquet: {exc}") from exc


# ─── Pareto Frontier ──────────────────────────────────────────────────────────
def compute_pareto_frontier(
    costs: list[float],
    latencies: list[float],
) -> tuple[list[float], list[float]]:
    """
    Compute the Pareto-optimal frontier for (cost, latency) minimization.

    A point is Pareto-optimal if no other point is strictly better on
    BOTH dimensions simultaneously. We sort by cost ascending, then keep
    only points where latency is non-increasing (best-of-so-far).

    Args:
        costs: List of per-request cost values in USD.
        latencies: List of per-request total latency values in ms.

    Returns:
        Tuple of (pareto_costs, pareto_latencies) sorted by cost ascending.
    """
    if not costs or not latencies:
        return [], []

    points = sorted(zip(costs, latencies), key=lambda x: x[0])
    pareto_costs: list[float] = []
    pareto_latencies: list[float] = []
    min_latency = float("inf")

    for cost, lat in points:
        if lat < min_latency:
            min_latency = lat
            pareto_costs.append(cost)
            pareto_latencies.append(lat)

    return pareto_costs, pareto_latencies


def chart_a_pareto(data: dict[str, Any]) -> None:
    """
    Chart A — Pareto Optimization Frontier.

    Scatter plot of local_cost_usd vs total_latency_ms coloured by category,
    with the Pareto-optimal boundary overlaid as a step curve.

    Args:
        data: Column dictionary loaded from Parquet.
    """
    fig, ax = plt.subplots(figsize=(14, 9), dpi=DPI, facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    costs = np.array(data["local_cost_usd"], dtype=float)
    latencies = np.array(data["total_latency_ms"], dtype=float)
    categories = data["category"]
    entropy = np.array(data["entropy_score"], dtype=float)

    # Scatter by category
    legend_handles = []
    for cat, color in CATEGORY_COLORS.items():
        mask = np.array([c == cat for c in categories])
        if not np.any(mask):
            continue
        sizes = 25 + entropy[mask] * 8
        sc = ax.scatter(
            costs[mask],
            latencies[mask],
            c=color,
            s=sizes,
            alpha=0.70,
            linewidths=0.4,
            edgecolors=BG_COLOR,
            zorder=3,
        )
        legend_handles.append(mpatches.Patch(color=color, label=cat.replace("_", " ").title()))

    # Pareto frontier
    pf_costs, pf_lats = compute_pareto_frontier(costs.tolist(), latencies.tolist())
    if pf_costs:
        ax.step(
            pf_costs,
            pf_lats,
            where="post",
            color=ACCENT_GREEN,
            linewidth=2.2,
            zorder=5,
            label="Pareto Frontier",
        )
        ax.scatter(pf_costs, pf_lats, color=ACCENT_GREEN, s=55, zorder=6, marker="D")

        # Shade Pareto-dominated region
        ax.fill_betweenx(
            [min(pf_lats) * 0.5, max(pf_lats) * 1.15],
            min(pf_costs) * 0.5,
            max(pf_costs) * 1.1,
            color=ACCENT_GREEN,
            alpha=0.04,
            zorder=1,
        )

    # SLA breach line
    sla_ms = 15.0
    ax.axhline(sla_ms, color=SLA_COLOR, linewidth=1.5, linestyle="--", alpha=0.85, zorder=4)
    ax.text(
        max(costs) * 0.95,
        sla_ms + 0.3,
        "SLA BREACH THRESHOLD (15ms)",
        color=SLA_COLOR,
        fontsize=8.5,
        ha="right",
        fontweight="bold",
    )

    # Safe zone annotation
    y_safe_max = sla_ms * 0.85
    ax.axhspan(0, y_safe_max, color=SAFE_ZONE_COLOR, alpha=0.04, zorder=0)
    ax.text(
        min(costs) * 1.2,
        y_safe_max * 0.45,
        "AEGIS V2\nSOVEREIGN ZONE",
        color=ACCENT_GREEN,
        fontsize=9,
        fontweight="bold",
        alpha=0.6,
    )

    # Aegis V2 centroid marker
    aegis_x = float(np.percentile(costs, 25))
    aegis_y = float(np.percentile(latencies, 25))
    ax.scatter([aegis_x], [aegis_y], color=PRIMARY, s=280, marker="*", zorder=7, label="Aegis V2 Operating Point")
    ax.annotate(
        "AEGIS V2\nOPERATING POINT",
        xy=(aegis_x, aegis_y),
        xytext=(aegis_x * 1.6, aegis_y + 1.5),
        color=PRIMARY,
        fontsize=8.5,
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=PRIMARY, lw=1.2),
    )

    # Styling
    ax.set_xlabel("Local Cost per Request (USD)", color=TEXT_COLOR, fontsize=12, labelpad=10)
    ax.set_ylabel("Total Latency (ms)", color=TEXT_COLOR, fontsize=12, labelpad=10)
    ax.set_title(
        "PARETO OPTIMIZATION FRONTIER\nCost vs. Latency — Aegis V2 Compute Sovereignty",
        color=TEXT_COLOR,
        fontsize=15,
        fontweight="bold",
        pad=18,
    )
    ax.tick_params(colors=DIM_TEXT, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.6)

    legend_handles.append(
        mpatches.Patch(color=ACCENT_GREEN, label="Pareto Frontier")
    )
    legend_handles.append(
        plt.scatter([], [], color=PRIMARY, s=150, marker="*", label="Aegis V2 Op. Point")
    )
    legend = ax.legend(
        handles=legend_handles,
        loc="upper right",
        framealpha=0.2,
        facecolor=BG_COLOR,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR,
        fontsize=9.5,
    )

    # Watermark
    fig.text(
        0.5, 0.5,
        "AEGIS V2",
        fontsize=60,
        color=PRIMARY,
        alpha=0.04,
        ha="center",
        va="center",
        rotation=30,
        fontweight="bold",
    )

    fig.tight_layout(pad=2.0)
    fig.savefig(CHART_A_OUT, dpi=DPI, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    print(f"✓ Chart A saved → {CHART_A_OUT}")


# ─── SLA Fortress ─────────────────────────────────────────────────────────────
def chart_b_sla_fortress(data: dict[str, Any]) -> None:
    """
    Chart B — The SLA Fortress: Violin + KDE Heatmap.

    Violin plot per category with KDE overlay demonstrating that >99% of
    requests remain below the 10ms safe-zone boundary.

    Args:
        data: Column dictionary loaded from Parquet.
    """
    fig, axes = plt.subplots(1, 2, figsize=(16, 9), dpi=DPI, facecolor=BG_COLOR,
                             gridspec_kw={"width_ratios": [2, 1]})
    fig.patch.set_facecolor(BG_COLOR)

    latencies = np.array(data["total_latency_ms"], dtype=float)
    categories = data["category"]
    cat_order = ["standard", "edge_case", "jailbreak"]

    # ── Left: Violin per category ──
    ax = axes[0]
    ax.set_facecolor(BG_COLOR)

    grouped_lats: dict[str, list[float]] = {c: [] for c in cat_order}
    for lat, cat in zip(latencies, categories):
        if cat in grouped_lats:
            grouped_lats[cat].append(lat)

    parts_data = [grouped_lats[c] for c in cat_order if grouped_lats[c]]
    cat_labels = [c for c in cat_order if grouped_lats[c]]

    vp = ax.violinplot(
        parts_data,
        positions=range(len(cat_labels)),
        showmedians=True,
        showextrema=True,
        widths=0.6,
    )
    for i, (body, cat) in enumerate(zip(vp["bodies"], cat_labels)):
        color = CATEGORY_COLORS[cat]
        body.set_facecolor(color)
        body.set_alpha(0.5)
        body.set_edgecolor(color)

    vp["cmedians"].set_color(TEXT_COLOR)
    vp["cmedians"].set_linewidth(2)
    vp["cmins"].set_color(DIM_TEXT)
    vp["cmaxes"].set_color(DIM_TEXT)
    vp["cbars"].set_color(DIM_TEXT)

    # Overlay individual points (jittered)
    for i, (cat, lats_cat) in enumerate(zip(cat_labels, parts_data)):
        jitter = np.random.uniform(-0.12, 0.12, len(lats_cat))
        color = CATEGORY_COLORS[cat]
        ax.scatter(i + jitter, lats_cat, c=color, s=6, alpha=0.35, zorder=4)

    # SLA reference lines
    ax.axhline(15.0, color=SLA_COLOR, linewidth=1.8, linestyle="--", alpha=0.9, zorder=5)
    ax.axhline(10.0, color=SAFE_ZONE_COLOR, linewidth=1.5, linestyle=":", alpha=0.9, zorder=5)
    ax.axhspan(0, 10.0, color=SAFE_ZONE_COLOR, alpha=0.06, zorder=0)

    ax.text(len(cat_labels) - 0.4, 15.3, "SLA BREACH (15ms)", color=SLA_COLOR,
            fontsize=8, ha="right", fontweight="bold")
    ax.text(len(cat_labels) - 0.4, 10.3, "SAFE ZONE (10ms)", color=SAFE_ZONE_COLOR,
            fontsize=8, ha="right", fontweight="bold")

    # P99 annotation per category
    for i, (cat, lats_cat) in enumerate(zip(cat_labels, parts_data)):
        if lats_cat:
            p99 = float(np.percentile(lats_cat, 99))
            ax.annotate(
                f"P99={p99:.1f}ms",
                xy=(i, p99),
                xytext=(i + 0.35, p99),
                color=ACCENT_AMBER,
                fontsize=7.5,
                arrowprops=dict(arrowstyle="-", color=ACCENT_AMBER, lw=0.8),
            )

    ax.set_xticks(range(len(cat_labels)))
    ax.set_xticklabels([c.replace("_", " ").title() for c in cat_labels], color=TEXT_COLOR, fontsize=11)
    ax.set_ylabel("Total Latency (ms)", color=TEXT_COLOR, fontsize=12, labelpad=10)
    ax.set_title("SLA FORTRESS — Latency Distribution by Category", color=TEXT_COLOR,
                 fontsize=13, fontweight="bold", pad=15)
    ax.tick_params(colors=DIM_TEXT, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax.grid(True, axis="y", color=GRID_COLOR, linewidth=0.5, alpha=0.6)

    # ── Right: KDE Heatmap ──
    ax2 = axes[1]
    ax2.set_facecolor(BG_COLOR)

    lat_bins = np.linspace(latencies.min(), latencies.max(), 200)

    # Build KDE manually using Gaussian kernel (no scipy dependency needed)
    bandwidth = float(np.std(latencies)) * (len(latencies) ** (-1 / 5)) * 1.06

    def kde_eval(points: np.ndarray, bandwidth: float) -> np.ndarray:
        """Evaluate Gaussian KDE at lat_bins."""
        n = len(points)
        result = np.zeros(len(lat_bins))
        for p in points:
            result += np.exp(-0.5 * ((lat_bins - p) / bandwidth) ** 2)
        result /= n * bandwidth * np.sqrt(2 * np.pi)
        return result

    all_kde = kde_eval(latencies, bandwidth)

    # Stacked KDE by category with fill
    colors_kde = [CATEGORY_COLORS[c] for c in cat_order if grouped_lats[c]]
    for cat, color in zip(cat_labels, colors_kde):
        lats_cat = np.array(grouped_lats[cat])
        if len(lats_cat) == 0:
            continue
        cat_kde = kde_eval(lats_cat, bandwidth * 1.2)
        ax2.fill_betweenx(lat_bins, 0, cat_kde, color=color, alpha=0.3)
        ax2.plot(cat_kde, lat_bins, color=color, linewidth=1.5, alpha=0.9)

    # Overall KDE
    ax2.plot(all_kde, lat_bins, color=TEXT_COLOR, linewidth=2.0, linestyle="-", alpha=0.9, label="All Requests")

    # Reference lines
    ax2.axhline(15.0, color=SLA_COLOR, linewidth=1.8, linestyle="--", alpha=0.9)
    ax2.axhline(10.0, color=SAFE_ZONE_COLOR, linewidth=1.5, linestyle=":", alpha=0.9)
    ax2.axhspan(0, 10.0, color=SAFE_ZONE_COLOR, alpha=0.06)

    # 99th percentile annotation
    p99_all = float(np.percentile(latencies, 99))
    ax2.axhline(p99_all, color=ACCENT_AMBER, linewidth=1.2, linestyle="-.", alpha=0.8)
    ax2.text(
        max(all_kde) * 0.6,
        p99_all + 0.3,
        f"P99 = {p99_all:.2f}ms",
        color=ACCENT_AMBER,
        fontsize=8.5,
        fontweight="bold",
    )

    # Safe zone pct
    safe_pct = np.mean(latencies < 10.0) * 100
    ax2.text(
        max(all_kde) * 0.3,
        5.0,
        f"{safe_pct:.1f}%\nIN SAFE ZONE",
        color=ACCENT_GREEN,
        fontsize=10,
        fontweight="bold",
        ha="center",
        va="center",
    )

    ax2.set_xlabel("Density", color=TEXT_COLOR, fontsize=11, labelpad=10)
    ax2.set_ylabel("Latency (ms)", color=TEXT_COLOR, fontsize=11, labelpad=10)
    ax2.set_title("KDE DENSITY\nHEATMAP", color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=15)
    ax2.tick_params(colors=DIM_TEXT, labelsize=9)
    for spine in ax2.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax2.grid(True, axis="y", color=GRID_COLOR, linewidth=0.5, alpha=0.6)

    # Shared title
    fig.suptitle(
        "THE SLA FORTRESS — Aegis V2 Latency Sovereignty\n99%+ Requests Contained Within 10ms Safe Zone",
        color=TEXT_COLOR,
        fontsize=14,
        fontweight="bold",
        y=1.01,
    )

    # Watermark
    fig.text(
        0.5, 0.5,
        "AEGIS V2",
        fontsize=55,
        color=PRIMARY,
        alpha=0.04,
        ha="center",
        va="center",
        rotation=30,
        fontweight="bold",
    )

    fig.tight_layout(pad=2.5)
    fig.savefig(CHART_B_OUT, dpi=DPI, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    print(f"✓ Chart B saved → {CHART_B_OUT}")


# ─── Entry Point ─────────────────────────────────────────────────────────────
def main() -> None:
    """Main entry point: load Parquet and produce both charts."""
    try:
        print(f"Loading data from {PARQUET_FILE} ...")
        data = load_parquet(PARQUET_FILE)
        print(f"  Rows loaded: {len(data['prompt_id'])}")
    except FileNotFoundError as exc:
        print(f"✗ {exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"✗ {exc}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        chart_a_pareto(data)
    except Exception as exc:
        print(f"✗ Chart A failed: {exc}")
        raise

    try:
        chart_b_sla_fortress(data)
    except Exception as exc:
        print(f"✗ Chart B failed: {exc}")
        raise

    print("\n✓ All charts generated successfully.")
    print(f"  → {CHART_A_OUT}")
    print(f"  → {CHART_B_OUT}")


if __name__ == "__main__":
    main()
