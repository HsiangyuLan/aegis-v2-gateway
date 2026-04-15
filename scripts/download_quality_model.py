#!/usr/bin/env python3
"""
Download a larger MiniLM variant (all-MiniLM-L12-v2) ONNX for the cascade
**quality** path (學者 / 君主 tier).  Reuses the same WordPiece tokenizer as
L6 when served from ``models/tokenizer/`` (download via ``download_model.py``).

Output:
  models/minilm-l12.onnx   — float32 ONNX from the HuggingFace repo when available
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODEL_OUT = ROOT / "models" / "minilm-l12.onnx"
REPO_ID = "sentence-transformers/all-MiniLM-L12-v2"


def _size_mb(p: Path) -> str:
    return f"{p.stat().st_size / 1_048_576:.1f} MB"


def download_via_hf_hub() -> bool:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("  huggingface_hub not installed — skipping.")
        return False

    for onnx_filename in ("onnx/model.onnx", "model.onnx"):
        try:
            print(f"  Trying {REPO_ID}/{onnx_filename} ...")
            t0 = time.monotonic()
            path = hf_hub_download(
                repo_id=REPO_ID,
                filename=onnx_filename,
                local_dir=str(ROOT / "models" / "_hf_cache"),
                local_dir_use_symlinks=False,
            )
            elapsed = time.monotonic() - t0
            shutil.copy(path, MODEL_OUT)
            print(f"  Downloaded in {elapsed:.1f}s → {MODEL_OUT} ({_size_mb(MODEL_OUT)})")
            return True
        except Exception as exc:
            print(f"  Not found or error: {exc}")

    return False


def download_via_optimum() -> bool:
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
    except ImportError:
        print("  optimum not installed — run: pip install optimum[onnxruntime]")
        return False

    import tempfile

    print(f"  Exporting {REPO_ID} via optimum ...")
    t0 = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            model = ORTModelForFeatureExtraction.from_pretrained(
                REPO_ID,
                export=True,
            )
            model.save_pretrained(tmp)
            src = Path(tmp) / "model.onnx"
            if not src.exists():
                candidates = list(Path(tmp).glob("*.onnx"))
                if not candidates:
                    print("  No .onnx file found in optimum export.")
                    return False
                src = candidates[0]
            shutil.copy(src, MODEL_OUT)
        elapsed = time.monotonic() - t0
        print(f"  Exported in {elapsed:.1f}s → {MODEL_OUT} ({_size_mb(MODEL_OUT)})")
        return True
    except Exception as exc:
        print(f"  optimum export failed: {exc}")
        return False


def main() -> int:
    print(f"Aegis V2 — quality-path ONNX ({REPO_ID})")
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)

    if download_via_hf_hub():
        return 0
    if download_via_optimum():
        return 0

    print("ERROR: could not obtain ONNX weights.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
