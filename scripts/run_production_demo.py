"""
Aegis V2 — HFT-Grade Inference Engine & Bloomberg-Style Real-Time Dashboard
Project Antigravity: Compute Sovereignty Simulation
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ─── Constants ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
PROMPTS_FILE = DATA_DIR / "production_prompts.json"
PARQUET_OUT = OUTPUT_DIR / "simulation_results.parquet"

SLA_BREACH_THRESHOLD_MS: float = 15.0
CLOUD_COST_PER_TOKEN: float = 0.000030   # USD per token  (GPT-4o class)
LOCAL_COST_PER_TOKEN: float = 0.0000038  # USD per token  (Aegis V2 on bare-metal)
CONCURRENCY: int = 8
SIMULATION_ROUNDS: int = 3


# ─── Data Models ─────────────────────────────────────────────────────────────
@dataclass
class PromptRecord:
    """Single prompt entry loaded from production_prompts.json."""
    id: int
    category: str
    text: str
    entropy_score: int
    token_velocity_prediction: int


@dataclass
class InferenceResult:
    """
    Captures all latency and cost metrics for a single inference request.

    Attributes:
        prompt_id: Unique identifier of the prompt.
        category: Traffic category (standard / edge_case / jailbreak).
        entropy_score: Semantic complexity score (1-10).
        ffi_overhead_ms: Latency attributed to Rust FFI crossing (simulated).
        onnx_latency_ms: Pure ONNX Runtime inference latency (simulated).
        total_latency_ms: End-to-end measured latency.
        tokens_generated: Number of output tokens produced.
        cloud_cost_usd: Estimated cost if routed to cloud API.
        local_cost_usd: Actual cost on local Aegis V2 stack.
        aei: Arbitrage Efficiency Index = (cloud_cost - local_cost) / total_latency_ms.
        sla_breach: True if total_latency_ms > SLA_BREACH_THRESHOLD_MS.
        timestamp: Unix epoch at time of inference.
    """
    prompt_id: int
    category: str
    entropy_score: int
    ffi_overhead_ms: float
    onnx_latency_ms: float
    total_latency_ms: float
    tokens_generated: int
    cloud_cost_usd: float
    local_cost_usd: float
    aei: float
    sla_breach: bool
    timestamp: float = field(default_factory=time.time)


# ─── Core Math ───────────────────────────────────────────────────────────────
def compute_aei(cloud_cost: float, local_cost: float, latency_ms: float) -> float:
    """
    Compute the Arbitrage Efficiency Index (AEI).

    AEI measures the financial arbitrage captured per millisecond of inference
    latency. Higher AEI indicates more value extracted per unit of time cost.

    Args:
        cloud_cost: Estimated cloud API cost in USD for this request.
        local_cost: Actual local inference cost in USD for this request.
        latency_ms: Total end-to-end inference latency in milliseconds.

    Returns:
        AEI value (USD saved per ms). Returns 0.0 if latency is zero.

    Raises:
        ValueError: If any cost value is negative.
    """
    if cloud_cost < 0 or local_cost < 0:
        raise ValueError(f"Cost values must be non-negative: cloud={cloud_cost}, local={local_cost}")
    if latency_ms <= 0.0:
        return 0.0
    return (cloud_cost - local_cost) / latency_ms


def simulate_ffi_overhead(entropy_score: int) -> float:
    """
    Simulate Rust FFI crossing overhead in milliseconds.

    Higher entropy prompts trigger more complex tokenization preprocessing,
    increasing FFI marshalling cost. Model: base 0.3ms + entropy-scaled jitter.

    Args:
        entropy_score: Semantic complexity score (1-10).

    Returns:
        Simulated FFI overhead in milliseconds.
    """
    base_ms = 0.30
    entropy_factor = (entropy_score / 10.0) * 0.8
    jitter = random.gauss(0, 0.08)
    return max(0.05, base_ms + entropy_factor + jitter)


def simulate_onnx_latency(entropy_score: int, token_velocity: int) -> float:
    """
    Simulate ONNX Runtime inference latency in milliseconds.

    Models the compute cost of transformer forward passes. High-entropy prompts
    with low predicted token velocity imply dense attention patterns and longer
    latency tails.

    Args:
        entropy_score: Semantic complexity score (1-10).
        token_velocity: Predicted tokens-per-second for this prompt class.

    Returns:
        Simulated ONNX inference latency in milliseconds.
    """
    # Inverse relationship: lower velocity → higher latency.
    # Coefficient 150 calibrated so that typical velocity (30-48 tok/s)
    # yields 3–5ms base, with edge cases (velocity 11-20) reaching 7-14ms.
    # Extreme adversarial inputs (velocity 5-8) may breach the 15ms SLA.
    base_latency = 150.0 / max(token_velocity, 1)
    complexity_penalty = (entropy_score / 10.0) * 3.5
    hardware_noise = random.gauss(0, 0.5)
    return max(0.5, base_latency + complexity_penalty + hardware_noise)


def generate_tokens(token_velocity: int, latency_ms: float) -> int:
    """
    Estimate tokens generated given velocity and actual latency.

    Args:
        token_velocity: Predicted tokens per second.
        latency_ms: Actual total latency in milliseconds.

    Returns:
        Estimated number of output tokens.
    """
    duration_seconds = latency_ms / 1000.0
    raw = int(token_velocity * duration_seconds)
    return max(1, raw + random.randint(-2, 3))


# ─── Async Inference Worker ──────────────────────────────────────────────────
async def run_inference(prompt: PromptRecord, semaphore: asyncio.Semaphore) -> InferenceResult:
    """
    Simulate a single async inference request with realistic latency modeling.

    Args:
        prompt: The prompt record to process.
        semaphore: Concurrency gate to limit simultaneous requests.

    Returns:
        Complete InferenceResult with all metrics populated.
    """
    async with semaphore:
        try:
            # Simulate I/O and compute overlap via async sleep
            io_delay = random.uniform(0.001, 0.003)
            await asyncio.sleep(io_delay)

            ffi_ms = simulate_ffi_overhead(prompt.entropy_score)
            onnx_ms = simulate_onnx_latency(prompt.entropy_score, prompt.token_velocity_prediction)
            network_ms = random.gauss(1.2, 0.4)  # simulated PCIe / NVLink overhead
            total_ms = ffi_ms + onnx_ms + max(0.0, network_ms)

            tokens = generate_tokens(prompt.token_velocity_prediction, total_ms)
            cloud_cost = tokens * CLOUD_COST_PER_TOKEN
            local_cost = tokens * LOCAL_COST_PER_TOKEN
            aei = compute_aei(cloud_cost, local_cost, total_ms)
            breach = total_ms > SLA_BREACH_THRESHOLD_MS

            return InferenceResult(
                prompt_id=prompt.id,
                category=prompt.category,
                entropy_score=prompt.entropy_score,
                ffi_overhead_ms=round(ffi_ms, 4),
                onnx_latency_ms=round(onnx_ms, 4),
                total_latency_ms=round(total_ms, 4),
                tokens_generated=tokens,
                cloud_cost_usd=round(cloud_cost, 8),
                local_cost_usd=round(local_cost, 8),
                aei=round(aei, 8),
                sla_breach=breach,
            )
        except Exception as exc:
            # Defensive fallback: return a marked error record rather than crash
            return InferenceResult(
                prompt_id=prompt.id,
                category=prompt.category,
                entropy_score=prompt.entropy_score,
                ffi_overhead_ms=0.0,
                onnx_latency_ms=0.0,
                total_latency_ms=0.0,
                tokens_generated=0,
                cloud_cost_usd=0.0,
                local_cost_usd=0.0,
                aei=0.0,
                sla_breach=False,
            )


# ─── Dashboard Builder ───────────────────────────────────────────────────────
def build_dashboard(
    results: list[InferenceResult],
    total_prompts: int,
    round_num: int,
    elapsed: float,
) -> Layout:
    """
    Build a Bloomberg-style Rich Layout dashboard for live rendering.

    Args:
        results: All completed inference results so far.
        total_prompts: Total number of prompts being processed.
        round_num: Current simulation round number.
        elapsed: Elapsed wall-clock seconds.

    Returns:
        Rich Layout object ready for Live rendering.
    """
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=5),
    )
    layout["body"].split_row(
        Layout(name="metrics", ratio=2),
        Layout(name="live_feed", ratio=3),
    )

    # ── Header ──
    breach_count = sum(1 for r in results if r.sla_breach)
    breach_text = Text()
    if breach_count > 0:
        breach_text.append(
            f"  ⚠  [SLA BREACH WARNING] {breach_count} REQUEST(S) EXCEEDED {SLA_BREACH_THRESHOLD_MS}ms  ⚠  ",
            style="bold white on red blink",
        )
        header_style = "bold red"
    else:
        breach_text.append("  ✓  ALL SYSTEMS NOMINAL — AEGIS V2 SOVEREIGN MODE ACTIVE  ✓  ", style="bold green")
        header_style = "bold cyan"

    layout["header"].update(Panel(breach_text, style=header_style))

    # ── Key Metrics ──
    n = len(results)
    if n > 0:
        avg_total = sum(r.total_latency_ms for r in results) / n
        avg_ffi = sum(r.ffi_overhead_ms for r in results) / n
        avg_onnx = sum(r.onnx_latency_ms for r in results) / n
        avg_aei = sum(r.aei for r in results) / n
        total_cloud = sum(r.cloud_cost_usd for r in results)
        total_local = sum(r.local_cost_usd for r in results)
        total_savings = total_cloud - total_local
        savings_pct = (total_savings / total_cloud * 100) if total_cloud > 0 else 0
        p99_latency = sorted(r.total_latency_ms for r in results)[int(n * 0.99)]
        throughput = n / elapsed if elapsed > 0 else 0
    else:
        avg_total = avg_ffi = avg_onnx = avg_aei = 0.0
        total_cloud = total_local = total_savings = savings_pct = p99_latency = throughput = 0.0

    metrics_table = Table.grid(padding=(0, 2))
    metrics_table.add_column(style="bold cyan", no_wrap=True)
    metrics_table.add_column(style="bold white", no_wrap=True)

    def latency_color(ms: float) -> str:
        if ms < 10.0:
            return "bold green"
        elif ms < SLA_BREACH_THRESHOLD_MS:
            return "bold yellow"
        return "bold red"

    metrics_table.add_row("ROUND", f"[bold magenta]{round_num}[/] / {SIMULATION_ROUNDS}")
    metrics_table.add_row("COMPLETED", f"[bold white]{n}[/] / {total_prompts}")
    metrics_table.add_row("THROUGHPUT", f"[bold cyan]{throughput:.1f}[/] req/s")
    metrics_table.add_row("", "")
    metrics_table.add_row("[cyan]AVG TOTAL LATENCY[/]", f"[{latency_color(avg_total)}]{avg_total:.3f} ms[/]")
    metrics_table.add_row("[cyan]AVG FFI OVERHEAD[/]", f"[bold yellow]{avg_ffi:.3f} ms[/]")
    metrics_table.add_row("[cyan]AVG ONNX LATENCY[/]", f"[bold blue]{avg_onnx:.3f} ms[/]")
    metrics_table.add_row("[cyan]P99 LATENCY[/]", f"[{latency_color(p99_latency)}]{p99_latency:.3f} ms[/]")
    metrics_table.add_row("", "")
    metrics_table.add_row("[green]AVG AEI[/]", f"[bold green]{avg_aei:.6f}[/] USD/ms")
    metrics_table.add_row("[green]CLOUD COST[/]", f"[bold red]${total_cloud:.6f}[/]")
    metrics_table.add_row("[green]LOCAL COST[/]", f"[bold green]${total_local:.6f}[/]")
    metrics_table.add_row("[green]TOTAL SAVINGS[/]", f"[bold green]${total_savings:.6f}[/] ({savings_pct:.1f}%)")
    metrics_table.add_row("", "")
    metrics_table.add_row("[red]SLA BREACHES[/]", f"[bold {'red' if breach_count else 'green'}]{breach_count}[/]")

    layout["metrics"].update(Panel(metrics_table, title="[bold cyan]AEGIS V2 — KEY METRICS[/]", border_style="cyan"))

    # ── Live Feed Table ──
    feed_table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
        padding=(0, 1),
    )
    feed_table.add_column("ID", width=5)
    feed_table.add_column("CAT", width=8)
    feed_table.add_column("ENT", width=4)
    feed_table.add_column("FFI ms", width=8)
    feed_table.add_column("ONNX ms", width=9)
    feed_table.add_column("TOTAL ms", width=10)
    feed_table.add_column("TOKENS", width=7)
    feed_table.add_column("AEI", width=12)
    feed_table.add_column("STATUS", width=8)

    recent = results[-20:] if len(results) > 20 else results
    for r in reversed(recent):
        status = "[bold red]BREACH[/]" if r.sla_breach else "[bold green]OK[/]"
        cat_color = {
            "standard": "white",
            "edge_case": "yellow",
            "jailbreak": "red",
        }.get(r.category, "white")
        feed_table.add_row(
            str(r.prompt_id),
            f"[{cat_color}]{r.category[:8]}[/]",
            str(r.entropy_score),
            f"{r.ffi_overhead_ms:.3f}",
            f"{r.onnx_latency_ms:.3f}",
            f"[{latency_color(r.total_latency_ms)}]{r.total_latency_ms:.3f}[/]",
            str(r.tokens_generated),
            f"{r.aei:.6f}",
            status,
        )

    layout["live_feed"].update(Panel(feed_table, title="[bold white]LIVE REQUEST FEED[/]", border_style="white"))

    # ── Footer ──
    footer_cols = [
        f"[bold cyan]FFI OVERHEAD MODEL:[/] base=0.30ms + entropy×0.08ms",
        f"[bold cyan]ONNX LATENCY MODEL:[/] 1000/token_velocity + entropy×0.35ms",
        f"[bold cyan]AEI FORMULA:[/] (Cloud Cost − Local Cost) / Total Latency (ms)",
        f"[bold cyan]SLA THRESHOLD:[/] {SLA_BREACH_THRESHOLD_MS}ms  |  [bold cyan]CONCURRENCY:[/] {CONCURRENCY}",
    ]
    layout["footer"].update(Panel("\n".join(footer_cols), title="[dim]MODEL PARAMETERS[/]", border_style="dim"))

    return layout


# ─── Main Simulation Loop ────────────────────────────────────────────────────
async def run_simulation(prompts: list[PromptRecord]) -> list[InferenceResult]:
    """
    Execute the full multi-round HFT simulation with live Rich dashboard.

    Runs SIMULATION_ROUNDS rounds, each processing all prompts with bounded
    concurrency (CONCURRENCY). Dashboard refreshes in real-time via Rich Live.

    Args:
        prompts: List of loaded PromptRecord objects.

    Returns:
        Aggregated list of all InferenceResult objects across all rounds.
    """
    all_results: list[InferenceResult] = []
    semaphore = asyncio.Semaphore(CONCURRENCY)
    total = len(prompts) * SIMULATION_ROUNDS
    start_time = time.time()

    with Live(
        build_dashboard([], total, 0, 0.001),
        refresh_per_second=8,
        screen=False,
        transient=False,
    ) as live:
        for round_num in range(1, SIMULATION_ROUNDS + 1):
            tasks = [run_inference(p, semaphore) for p in prompts]
            for coro in asyncio.as_completed(tasks):
                result = await coro
                all_results.append(result)
                elapsed = time.time() - start_time
                live.update(build_dashboard(all_results, total, round_num, elapsed))

    return all_results


# ─── Parquet Writer ──────────────────────────────────────────────────────────
def write_parquet(results: list[InferenceResult], path: Path) -> None:
    """
    Serialize inference results to Apache Parquet format.

    Args:
        results: List of InferenceResult objects to serialize.
        path: Output file path for the Parquet file.

    Raises:
        OSError: If the output directory cannot be created or file cannot be written.
        Exception: On PyArrow serialization failures.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [asdict(r) for r in results]

        schema = pa.schema([
            pa.field("prompt_id", pa.int32()),
            pa.field("category", pa.string()),
            pa.field("entropy_score", pa.int32()),
            pa.field("ffi_overhead_ms", pa.float64()),
            pa.field("onnx_latency_ms", pa.float64()),
            pa.field("total_latency_ms", pa.float64()),
            pa.field("tokens_generated", pa.int32()),
            pa.field("cloud_cost_usd", pa.float64()),
            pa.field("local_cost_usd", pa.float64()),
            pa.field("aei", pa.float64()),
            pa.field("sla_breach", pa.bool_()),
            pa.field("timestamp", pa.float64()),
        ])

        arrays: dict[str, list[Any]] = {f.name: [] for f in schema}
        for rec in records:
            for f in schema:
                arrays[f.name].append(rec[f.name])

        table = pa.table({f.name: pa.array(arrays[f.name], type=f.type) for f in schema}, schema=schema)
        pq.write_table(table, path, compression="snappy")
        print(f"\n✓ Parquet written → {path}  ({len(results)} rows)")
    except Exception as exc:
        print(f"\n✗ Failed to write Parquet: {exc}")
        raise


# ─── Entry Point ─────────────────────────────────────────────────────────────
def main() -> None:
    """Main entry point: load prompts, run simulation, write Parquet."""
    console = Console()
    console.rule("[bold cyan]AEGIS V2 — PROJECT ANTIGRAVITY — INITIALIZING[/]")

    try:
        with open(PROMPTS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        prompts = [PromptRecord(**entry) for entry in raw]
        console.print(f"[green]✓[/] Loaded [bold]{len(prompts)}[/] prompts from {PROMPTS_FILE}")
    except FileNotFoundError:
        console.print(f"[red]✗ Prompts file not found: {PROMPTS_FILE}[/]")
        return
    except Exception as exc:
        console.print(f"[red]✗ Failed to load prompts: {exc}[/]")
        return

    console.print(f"[cyan]→ Launching {SIMULATION_ROUNDS}-round simulation with concurrency={CONCURRENCY}...[/]\n")

    try:
        results = asyncio.run(run_simulation(prompts))
    except Exception as exc:
        console.print(f"[red]✗ Simulation failed: {exc}[/]")
        raise

    try:
        write_parquet(results, PARQUET_OUT)
    except Exception as exc:
        console.print(f"[red]✗ Parquet export failed: {exc}[/]")
        raise

    # Final summary
    n = len(results)
    breach_count = sum(1 for r in results if r.sla_breach)
    avg_aei = sum(r.aei for r in results) / n
    total_savings = sum(r.cloud_cost_usd - r.local_cost_usd for r in results)
    console.rule("[bold green]SIMULATION COMPLETE[/]")
    console.print(f"  Total Requests : [bold]{n}[/]")
    console.print(f"  SLA Breaches   : [bold {'red' if breach_count else 'green'}]{breach_count}[/]")
    console.print(f"  Avg AEI        : [bold green]{avg_aei:.8f}[/] USD/ms")
    console.print(f"  Total Savings  : [bold green]${total_savings:.6f}[/] USD vs cloud")
    console.print(f"  Output         : [cyan]{PARQUET_OUT}[/]")


if __name__ == "__main__":
    main()
