"""
Aegis V2 — Sequence Frame Generator
=====================================
Generates 89 WebP frames for the ScrollyCanvas component.
Each frame renders a HUD-style sovereign compute visualization:
  - Dark background (#09090B)
  - Animated radar sweep arc
  - Rolling AEI data lattice
  - Glowing particle nodes (entropy-mapped)
  - Frame counter overlay

Output: frontend/public/sequence/0000.webp … 0088.webp

Requires: Pillow >= 10.0
  pip install Pillow
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Final

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow not found. Installing…")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image, ImageDraw, ImageFont  # type: ignore[assignment]

# ─── Config ───────────────────────────────────────────────────────────────────

FRAME_COUNT: Final = 89
WIDTH:  Final = 1920
HEIGHT: Final = 1080
OUTPUT_DIR: Final = Path(__file__).parent.parent / "frontend" / "public" / "sequence"

BG_COLOR     = (9,  9,  11)        # #09090B
CYAN         = (56, 189, 248)      # #38BDF8
AMBER        = (251, 191, 36)      # #FBBF24
RED          = (248, 113, 113)     # #F87171
GREEN        = (52,  211, 153)     # #34D399
DIM          = (30,  41,  59)      # grid lines

# ─── Helpers ──────────────────────────────────────────────────────────────────

def lerp_color(
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    """Linear interpolation between two RGB colours."""
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (*color, alpha)


# ─── Per-frame Render ─────────────────────────────────────────────────────────

def render_frame(idx: int) -> Image.Image:
    """
    Render a single HUD frame.

    idx  : 0–88 (monotonically increasing)
    t    : normalised progress 0.0–1.0
    """
    t = idx / (FRAME_COUNT - 1)
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img, "RGBA")

    # ── 1. Background dot-grid ────────────────────────────────────────────────
    GRID_STEP = 48
    for gx in range(0, WIDTH, GRID_STEP):
        for gy in range(0, HEIGHT, GRID_STEP):
            draw.ellipse([(gx - 1, gy - 1), (gx + 1, gy + 1)], fill=rgba(DIM, 80))

    # ── 2. Radar sweep arc ────────────────────────────────────────────────────
    cx, cy = WIDTH // 2, HEIGHT // 2
    RADAR_R = min(WIDTH, HEIGHT) * 0.42
    sweep_angle = t * 360.0 * 3         # 3 full rotations across the sequence

    # Faded trail (last 90° of the sweep)
    TRAIL_STEPS = 18
    for step in range(TRAIL_STEPS):
        trail_t = step / TRAIL_STEPS
        angle = sweep_angle - (1.0 - trail_t) * 90.0
        alpha = int(trail_t * 120)
        color = lerp_color(BG_COLOR, CYAN, trail_t * 0.5)
        r0 = RADAR_R * 0.05
        r1 = RADAR_R * trail_t
        rad = math.radians(angle)
        x1 = cx + math.cos(rad) * r0
        y1 = cy + math.sin(rad) * r0
        x2 = cx + math.cos(rad) * r1
        y2 = cy + math.sin(rad) * r1
        draw.line([(x1, y1), (x2, y2)], fill=rgba(color, alpha), width=2)

    # Bright leading edge
    lead_rad = math.radians(sweep_angle)
    draw.line(
        [
            (cx + math.cos(lead_rad) * RADAR_R * 0.05,
             cy + math.sin(lead_rad) * RADAR_R * 0.05),
            (cx + math.cos(lead_rad) * RADAR_R,
             cy + math.sin(lead_rad) * RADAR_R),
        ],
        fill=rgba(CYAN, 220),
        width=3,
    )

    # Radar concentric rings
    for ring_r in [0.25, 0.5, 0.75, 1.0]:
        r = RADAR_R * ring_r
        bbox = [(cx - r, cy - r), (cx + r, cy + r)]
        draw.ellipse(bbox, outline=rgba(CYAN, 25 if ring_r < 1.0 else 50), width=1)

    # ── 3. AEI data lattice — animated horizontal lines ───────────────────────
    LANE_COUNT = 12
    for lane in range(LANE_COUNT):
        lane_y = int(HEIGHT * 0.1 + lane * HEIGHT * 0.08)
        phase = (t * 2.0 + lane * 0.15) % 1.0
        bar_len = int(WIDTH * 0.6 * abs(math.sin(phase * math.pi)))
        bar_x = int(WIDTH * 0.05 + (WIDTH * 0.35) * (1.0 - abs(math.sin(phase * math.pi))))
        alpha = int(30 + 50 * abs(math.sin(phase * math.pi)))
        color_t = (math.sin(t * math.pi * 2 + lane) + 1) / 2.0
        bar_color = lerp_color(CYAN, AMBER, color_t * 0.3)
        draw.rectangle(
            [(bar_x, lane_y - 1), (bar_x + bar_len, lane_y + 1)],
            fill=rgba(bar_color, alpha),
        )

    # ── 4. Particle nodes (entropy-mapped) ────────────────────────────────────
    NODE_COUNT = 32
    for n in range(NODE_COUNT):
        seed_x = (n * 0.618033) % 1.0   # golden-ratio distribution
        seed_y = (n * 0.381966) % 1.0
        # Nodes drift slowly over time
        nx = int((seed_x + math.sin(t * math.pi * 2 + n) * 0.05) % 1.0 * WIDTH)
        ny = int((seed_y + math.cos(t * math.pi * 2 + n * 0.7) * 0.04) % 1.0 * HEIGHT)
        # Entropy tier → size + color
        tier = n % 3
        if tier == 0:
            node_color, node_r, node_alpha = CYAN, 4, 200
        elif tier == 1:
            node_color, node_r, node_alpha = AMBER, 3, 160
        else:
            node_color, node_r, node_alpha = GREEN, 2, 140

        # Glow halo
        for glow_r in [node_r + 6, node_r + 12]:
            glow_alpha = int(node_alpha * 0.12 * (1 - glow_r / (node_r + 15)))
            draw.ellipse(
                [(nx - glow_r, ny - glow_r), (nx + glow_r, ny + glow_r)],
                fill=rgba(node_color, max(0, glow_alpha)),
            )
        # Core dot
        draw.ellipse(
            [(nx - node_r, ny - node_r), (nx + node_r, ny + node_r)],
            fill=rgba(node_color, node_alpha),
        )

    # ── 5. Scanline overlay ───────────────────────────────────────────────────
    for sl_y in range(0, HEIGHT, 4):
        draw.line([(0, sl_y), (WIDTH, sl_y)], fill=rgba(CYAN, 5), width=1)

    # ── 6. Frame counter HUD ──────────────────────────────────────────────────
    # Draw text using default font (no external font file needed)
    hud_lines = [
        f"AEGIS V2.5  ///  FRAME {idx:04d}/{FRAME_COUNT - 1:04d}",
        f"SOVEREIGN_COMPUTE_SEQUENCE  ///  T={t:.4f}",
        f"AEI_CAPTURE_MODE: ACTIVE  ///  NODES: {NODE_COUNT}",
    ]
    for li, line in enumerate(hud_lines):
        draw.text(
            (24, 16 + li * 18),
            line,
            fill=rgba(CYAN, 140),
        )

    # Bottom-right telemetry
    draw.text(
        (WIDTH - 280, HEIGHT - 36),
        f"LATENCY_SERIES  ///  SEQ_{idx:04d}",
        fill=rgba(CYAN, 100),
    )

    return img


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating {FRAME_COUNT} frames → {OUTPUT_DIR}")
    print(f"Resolution: {WIDTH}×{HEIGHT}  |  Format: WebP (quality=85)")

    for idx in range(FRAME_COUNT):
        img = render_frame(idx)
        out_path = OUTPUT_DIR / f"{idx:04d}.webp"
        img.save(str(out_path), format="WEBP", quality=85, method=4)

        # Progress bar
        pct = (idx + 1) / FRAME_COUNT
        bar_len = 40
        filled = int(bar_len * pct)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r  [{bar}] {idx + 1:3d}/{FRAME_COUNT}  {out_path.name}", end="", flush=True)

    print(f"\n✓ Done — {FRAME_COUNT} frames saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
