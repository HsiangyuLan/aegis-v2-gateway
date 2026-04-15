#!/usr/bin/env python3
"""
Aegis V2 FinOps Telemetry Analysis Script
──────────────────────────────────────────

Reads all Parquet log files produced by the gateway's RequestLogger and
performs cost-savings and latency aggregations using Polars' streaming
execution engine.

Why streaming?
──────────────
In production, the gateway processes millions of requests per day.  The
resulting Parquet files can easily exceed the available RAM on the edge node
running this script.  Polars' ``collect(engine="streaming")`` uses a
Morsel-Driven Parallelism algorithm that processes data in small chunks,
keeping peak memory usage far below the total dataset size — enabling
out-of-core analytics on constrained hardware.

Usage
─────
    python scripts/finops_analysis.py [LOG_DIR]

    LOG_DIR defaults to ``./logs/finops`` (configurable via
    AEGIS_FINOPS_LOG_DIR environment variable).

Output
──────
Per-destination summary table:

  routed_to    | total_requests | total_cost_saved_usd | avg_latency_ms | p95_latency_ms
  -------------|----------------|----------------------|----------------|---------------
  local_edge   | 182,341        | 2.547                | 54.2           | 78.1
  cloud_gemini | 67,421         | 0.000                | 243.8          | 891.4

Exit codes: 0 = success, 1 = no log files found, 2 = Polars error.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import polars as pl


# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_LOG_DIR = os.environ.get("AEGIS_FINOPS_LOG_DIR", "./logs/finops")


def _find_parquet_files(log_dir: Path) -> list[Path]:
    """Return all gateway log Parquet files in ``log_dir``."""
    return sorted(log_dir.glob("requests_*.parquet"))


def analyze(log_dir: Path) -> pl.DataFrame:
    """
    Read all Parquet files in ``log_dir`` and return an aggregated summary.

    Uses ``pl.scan_parquet()`` (lazy API) combined with
    ``collect(engine="streaming")`` to process data out-of-core.

    The streaming engine applies:
      * Predicate pushdown  — filters are pushed to the Parquet reader
      * Projection pushdown — only required columns are read from disk
      * Morsel parallelism  — data flows in small chunks through the pipeline

    This means peak RAM usage is O(chunk_size) not O(total_dataset_size).

    Returns
    -------
    pl.DataFrame with columns:
      routed_to, total_requests, total_cost_saved_usd, avg_latency_ms,
      p95_latency_ms
    """
    files = _find_parquet_files(log_dir)
    if not files:
        raise FileNotFoundError(
            f"No Parquet log files found in '{log_dir}'. "
            "Ensure the gateway has processed at least one request and the "
            "FinOps flush interval has elapsed."
        )

    # scan_parquet with a glob covers all matching files; combined with
    # streaming engine this handles datasets larger than available RAM.
    glob_pattern = str(log_dir / "requests_*.parquet")

    result: pl.DataFrame = (
        pl.scan_parquet(glob_pattern)
        .group_by("routed_to")
        .agg(
            [
                pl.len().alias("total_requests"),
                pl.sum("cost_saved_usd").alias("total_cost_saved_usd"),
                pl.mean("latency_ms").alias("avg_latency_ms"),
                pl.quantile("latency_ms", 0.95).alias("p95_latency_ms"),
            ]
        )
        .sort("routed_to")
        .collect(engine="streaming")
    )

    return result


def _format_report(df: pl.DataFrame, log_dir: Path) -> str:
    """Render a human-readable FinOps report."""
    total_requests = df["total_requests"].sum()
    total_savings = df["total_cost_saved_usd"].sum()

    lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "  Aegis V2 FinOps Report  (Polars Streaming Engine)",
        f"  Log directory : {log_dir.resolve()}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        df.to_string(),
        "",
        f"  Total requests    : {total_requests:,}",
        f"  Total cost saved  : ${total_savings:.6f} USD",
        "",
    ]

    if total_requests > 0:
        local_rows = df.filter(pl.col("routed_to") == "local_edge")
        local_count = (
            local_rows["total_requests"].sum() if len(local_rows) > 0 else 0
        )
        pct_local = 100.0 * local_count / total_requests
        lines += [
            f"  Edge offload rate : {pct_local:.1f}% "
            f"({local_count:,} / {total_requests:,} requests handled locally)",
            "",
        ]

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def main() -> int:
    log_dir_str = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_LOG_DIR
    log_dir = Path(log_dir_str)

    try:
        df = analyze(log_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"POLARS ERROR: {exc}", file=sys.stderr)
        return 2

    print(_format_report(df, log_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
