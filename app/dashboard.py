#!/usr/bin/env python3
"""
Aegis V2 — Real-Time FinOps Terminal Dashboard
────────────────────────────────────────────────
Displays live system metrics using the rich library.

Usage:
    python app/dashboard.py [--model models/minilm-v2-int8.onnx]

Metrics shown:
  [RUST_ENGINE_STATUS]   — whether the ONNX engine is loaded and healthy
  [P99_LATENCY]          — rolling P99 over the last N inference calls
  [TOTAL_SAVED_USD]      — cumulative $ saved vs cloud-only routing
                           (basis: GPT-4 $30 / 1M tokens)

Press Ctrl+C to exit.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from rich import box
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("ERROR: rich not installed. Run: pip install rich", file=sys.stderr)
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_MODEL     = "models/minilm-v2-int8.onnx"
DEFAULT_QUALITY   = os.environ.get("AEGIS_RUST_QUALITY_MODEL_PATH", "models/minilm-l12.onnx")
DEFAULT_TOK       = "models/tokenizer/tokenizer.json"
FINOPS_LOG_DIR    = Path("logs/finops")
REFRESH_INTERVAL  = 1.0      # seconds between dashboard updates
BENCH_INTERVAL    = 5.0      # seconds between live latency measurements
LATENCY_WINDOW    = 50       # rolling window size for P99 calculation
GPT4_USD_PER_1M   = 30.0    # $/1M tokens — basis for cost savings

BENCH_PROMPTS = [
    b"What is 2+2?",
    b"Explain gradient descent.",
    b"How to implement a binary search tree?",
    b"What is the capital of France?",
    b"Compare REST and GraphQL APIs.",
]

# ── State ─────────────────────────────────────────────────────────────────────

class DashboardState:
    def __init__(self) -> None:
        self.engine_ready:    bool          = False
        self.engine_info:     str           = "Initialising..."
        self.pool_size:       int           = 0
        self.model_path:      str           = DEFAULT_MODEL
        self.model_size_mb:   float         = 0.0
        self.has_tokenizer:   bool          = False
        self.cascade_quality_loaded: bool  = False
        self.tier_sentinel:   int           = 0
        self.tier_scholar:    int           = 0
        self.tier_monarch:    int           = 0

        self.latency_history: deque[float]  = deque(maxlen=LATENCY_WINDOW)
        self.p50_ms:          float         = 0.0
        self.p95_ms:          float         = 0.0
        self.p99_ms:          float         = 0.0
        self.throughput:      float         = 0.0

        self.total_requests:  int           = 0
        self.local_requests:  int           = 0
        self.cloud_requests:  int           = 0
        self.total_saved_usd: float         = 0.0
        self.local_rate_pct:  float         = 0.0

        self.last_bench_ms:   float         = time.monotonic()
        self.uptime_s:        float         = 0.0
        self._start:          float         = time.monotonic()


state = DashboardState()

# ── Engine / inference ────────────────────────────────────────────────────────

_engine    = None
_compute   = None
_is_cascade = False


def _init_engine(model_path: str, tok_path: str | None, quality_path: str | None) -> None:
    global _engine, _compute, _is_cascade

    mp = Path(model_path)
    tp = Path(tok_path) if tok_path else None
    q_raw = (quality_path or "").strip()
    qp = Path(q_raw) if q_raw else None

    try:
        from aegis_rust_core import CascadingEngine, compute_cascade_entropy_score

        _engine = CascadingEngine(
            model_path,
            str(qp) if (qp and qp.is_file()) else None,
            64,
            str(tp) if (tp and tp.exists()) else None,
            max(1, os.cpu_count() or 4),
            float(os.environ.get("AEGIS_CASCADE_UNCERTAINTY_TRIGGER", "0.35")),
            float(os.environ.get("AEGIS_CASCADE_MONARCH_UNCERTAINTY", "0.42")),
        )
        _compute = compute_cascade_entropy_score
        _is_cascade = True

        state.engine_ready = True
        state.pool_size = _engine.pool_size_fast()
        state.has_tokenizer = _engine.has_real_tokenizer()
        state.cascade_quality_loaded = _engine.has_quality_path()
        state.model_path = model_path
        state.model_size_mb = mp.stat().st_size / 1_048_576 if mp.exists() else 0.0
        q_note = (
            f"quality=ON ({_engine.pool_size_quality()} sess)"
            if state.cascade_quality_loaded
            else "quality=OFF"
        )
        state.engine_info = (
            f"CASCADE  {'INT8' if 'int8' in model_path.lower() else 'FP32'} fast  "
            f"pool={state.pool_size}  {q_note}  "
            f"tok={'real' if state.has_tokenizer else 'placeholder'}"
        )
        s, c, m = _engine.tier_counts()
        state.tier_sentinel, state.tier_scholar, state.tier_monarch = int(s), int(c), int(m)
        return
    except Exception as exc:
        state.engine_info = f"Cascade load failed ({exc}); trying single engine…"

    try:
        from aegis_rust_core import EmbeddingEngine, compute_entropy_score

        _engine = EmbeddingEngine(
            model_path,
            max_seq_len    = 64,
            tokenizer_path = str(tp) if (tp and tp.exists()) else None,
            num_sessions   = max(1, os.cpu_count() or 4),
        )
        _compute = compute_entropy_score
        _is_cascade = False

        state.engine_ready  = True
        state.pool_size     = _engine.pool_size()
        state.has_tokenizer = _engine.has_real_tokenizer()
        state.cascade_quality_loaded = False
        state.model_path    = model_path
        state.model_size_mb = mp.stat().st_size / 1_048_576 if mp.exists() else 0.0
        state.engine_info   = (
            f"{'INT8' if 'int8' in model_path.lower() else 'FP32'} ONNX  "
            f"pool={state.pool_size}  "
            f"tok={'real' if state.has_tokenizer else 'placeholder'}"
        )
    except Exception as exc2:
        state.engine_ready = False
        state.engine_info  = f"ERROR: {exc2}"


def _measure_latency() -> None:
    """Run N inference calls and update the rolling latency window."""
    if not state.engine_ready or _engine is None:
        return

    for prompt in BENCH_PROMPTS:
        try:
            t0    = time.perf_counter()
            _compute(_engine, prompt)
            elapsed = (time.perf_counter() - t0) * 1000
            state.latency_history.append(elapsed)
        except Exception:
            pass

    if state.engine_ready and _engine is not None and _is_cascade:
        s, c, m = _engine.tier_counts()
        state.tier_sentinel = int(s)
        state.tier_scholar = int(c)
        state.tier_monarch = int(m)

    if len(state.latency_history) >= 3:
        lat = sorted(state.latency_history)
        n   = len(lat)
        state.p50_ms    = statistics.median(lat)
        state.p95_ms    = lat[int(n * 0.95) - 1]
        state.p99_ms    = lat[int(n * 0.99) - 1]
        state.throughput = 1000 / state.p50_ms if state.p50_ms > 0 else 0


def _read_finops() -> None:
    """Read FinOps Parquet logs and update cost / routing metrics."""
    try:
        import polars as pl
        files = list(FINOPS_LOG_DIR.glob("requests_*.parquet"))
        if not files:
            return

        df = (
            pl.scan_parquet(str(FINOPS_LOG_DIR / "requests_*.parquet"))
            .select([
                pl.col("routed_to"),
                pl.col("cost_saved_usd"),
                pl.len().alias("n"),
            ])
            .group_by("routed_to")
            .agg([
                pl.count("cost_saved_usd").alias("count"),
                pl.sum("cost_saved_usd").alias("saved"),
            ])
            .collect(engine="streaming")
        )

        total = cloud = local = saved = 0
        for row in df.iter_rows(named=True):
            count = row["count"]
            total += count
            if row["routed_to"] == "local_edge":
                local += count
                saved += row["saved"]
            else:
                cloud += count

        state.total_requests  = total
        state.local_requests  = local
        state.cloud_requests  = cloud
        state.total_saved_usd = saved
        state.local_rate_pct  = (local / total * 100) if total > 0 else 0.0
    except Exception:
        pass  # FinOps logs not yet available — show zeros


# ── Rich layout builder ───────────────────────────────────────────────────────

def _status_color(ready: bool) -> str:
    return "bright_green" if ready else "bright_red"


def _latency_color(p99: float) -> str:
    if p99 < 6:   return "bright_green"
    if p99 < 10:  return "yellow"
    return "bright_red"


def _tier_bar(count: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "░" * width
    filled = int(round(width * count / total))
    filled = min(width, max(0, filled))
    return "█" * filled + "░" * (width - filled)


def _build_engine_panel() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1))
    t.add_column("k", style="dim", width=16)
    t.add_column("v")

    status_text = "✅  READY" if state.engine_ready else "❌  NOT READY"
    t.add_row("Status",   Text(status_text, style=_status_color(state.engine_ready)))
    t.add_row("Model",    state.model_path.split("/")[-1])
    t.add_row("Size",     f"{state.model_size_mb:.1f} MB" if state.model_size_mb else "—")
    t.add_row("Pool",     f"{state.pool_size} sessions")
    t.add_row("Tokenizer","Real (WordPiece)" if state.has_tokenizer else "Placeholder")
    t.add_row(
        "Cascade",
        "Quality ONNX armed" if state.cascade_quality_loaded else "Fast path only",
    )
    t.add_row("Uptime",   f"{state.uptime_s:.0f} s")

    return Panel(t, title="[bold cyan]⚡ RUST ENGINE[/bold cyan]",
                 border_style="cyan", box=box.ROUNDED)


def _build_latency_panel() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1))
    t.add_column("k", style="dim", width=16)
    t.add_column("v")

    col = _latency_color(state.p99_ms)
    sla = "✅  PASS" if state.p99_ms < 10 else ("⚠️  WARN" if state.p99_ms < 14 else "❌  FAIL")

    t.add_row("P50",       Text(f"{state.p50_ms:.2f} ms", style="bright_green"))
    t.add_row("P95",       Text(f"{state.p95_ms:.2f} ms", style="yellow"))
    t.add_row("P99",       Text(f"{state.p99_ms:.2f} ms  {sla}", style=col))
    t.add_row("Throughput",f"{state.throughput:,.0f} req/s")
    t.add_row("SLA target","< 10 ms (rolling P99; sentinel path)")
    t.add_row("Samples",   f"{len(state.latency_history)}/{LATENCY_WINDOW}")

    return Panel(t, title="[bold magenta]📊 P99 LATENCY[/bold magenta]",
                 border_style="magenta", box=box.ROUNDED)


def _build_tier_panel() -> Panel:
    """模型分級分佈：哨兵 (fast-only) / 學者 (quality, confident) / 君主 (quality, still ambiguous)."""
    t = Table(box=None, show_header=False, padding=(0, 1))
    t.add_column("tier", style="dim", width=10)
    t.add_column("label", width=14)
    t.add_column("n", justify="right", width=8)
    t.add_column("bar", width=30)

    tot = state.tier_sentinel + state.tier_scholar + state.tier_monarch
    if tot <= 0:
        tot = 1

    t.add_row(
        "哨兵",
        "Sentinel",
        str(state.tier_sentinel),
        Text(_tier_bar(state.tier_sentinel, tot), style="cyan"),
    )
    t.add_row(
        "學者",
        "Scholar",
        str(state.tier_scholar),
        Text(_tier_bar(state.tier_scholar, tot), style="magenta"),
    )
    t.add_row(
        "君主",
        "Monarch",
        str(state.tier_monarch),
        Text(_tier_bar(state.tier_monarch, tot), style="bright_red"),
    )

    foot = Text(
        "Tier counts from live Rust CascadingEngine inference (zero-copy FFI).",
        style="dim",
    )
    inner = Group(t, Text(""), foot)

    return Panel(
        inner,
        title="[bold yellow]📶 模型分級分佈[/bold yellow]",
        border_style="yellow",
        box=box.ROUNDED,
    )


def _build_finops_panel() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1))
    t.add_column("k", style="dim", width=16)
    t.add_column("v")

    # GPT-4 equivalent: $30/1M tokens → per token ≈ $0.00003
    # We track cost_saved_usd per request in the Parquet logs
    # Also compute running estimate from current inferences
    gpt4_equiv = state.total_saved_usd  # logged savings
    rate_str   = f"{state.local_rate_pct:.1f}%"
    rate_col   = "bright_green" if state.local_rate_pct >= 60 else "yellow"

    t.add_row("Total saved",  Text(f"${gpt4_equiv:.4f} USD", style="bright_green bold"))
    t.add_row("GPT-4 basis",  f"${GPT4_USD_PER_1M}/1M tokens")
    t.add_row("Local requests",f"{state.local_requests:,}")
    t.add_row("Cloud requests",f"{state.cloud_requests:,}")
    t.add_row("Local rate",   Text(rate_str, style=rate_col))
    t.add_row("Total requests",f"{state.total_requests:,}")

    return Panel(t, title="[bold green]💰 FINOPS[/bold green]",
                 border_style="green", box=box.ROUNDED)


def _build_dashboard() -> Group:
    """Top row: engine / latency / FinOps; bottom: tier distribution."""
    row1 = Table(box=None, show_header=False, show_edge=False, padding=(0, 1))
    row1.add_column("", ratio=1)
    row1.add_column("", ratio=1)
    row1.add_column("", ratio=1)
    row1.add_row(
        _build_engine_panel(),
        _build_latency_panel(),
        _build_finops_panel(),
    )
    return Group(row1, Text(""), _build_tier_panel())


def _header() -> Panel:
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    return Panel(
        Text(
            f"🚀  Aegis V2 — Hardware-Aware Edge-Cloud Gateway  "
            f"[RUST_ENGINE_STATUS: {'READY' if state.engine_ready else 'OFFLINE'}]"
            f"   {t}",
            justify="center",
            style="bold white",
        ),
        border_style="white",
        box=box.HEAVY,
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Aegis V2 real-time dashboard")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Fast-path ONNX (INT8 MiniLM)")
    parser.add_argument(
        "--quality-model",
        default=DEFAULT_QUALITY,
        help="Quality-path ONNX (e.g. L12); file must exist or cascade uses fast only",
    )
    parser.add_argument("--tokenizer", default=DEFAULT_TOK, help="tokenizer.json path")
    args = parser.parse_args()

    console = Console()
    console.print("[cyan]Initialising Aegis V2 Dashboard...[/cyan]")

    _init_engine(args.model, args.tokenizer, args.quality_model)
    _measure_latency()
    _read_finops()

    console.print(
        f"[{'bright_green' if state.engine_ready else 'bright_red'}]"
        f"Engine: {state.engine_info}[/]"
    )

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )

    try:
        with Live(layout, console=console, refresh_per_second=2, screen=True) as live:
            last_bench = time.monotonic()
            while True:
                now = time.monotonic()
                state.uptime_s = now - state._start

                # Periodic latency measurement
                if now - last_bench >= BENCH_INTERVAL:
                    _measure_latency()
                    _read_finops()
                    last_bench = now

                layout["header"].update(_header())
                layout["body"].update(_build_dashboard())

                time.sleep(REFRESH_INTERVAL)

    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
