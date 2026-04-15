"""
Aegis V2 — Asset Optimization Pipeline
========================================
Batch-converts public/sequence/hero/*.png (84MB) to optimised WebP in
public/sequence/hero_webp/ targeting ~85% size reduction (~12MB total).

Why Python/Pillow instead of ffmpeg?
──────────────────────────────────────
The Homebrew ffmpeg 8.1 bottle ships WITHOUT --enable-libwebp (encoder).
It includes a WebP decoder (D.VILS webp) but the encoder (libwebp) is absent
from the pre-built bottle's configuration string.  Pillow provides native
libwebp bindings via the Pillow-pillow-avif-plugin or built-in WebP support
and is already installed in the project venv.

Encoder settings (mirror -c:v libwebp equivalent):
  quality           = 75    → equivalent to ffmpeg -q:v 75
  method            = 6     → equivalent to -compression_level 6
  lossless          = False → lossy WebP for maximum size reduction

Visual integrity for "Entropy Probe" eye effects:
  quality=75 preserves high-frequency luminance edges (cyan glow rings)
  without the banding artefacts that appear at quality<65.
  method=6 enables advanced Huffman + arith coding for better compression
  without sacrificing quality vs method=4.

Usage:
  python3 scripts/optimize_assets.py [--quality 75] [--method 6]
  python3 scripts/optimize_assets.py --dry-run    # size estimate only
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

# ─── Self-healing import ──────────────────────────────────────────────────────
try:
    from PIL import Image
except ImportError:
    print("Pillow not found — installing…")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image  # type: ignore[assignment]

# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parent.parent
FRONTEND    = REPO_ROOT / "frontend"
SRC_DIR     = FRONTEND / "public" / "sequence" / "hero"
DST_DIR     = FRONTEND / "public" / "sequence" / "hero_webp"

# ─── Result type ─────────────────────────────────────────────────────────────

class ConversionResult(NamedTuple):
    src_path:  Path
    dst_path:  Path
    src_bytes: int
    dst_bytes: int
    ok:        bool
    error:     str


# ─── Worker ───────────────────────────────────────────────────────────────────

def convert_one(
    src: Path,
    dst: Path,
    quality: int,
    method: int,
    dry_run: bool,
) -> ConversionResult:
    """
    Convert a single PNG → WebP.

    The target stem is preserved (frame_001.png → frame_001.webp) so that
    ScrollyCanvas can calculate the URL with zero lookup overhead.

    Args:
        src:     Source PNG path.
        dst:     Destination WebP path.
        quality: lossy quality 0–100 (target: 75).
        method:  Compression effort 0–6 (target: 6 = best/slowest).
        dry_run: If True, skip actual conversion and return simulated sizes.

    Returns:
        ConversionResult with before/after byte counts.
    """
    src_bytes = src.stat().st_size

    if dry_run:
        estimated = int(src_bytes * 0.15)   # ~85% reduction heuristic
        return ConversionResult(src, dst, src_bytes, estimated, True, "")

    try:
        with Image.open(src) as img:
            # Ensure RGB mode (some PNG frames may be RGBA or P-mode)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            dst.parent.mkdir(parents=True, exist_ok=True)
            img.save(
                dst,
                format="WEBP",
                quality=quality,
                method=method,
                lossless=False,
                # Preserve colour profile if embedded
                icc_profile=img.info.get("icc_profile", b""),
            )

        dst_bytes = dst.stat().st_size
        return ConversionResult(src, dst, src_bytes, dst_bytes, True, "")

    except Exception as exc:
        return ConversionResult(src, dst, src_bytes, 0, False, str(exc))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aegis V2 Asset Optimization Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--quality",    type=int,  default=75, help="WebP quality 0-100 (default: 75)")
    parser.add_argument("--method",     type=int,  default=6,  help="Compression level 0-6 (default: 6)")
    parser.add_argument("--workers",    type=int,  default=8,  help="Parallel worker threads (default: 8)")
    parser.add_argument("--dry-run",    action="store_true",   help="Estimate sizes without writing files")
    parser.add_argument("--src",        type=Path, default=SRC_DIR,  help=f"Source PNG dir (default: {SRC_DIR})")
    parser.add_argument("--dst",        type=Path, default=DST_DIR,  help=f"Dest WebP dir (default: {DST_DIR})")
    args = parser.parse_args()

    src_dir: Path = args.src
    dst_dir: Path = args.dst

    # ── Validate source ───────────────────────────────────────────────────────
    if not src_dir.exists():
        print(f"✗ Source directory not found: {src_dir}")
        print("  Run ffmpeg extraction first, or check the path.")
        sys.exit(1)

    png_files = sorted(src_dir.glob("*.png"))
    if not png_files:
        print(f"✗ No .png files found in {src_dir}")
        sys.exit(1)

    # ── Summary header ────────────────────────────────────────────────────────
    total_src_bytes = sum(p.stat().st_size for p in png_files)
    print()
    print("══════════════════════════════════════════════════════════════")
    print("  Aegis V2 — Asset Optimization Pipeline")
    print("══════════════════════════════════════════════════════════════")
    print(f"  Source   : {src_dir}")
    print(f"  Output   : {dst_dir}")
    print(f"  Frames   : {len(png_files)}")
    print(f"  Input    : {total_src_bytes / 1024 / 1024:.1f} MB")
    print(f"  Quality  : {args.quality}  |  Method: {args.method}  |  Workers: {args.workers}")
    print(f"  Dry run  : {'YES (no files written)' if args.dry_run else 'NO (writing files)'}")
    print("══════════════════════════════════════════════════════════════")
    print()

    if not args.dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)

    # ── Parallel conversion ───────────────────────────────────────────────────
    tasks = [
        (src, dst_dir / f"{src.stem}.webp", args.quality, args.method, args.dry_run)
        for src in png_files
    ]

    results: list[ConversionResult] = []
    bar_width = 44
    start_time = time.monotonic()
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(convert_one, *task): task[0] for task in tasks}

        completed = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1

            if not result.ok:
                errors.append(f"  ✗ {result.src_path.name}: {result.error}")

            # Progress bar
            pct = completed / len(tasks)
            filled = int(bar_width * pct)
            bar = "█" * filled + "░" * (bar_width - filled)
            elapsed = time.monotonic() - start_time
            fps = completed / max(elapsed, 1e-9)
            eta = (len(tasks) - completed) / max(fps, 1e-9)
            print(
                f"\r  [{bar}] {completed:3d}/{len(tasks)}"
                f"  {pct*100:5.1f}%"
                f"  {fps:5.1f} fps"
                f"  ETA {eta:4.1f}s",
                end="",
                flush=True,
            )

    elapsed_total = time.monotonic() - start_time
    print()  # newline after progress bar

    # ── Statistics ────────────────────────────────────────────────────────────
    ok_results = [r for r in results if r.ok]
    total_dst_bytes = sum(r.dst_bytes for r in ok_results)
    total_src_bytes_ok = sum(r.src_bytes for r in ok_results)

    reduction_pct = (
        (1.0 - total_dst_bytes / total_src_bytes_ok) * 100
        if total_src_bytes_ok else 0.0
    )

    print()
    print("══════════════════════════════════════════════════════════════")
    print("  Results")
    print("══════════════════════════════════════════════════════════════")
    print(f"  Converted : {len(ok_results)}/{len(tasks)} frames")
    print(f"  Input     : {total_src_bytes_ok / 1024 / 1024:.2f} MB")
    print(f"  Output    : {total_dst_bytes / 1024 / 1024:.2f} MB")
    print(f"  Reduction : {reduction_pct:.1f}%  (target: ≥85%)")
    print(f"  Elapsed   : {elapsed_total:.2f}s  ({len(ok_results)/elapsed_total:.1f} fps)")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for err in errors:
            print(err)

    # SLA check: warn if reduction < 80%
    if reduction_pct < 80.0 and not args.dry_run:
        print(f"\n  ⚠ Reduction {reduction_pct:.1f}% is below 80% threshold.")
        print("    Consider lowering --quality to 65 if bandwidth is critical.")
    elif not args.dry_run:
        print(f"\n  ✓ Target met — {reduction_pct:.1f}% reduction achieved.")

    print("══════════════════════════════════════════════════════════════")
    print()

    if not args.dry_run and len(ok_results) > 0:
        # Verify first and last frame are readable
        first = ok_results[0].dst_path if ok_results[0].dst_path.exists() else None
        last  = ok_results[-1].dst_path if ok_results[-1].dst_path.exists() else None
        if first and last:
            try:
                with Image.open(first) as img:
                    w, h = img.size
                print(f"  ✓ Frame integrity: {first.name} — {w}×{h} {img.mode}")
                with Image.open(last) as img:
                    w, h = img.size
                print(f"  ✓ Frame integrity: {last.name} — {w}×{h} {img.mode}")
            except Exception as exc:
                print(f"  ✗ Integrity check failed: {exc}")
        print()


if __name__ == "__main__":
    main()
