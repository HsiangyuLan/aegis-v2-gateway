#!/usr/bin/env python3
"""
Create a minimal valid ONNX model for Sprint 4 SEP testing.

The generated model is a Gather-based embedding lookup:
  input_ids (int64, [batch, seq])  →  Gather  →  last_hidden_state (float32, [batch, seq, 384])
  attention_mask (int64, [batch, seq])  →  (accepted but ignored, for API compatibility)

Mathematical correctness: each token is looked up in a random 30522×384
embedding table.  The output has the right shape for our linear_probe()
function.  NOT semantically meaningful — for production use the real
sentence-transformers/all-MiniLM-L6-v2 model.

Production download:
    pip install sentence-transformers optimum[onnxruntime]
    python -c "
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    model = ORTModelForFeatureExtraction.from_pretrained(
        'sentence-transformers/all-MiniLM-L6-v2', export=True)
    model.save_pretrained('models/')"
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
MODEL_PATH = ROOT / "models" / "minilm-v2.onnx"

HIDDEN_DIM  = 384
VOCAB_SIZE  = 30_522
OPSET       = 17


def create(out_path: Path = MODEL_PATH) -> None:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Random embedding weights (seed=42 → reproducible) ────────────────────
    rng = np.random.default_rng(42)
    weights = rng.normal(0.0, 0.02, (VOCAB_SIZE, HIDDEN_DIM)).astype(np.float32)
    embedding_init = numpy_helper.from_array(weights, name="embedding_weights")

    # ── Graph inputs / outputs ────────────────────────────────────────────────
    input_ids = helper.make_tensor_value_info(
        "input_ids", TensorProto.INT64, [None, None]
    )
    attention_mask = helper.make_tensor_value_info(
        "attention_mask", TensorProto.INT64, [None, None]
    )
    last_hidden_state = helper.make_tensor_value_info(
        "last_hidden_state", TensorProto.FLOAT, [None, None, HIDDEN_DIM]
    )

    # ── Gather: embedding_weights[input_ids, :] → [batch, seq, hidden_dim] ───
    # ONNX Gather with axis=0:
    #   data.shape    = [VOCAB_SIZE, HIDDEN_DIM]
    #   indices.shape = [batch, seq]
    #   output.shape  = [batch, seq, HIDDEN_DIM]  ✓
    gather = helper.make_node(
        "Gather",
        inputs=["embedding_weights", "input_ids"],
        outputs=["last_hidden_state"],
        axis=0,
    )

    graph = helper.make_graph(
        [gather],
        "dummy_minilm_v2",
        inputs=[input_ids, attention_mask],
        outputs=[last_hidden_state],
        initializer=[embedding_init],
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid("", OPSET)],
    )
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(out_path))

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"[DUMMY_MODEL_CREATED]  {out_path}")
    print(f"  Embedding table : {VOCAB_SIZE:,} × {HIDDEN_DIM}  (float32)")
    print(f"  File size       : {size_mb:.1f} MB")
    print(f"  ONNX opset      : {OPSET}")
    print()
    print("  NOTE: Random weights — use real MiniLM-L6-v2 for production.")
    print("        See module docstring for production download command.")


if __name__ == "__main__":
    if MODEL_PATH.exists():
        print(f"Model already exists: {MODEL_PATH} "
              f"({MODEL_PATH.stat().st_size / 1_048_576:.1f} MB)")
        sys.exit(0)
    try:
        import onnx  # noqa: F401
    except ImportError:
        print("ERROR: onnx not installed. Run: pip install 'onnx>=1.15'", file=sys.stderr)
        sys.exit(1)
    create()
