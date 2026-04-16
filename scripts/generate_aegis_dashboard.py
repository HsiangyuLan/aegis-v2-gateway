#!/usr/bin/env python3
"""Generate the Cyber-FinOps Command Center hero PNG (aegis-dashboard.png).

Raster layout is produced with Pillow for reproducible, CI-friendly assets aligned
with ``ag-finops-model`` demo snapshot figures (not audited financials).

Outputs a 1920x1080 PNG suitable for the root README hero image.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from pathlib import Path
from typing import Final, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError as exc:
    print("Pillow is required: python3 -m pip install Pillow", file=sys.stderr)
    raise SystemExit(1) from exc

# --- Financial / demo constants (aligned with crates/ag-finops-model demo_snapshot) ---
VISA_TARIFF_EXEMPTION_USD: Final[float] = 100_000.0
COMPUTE_ARBITRAGE_ANNUAL_MIN_USD: Final[float] = 90_000.0
CACHE_HIT_RATE: Final[float] = 0.80
DEMO_TOTAL_REQUESTS: Final[int] = 1337
DEMO_P99_LATENCY_MS: Final[float] = 12.4
DEMO_COST_SAVED_USD: Final[float] = 0.004182

# Palette — cyber / C4 reference vibe (dark, neon blue/purple, alert red)
COLOR_BG_TOP: Final[Tuple[int, int, int]] = (8, 8, 12)
COLOR_BG_BOT: Final[Tuple[int, int, int]] = (18, 12, 28)
COLOR_GRID: Final[Tuple[int, int, int, int]] = (80, 120, 200, 40)
COLOR_NEON_BLUE: Final[Tuple[int, int, int]] = (0, 200, 255)
COLOR_NEON_PURPLE: Final[Tuple[int, int, int]] = (168, 85, 247)
COLOR_TEXT: Final[Tuple[int, int, int]] = (235, 235, 245)
COLOR_MUTED: Final[Tuple[int, int, int]] = (140, 140, 160)
COLOR_RED_ALERT: Final[Tuple[int, int, int]] = (220, 38, 38)
COLOR_RED_GLOW: Final[Tuple[int, int, int, int]] = (255, 60, 60, 120)

logger = logging.getLogger(__name__)


def _resolve_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a sans font if available; fall back to PIL bitmap default."""
    candidates: Sequence[str] = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )
    try:
        for path in candidates:
            if os.path.isfile(path):
                return ImageFont.truetype(path, size)
    except (OSError, IOError) as exc:
        logger.warning("Font load failed (%s), using default.", exc)
    try:
        return ImageFont.load_default()
    except (OSError, IOError) as exc:
        logger.warning("Default font load failed: %s", exc)
        return ImageFont.load_default()


def fill_vertical_gradient(
    img: Image.Image,
    top: Tuple[int, int, int],
    bottom: Tuple[int, int, int],
) -> None:
    """Fill ``img`` with a top-to-bottom RGB gradient.

    Args:
        img: Target RGB image.
        top: RGB tuple for the top scanline.
        bottom: RGB tuple for the bottom scanline.

    Raises:
        ValueError: If the image mode is not compatible.
    """
    try:
        w, h = img.size
        pixels = img.load()
        if pixels is None:
            raise ValueError("Cannot load pixel buffer")
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(top[0] * (1 - t) + bottom[0] * t)
            g = int(top[1] * (1 - t) + bottom[1] * t)
            b = int(top[2] * (1 - t) + bottom[2] * t)
            for x in range(w):
                pixels[x, y] = (r, g, b)
    except (TypeError, ValueError, ArithmeticError) as exc:
        logger.exception("Gradient fill failed: %s", exc)
        raise


def draw_subtle_grid(draw: ImageDraw.ImageDraw, w: int, h: int, step: int = 48) -> None:
    """Draw a faint perspective grid for depth."""
    try:
        for x in range(0, w + 1, step):
            draw.line([(x, 0), (x, h)], fill=COLOR_GRID, width=1)
        for y in range(0, h + 1, step):
            draw.line([(0, y), (w, y)], fill=COLOR_GRID, width=1)
    except (TypeError, ValueError) as exc:
        logger.warning("Grid draw skipped: %s", exc)


def draw_neon_panel(
    base: Image.Image,
    xy: Tuple[int, int, int, int],
    border_rgb: Tuple[int, int, int],
    title: str,
    font_title: ImageFont.ImageFont,
    font_body: ImageFont.ImageFont,
    body_lines: Sequence[str],
) -> None:
    """Draw a gradient-filled metric card with neon border and text."""
    try:
        x0, y0, x1, y1 = xy
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        for i in range(24, 0, -2):
            alpha = max(8, 40 - i)
            dl.rounded_rectangle(
                [x0 - i // 6, y0 - i // 6, x1 + i // 6, y1 + i // 6],
                radius=12 + i // 8,
                outline=(*border_rgb, alpha),
                width=1,
            )
        base.alpha_composite(layer)
        d = ImageDraw.Draw(base)
        inner = (x0 + 8, y0 + 36, x1 - 8, y1 - 8)
        for y in range(inner[1], inner[3]):
            t = (y - inner[1]) / max(inner[3] - inner[1], 1)
            r = int(22 + 20 * t)
            g = int(18 + 14 * t)
            b = int(35 + 28 * t)
            d.line([(inner[0], y), (inner[2], y)], fill=(r, g, b, 230))
        d.rounded_rectangle(xy, radius=14, outline=border_rgb, width=2)
        d.text((x0 + 16, y0 + 10), title, fill=COLOR_TEXT, font=font_title)
        by = y0 + 42
        for line in body_lines:
            d.text((x0 + 16, by), line, fill=COLOR_MUTED, font=font_body)
            by += 22
    except (TypeError, ValueError, OSError) as exc:
        logger.warning("Neon panel draw failed: %s", exc)


def _project(
    x: float,
    y: float,
    z: float,
    rot_y: float,
    rot_x: float,
    scale: float,
    cx: float,
    cy: float,
) -> Tuple[float, float]:
    """Apply simple 3D rotation and orthographic projection to XY."""
    try:
        cos_y, sin_y = math.cos(rot_y), math.sin(rot_y)
        cos_x, sin_x = math.cos(rot_x), math.sin(rot_x)
        x1 = x * cos_y + z * sin_y
        z1 = -x * sin_y + z * cos_y
        y1 = y * cos_x - z1 * sin_x
        return cx + x1 * scale, cy + y1 * scale
    except (TypeError, ValueError, ArithmeticError) as exc:
        logger.warning("Projection failed: %s", exc)
        return cx, cy


def draw_wireframe_ingestion_core(
    img: Image.Image,
    cx: int,
    cy: int,
    radius: float,
    color: Tuple[int, int, int],
) -> None:
    """Draw a pseudo-3D wireframe polyhedral core with orbital rings.

    Uses icosahedron vertices and edges for a dense technical look; particles
    are placed along ring parametrizations for a data-flow metaphor.
    """
    try:
        d = ImageDraw.Draw(img)
        phi = (1.0 + math.sqrt(5.0)) / 2.0
        verts: list[Tuple[float, float, float]] = []
        for s1 in (-1.0, 1.0):
            for s2 in (-1.0, 1.0):
                verts.append((0.0, s1, s2 * phi))
                verts.append((s1, s2 * phi, 0.0))
                verts.append((s1 * phi, 0.0, s2))
        scale = radius / 2.2
        rot_y, rot_x = 0.65, 0.35
        proj: list[Tuple[float, float]] = [
            _project(v[0], v[1], v[2], rot_y, rot_x, scale, float(cx), float(cy))
            for v in verts
        ]
        # Icosahedron edge length in model space ≈ 2; connect vertex pairs near that.
        edges: list[Tuple[int, int]] = []
        n = len(verts)
        for i in range(n):
            for j in range(i + 1, n):
                try:
                    ax, ay, az = verts[i]
                    bx, by, bz = verts[j]
                    dist = math.sqrt(
                        (ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2
                    )
                except (TypeError, ValueError, ArithmeticError):
                    continue
                if 1.9 < dist < 2.1:
                    edges.append((i, j))
        for i, j in edges:
            d.line([proj[i], proj[j]], fill=color, width=1)
        for ring in range(3):
            ry = rot_y + ring * 0.4
            pts: list[Tuple[float, float]] = []
            for k in range(64):
                t = k / 64 * 2 * math.pi
                rr = radius * (0.85 + ring * 0.12)
                px, py = _project(
                    math.cos(t) * rr / scale,
                    0.0,
                    math.sin(t) * rr / scale,
                    ry,
                    0.2 * ring,
                    0.45,
                    float(cx),
                    float(cy),
                )
                pts.append((px, py))
            for k in range(len(pts) - 1):
                d.line([pts[k], pts[k + 1]], fill=(*color, 180), width=1)
        for _ in range(120):
            t = (_ * 0.37) % (2 * math.pi)
            rr = radius * (0.3 + 0.55 * ((_ % 7) / 7.0))
            px, py = _project(
                math.cos(t) * rr / scale,
                math.sin(t * 2) * 0.3 * rr / scale,
                math.sin(t) * rr / scale,
                rot_y + 0.2,
                rot_x,
                0.35,
                float(cx),
                float(cy),
            )
            d.ellipse([px - 1, py - 1, px + 1, py + 1], fill=COLOR_NEON_BLUE)
    except (TypeError, ValueError, ArithmeticError) as exc:
        logger.warning("Wireframe core draw failed: %s", exc)


def draw_hologram_beam(
    overlay: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> None:
    """Soft trapezoid beam from core toward PII panel (holographic metaphor)."""
    try:
        d = ImageDraw.Draw(overlay)
        mid_y = (y0 + y1) // 2
        d.polygon(
            [
                (x0, y0),
                (x0 + 80, mid_y - 40),
                (x1 - 40, y1 - 20),
                (x1, y1),
                (x1 + 20, y1 + 30),
                (x0 + 40, y0 + 120),
            ],
            fill=(0, 180, 255, 25),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Beam draw failed: %s", exc)


def render_command_center(output_path: Path) -> None:
    """Render full 1920x1080 Cyber-FinOps dashboard to ``output_path``."""
    try:
        w, h = 1920, 1080
        base = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        rgb = Image.new("RGB", (w, h))
        fill_vertical_gradient(rgb, COLOR_BG_TOP, COLOR_BG_BOT)
        base.paste(rgb, (0, 0))
        draw = ImageDraw.Draw(base)
        draw_subtle_grid(draw, w, h, 56)

        font_xl = _resolve_font(28)
        font_lg = _resolve_font(20)
        font_md = _resolve_font(16)
        font_sm = _resolve_font(13)
        font_mono = _resolve_font(12)

        draw.text(
            (40, 24),
            "PROJECT ANTIGRAVITY — CYBER-FINOPS COMMAND CENTER (C4-STYLE CONTEXT)",
            fill=COLOR_TEXT,
            font=font_lg,
        )
        draw.text(
            (40, 52),
            "Aegis V2.5 Sovereign Core & FinOps Gateway · Day-1 execution surface (generated)",
            fill=COLOR_MUTED,
            font=font_sm,
        )
        draw.rounded_rectangle(
            [w - 280, 20, w - 24, 58], radius=8, outline=COLOR_NEON_BLUE, width=1
        )
        draw.text((w - 260, 30), "AI Chat", fill=COLOR_MUTED, font=font_sm)
        draw.rounded_rectangle(
            [w - 140, 20, w - 24, 58], radius=8, outline=COLOR_NEON_PURPLE, width=1
        )
        draw.text((w - 128, 30), "Code", fill=COLOR_MUTED, font=font_sm)

        # Left zone — fragmented ecosystem
        draw.rounded_rectangle(
            [32, 100, 420, 320], radius=16, outline=COLOR_NEON_BLUE, width=1
        )
        draw.text(
            (52, 112),
            "FRAGMENTED DATA / INGRESS",
            fill=COLOR_TEXT,
            font=font_md,
        )
        for i, line in enumerate(
            [
                "Metered LLM APIs",
                "Semantic token cache (80% posture)",
                "Edge request logs · Parquet pipeline",
            ]
        ):
            draw.text((52, 148 + i * 26), f"· {line}", fill=COLOR_MUTED, font=font_sm)

        # Metric cards (top row)
        card_y = 340
        draw_neon_panel(
            base,
            (40, card_y, 320, card_y + 110),
            COLOR_NEON_BLUE,
            "SAVED (SESSION)",
            font_md,
            font_sm,
            [f"${DEMO_COST_SAVED_USD:.6f} USD", "FinOps stub aggregate"],
        )
        draw_neon_panel(
            base,
            (340, card_y, 620, card_y + 110),
            COLOR_NEON_PURPLE,
            "COST / ROUTING",
            font_md,
            font_sm,
            ["local_edge: 1100", "cloud_gemini: 237"],
        )
        draw_neon_panel(
            base,
            (640, card_y, 920, card_y + 110),
            COLOR_NEON_BLUE,
            "SLA / DEGRADE",
            font_md,
            font_sm,
            ["~10 ms in-process budget", "K8s probes: second-scale"],
        )
        draw_neon_panel(
            base,
            (940, card_y, 1220, card_y + 110),
            COLOR_NEON_PURPLE,
            "P99 LATENCY",
            font_md,
            font_sm,
            [f"{DEMO_P99_LATENCY_MS} ms (demo snapshot)"],
        )
        draw_neon_panel(
            base,
            (1240, card_y, 1500, card_y + 110),
            COLOR_NEON_BLUE,
            "REQUESTS",
            font_md,
            font_sm,
            [f"{DEMO_TOTAL_REQUESTS} total (demo)"],
        )

        cx, cy = 960, 520
        draw_wireframe_ingestion_core(base, cx, cy, 220, COLOR_NEON_BLUE)
        draw.text(
            (cx - 120, cy + 200),
            "INGESTION CORE · ag-gateway (Axum)",
            fill=COLOR_TEXT,
            font=font_md,
        )
        draw.text(
            (cx - 140, cy + 228),
            "Zero-copy Arc[u8] · ONNX NER hot path · tower timeout layers",
            fill=COLOR_MUTED,
            font=font_sm,
        )

        # Visa & TCO arbitrage — high contrast panel
        arb_x0, arb_y0 = 1520, 100
        arb_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ad = ImageDraw.Draw(arb_layer)
        ad.rounded_rectangle(
            [arb_x0, arb_y0, 1880, 420], radius=18, fill=(168, 85, 247, 35)
        )
        ad.rounded_rectangle(
            [arb_x0, arb_y0, 1880, 420], radius=18, outline=COLOR_NEON_PURPLE, width=3
        )
        base.alpha_composite(arb_layer)
        draw = ImageDraw.Draw(base)
        draw.text(
            (arb_x0 + 20, arb_y0 + 16),
            "VISA & TCO ARBITRAGE OVERVIEW",
            fill=COLOR_TEXT,
            font=font_lg,
        )
        draw.text(
            (arb_x0 + 20, arb_y0 + 52),
            f"USD {VISA_TARIFF_EXEMPTION_USD:,.0f}",
            fill=(255, 255, 100),
            font=font_xl,
        )
        draw.text(
            (arb_x0 + 20, arb_y0 + 92),
            "H-1B tariff exemption framing · F-1 COS portfolio narrative",
            fill=COLOR_MUTED,
            font=font_sm,
        )
        draw.text(
            (arb_x0 + 20, arb_y0 + 150),
            f"> USD {COMPUTE_ARBITRAGE_ANNUAL_MIN_USD:,.0f} / yr",
            fill=(0, 255, 200),
            font=font_xl,
        )
        draw.text(
            (arb_x0 + 20, arb_y0 + 190),
            f"Projected compute arbitrage · {CACHE_HIT_RATE:.0%} cache + Rust (model)",
            fill=COLOR_MUTED,
            font=font_sm,
        )
        draw.text(
            (arb_x0 + 20, arb_y0 + 240),
            "Not legal, immigration, or tax advice.",
            fill=(200, 100, 100),
            font=font_sm,
        )

        # Right mid — operator value
        draw.rounded_rectangle(
            [1520, 440, 1880, 620], radius=16, outline=COLOR_NEON_BLUE, width=1
        )
        draw.text(
            (1540, 452),
            "OPERATOR OUTPUT",
            fill=COLOR_TEXT,
            font=font_md,
        )
        draw.text(
            (1540, 488),
            "Unified FinOps posture",
            fill=COLOR_MUTED,
            font=font_sm,
        )
        draw.text(
            (1540, 518),
            "Real-time PII redaction telemetry",
            fill=COLOR_MUTED,
            font=font_sm,
        )
        draw.text(
            (1540, 548),
            "SOC2-style hook audit trail (local)",
            fill=COLOR_MUTED,
            font=font_sm,
        )

        # PII zone + holographic beam
        beam = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_hologram_beam(beam, cx - 40, cy + 80, 400, 780)
        beam = beam.filter(ImageFilter.GaussianBlur(radius=8))
        base.alpha_composite(beam)

        pii_y0 = 680
        draw.rounded_rectangle(
            [32, pii_y0, 1888, 1040], radius=16, outline=COLOR_RED_ALERT, width=3
        )
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rounded_rectangle(
            [28, pii_y0 - 4, 1892, 1044], radius=18, outline=COLOR_RED_GLOW, width=6
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
        base.alpha_composite(glow)

        draw = ImageDraw.Draw(base)
        draw.text(
            (52, pii_y0 + 12),
            "PII_SCAN_ENGINE — ONNX NER PRIMARY PATH (regex = fast lane)",
            fill=COLOR_RED_ALERT,
            font=font_lg,
        )
        logs = [
            "[12:01:02.441] tokio::time::timeout OK — entity EMAIL masked (NER)",
            "[12:01:02.443] span redacted · len=4096 · Arc[u8] handoff",
            "[12:01:02.445] circuit: closed · failures=0 · degrade budget 10ms",
            "[12:01:02.448] audit: preToolUse secret scan — no leak (heuristic)",
        ]
        ly = pii_y0 + 52
        for line in logs:
            draw.text((52, ly), line, fill=(255, 200, 200), font=font_mono)
            ly += 22

        base.convert("RGB").save(output_path, "PNG", optimize=True)
        logger.info("Wrote %s", output_path)
    except (OSError, ValueError, TypeError) as exc:
        logger.exception("Render failed: %s", exc)
        raise


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    repo_root = Path(__file__).resolve().parents[1]
    default_out = repo_root / "aegis-dashboard.png"
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_out,
        help=f"Output PNG path (default: {default_out})",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return p.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        render_command_center(args.output.resolve())
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("generate_aegis_dashboard failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
