#!/usr/bin/env python3
"""
Sprint 4.1 — Download sentence-transformers/all-MiniLM-L6-v2 ONNX model.

Strategy (tried in order):
  1. huggingface_hub.hf_hub_download  — lightweight; downloads pre-exported
     ONNX file directly from the model repo (onnx/model.onnx).
  2. optimum export                   — heavier; exports on-the-fly from the
     original PyTorch weights if the pre-built ONNX is unavailable.

Output files:
  models/minilm-v2.onnx        — ONNX model (~23 MB float32)
  models/tokenizer/            — tokenizer files for sprint4_1_test.py

Production note:
  The downloaded model is the full-precision float32 variant.
  For production, consider the quantized variant (~6 MB) at
  onnx/model_quantized.onnx with INT8 arithmetic for lower latency.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT       = Path(__file__).parent.parent
MODEL_OUT  = ROOT / "models" / "minilm-v2.onnx"
TOK_OUT    = ROOT / "models" / "tokenizer"
REPO_ID    = "sentence-transformers/all-MiniLM-L6-v2"


# ── Helper ────────────────────────────────────────────────────────────────────

def _size_mb(p: Path) -> str:
    return f"{p.stat().st_size / 1_048_576:.1f} MB"


def _check_io(model_path: Path) -> None:
    """Print ONNX model input/output names using onnxruntime."""
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        inputs  = [i.name for i in sess.get_inputs()]
        outputs = [o.name for o in sess.get_outputs()]
        print(f"  ONNX inputs  : {inputs}")
        print(f"  ONNX outputs : {outputs}")
    except ImportError:
        print("  (install onnxruntime to inspect model I/O)")
    except Exception as exc:
        print(f"  (model I/O inspection failed: {exc})")


# ── Method 1: huggingface_hub direct download ─────────────────────────────────

def download_via_hf_hub() -> bool:
    """Try to download the pre-exported ONNX file from the HF repo."""
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


# ── Method 2: optimum export ──────────────────────────────────────────────────

def download_via_optimum() -> bool:
    """Export ONNX model on-the-fly using optimum."""
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
    except ImportError:
        print("  optimum not installed — run: pip install optimum[onnxruntime]")
        return False

    import tempfile

    print(f"  Exporting {REPO_ID} via optimum (downloads ~90 MB PyTorch weights) ...")
    t0 = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            model = ORTModelForFeatureExtraction.from_pretrained(
                REPO_ID, export=True
            )
            model.save_pretrained(tmp)
            # optimum saves as model.onnx in the temp dir
            src = Path(tmp) / "model.onnx"
            if not src.exists():
                # Older optimum versions might use a different name
                candidates = list(Path(tmp).glob("*.onnx"))
                if candidates:
                    src = candidates[0]
                else:
                    print("  No .onnx file found in optimum export.")
                    return False
            shutil.copy(src, MODEL_OUT)
        elapsed = time.monotonic() - t0
        print(f"  Exported in {elapsed:.1f}s → {MODEL_OUT} ({_size_mb(MODEL_OUT)})")
        return True
    except Exception as exc:
        print(f"  optimum export failed: {exc}")
        return False


# ── Tokenizer download ────────────────────────────────────────────────────────

def download_tokenizer() -> bool:
    """Download and save the tokenizer for sprint4_1_test.py."""
    try:
        from transformers import AutoTokenizer
    except ImportError:
        print("  transformers not installed — tokenizer skipped.")
        return False

    print(f"  Downloading tokenizer for {REPO_ID} ...")
    try:
        tok = AutoTokenizer.from_pretrained(REPO_ID)
        TOK_OUT.mkdir(parents=True, exist_ok=True)
        tok.save_pretrained(str(TOK_OUT))
        print(f"  Tokenizer saved → {TOK_OUT}/")
        return True
    except Exception as exc:
        print(f"  Tokenizer download failed: {exc}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)

    # ── Check if already downloaded ──────────────────────────────────────────
    if MODEL_OUT.exists() and MODEL_OUT.stat().st_size > 5_000_000:  # > 5 MB
        print(f"[OK] Model already present: {MODEL_OUT} ({_size_mb(MODEL_OUT)})")
        _check_io(MODEL_OUT)
    else:
        print(f"Downloading ONNX model → {MODEL_OUT}")
        print()

        # Method 1
        print("[Method 1] huggingface_hub direct download ...")
        ok = download_via_hf_hub()

        # Method 2 fallback
        if not ok:
            print()
            print("[Method 2] optimum on-the-fly export ...")
            ok = download_via_optimum()

        if not ok:
            print()
            print("ERROR: Both download methods failed.")
            print("  The dummy model is still at models/minilm-v2.onnx (if created).")
            print("  Alternatively, manually place the ONNX model at models/minilm-v2.onnx")
            return 1

        print()
        print(f"[RUST_CORE_READY] Model I/O inspection:")
        _check_io(MODEL_OUT)

    # ── Tokenizer ─────────────────────────────────────────────────────────────
    print()
    if TOK_OUT.exists():
        print(f"[OK] Tokenizer already present: {TOK_OUT}/")
    else:
        print("Downloading tokenizer ...")
        download_tokenizer()

    print()
    print("=" * 60)
    print(f"  Model  : {MODEL_OUT} ({_size_mb(MODEL_OUT)})")
    print(f"  Tokens : {TOK_OUT}/")
    print()
    print("  Next step:")
    print("    python scripts/sprint4_1_test.py")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
