"""
Telemetry Live API — Aegis V2 實時主機系統監控端點

端點：GET /api/telemetry/live

資料來源
--------
- CPU：psutil.cpu_percent(interval=0.1)               — 真實 0.1s 取樣週期
- 記憶體：psutil.virtual_memory()                      — 真實主機 RAM 統計
- 網路 I/O：psutil.net_io_counters()                   — 累計 Bytes 收發

設計原則
--------
- 嚴格使用 Pydantic BaseModel 約束回傳格式，防止欄位漂移。
- psutil 呼叫屬於 CPU-bound 同步阻塞，必須透過 asyncio.to_thread() 執行，
  保持 uvloop 事件迴圈非阻塞。
- 每次呼叫均觸發 logger.info，讓 Uvicorn 終端顯示真實數據跳動。
- 三層 Fail-Closed：任何 psutil 異常均回傳 503，附帶錯誤描述，
  不向前端洩漏內部 Traceback。
"""
from __future__ import annotations

import asyncio
import logging

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry", tags=["Telemetry"])


# ── Response Model ──────────────────────────────────────────────────────────────

class LiveTelemetry(BaseModel):
    """
    實時系統指標回應模型。

    Attributes
    ----------
    cpu_percent:
        真實 CPU 使用率（0.0–100.0），由 psutil 0.1s 取樣週期測量。
    memory_used_mb:
        已使用的主機 RAM（MiB），由 psutil.virtual_memory().used 計算。
    memory_total_mb:
        主機 RAM 總容量（MiB）。
    network_bytes_sent:
        自系統啟動後累計發送的位元組數（Bytes）。
    network_bytes_recv:
        自系統啟動後累計接收的位元組數（Bytes）。
    """

    cpu_percent: float = Field(
        ..., ge=0.0, le=100.0, description="CPU 使用率 (%)"
    )
    memory_used_mb: float = Field(
        ..., ge=0.0, description="已使用記憶體 (MiB)"
    )
    memory_total_mb: float = Field(
        ..., ge=0.0, description="總記憶體容量 (MiB)"
    )
    network_bytes_sent: int = Field(
        ..., ge=0, description="累計發送位元組數"
    )
    network_bytes_recv: int = Field(
        ..., ge=0, description="累計接收位元組數"
    )


# ── 同步採集核心（必須在 Thread Pool 執行）──────────────────────────────────────

def _collect_metrics_sync() -> LiveTelemetry:
    """
    透過 psutil 採集真實主機系統指標。

    本函式為純同步函式，由 asyncio.to_thread() 呼叫，
    嚴禁在 async context 直接執行（cpu_percent interval=0.1 會阻塞 0.1s）。

    Returns
    -------
    LiveTelemetry
        包含 CPU / 記憶體 / 網路 I/O 的真實主機指標。

    Raises
    ------
    RuntimeError
        若 psutil 採集任一指標失敗，則向上拋出供 API 層捕捉。
    """
    cpu_percent: float = psutil.cpu_percent(interval=0.1)

    mem = psutil.virtual_memory()
    _mb = 1024.0 * 1024.0
    memory_used_mb: float = round(mem.used / _mb, 2)
    memory_total_mb: float = round(mem.total / _mb, 2)

    net = psutil.net_io_counters()
    network_bytes_sent: int = net.bytes_sent
    network_bytes_recv: int = net.bytes_recv

    logger.info(
        "[TELEMETRY LIVE] Real Host CPU: %.1f%%, Mem Used: %.1fMB / %.1fMB, "
        "Net Sent: %d B, Net Recv: %d B",
        cpu_percent,
        memory_used_mb,
        memory_total_mb,
        network_bytes_sent,
        network_bytes_recv,
    )

    return LiveTelemetry(
        cpu_percent=cpu_percent,
        memory_used_mb=memory_used_mb,
        memory_total_mb=memory_total_mb,
        network_bytes_sent=network_bytes_sent,
        network_bytes_recv=network_bytes_recv,
    )


# ── API Endpoint ────────────────────────────────────────────────────────────────

@router.get(
    "/live",
    response_model=LiveTelemetry,
    summary="實時主機系統指標 — 真實 psutil 採集，不含任何 Mock",
)
async def telemetry_live() -> LiveTelemetry:
    """
    透過 psutil 採集並回傳真實主機系統指標。

    每次請求均執行真實 psutil 採集（0.1s CPU 取樣），
    保證回傳數據反映呼叫當下的主機狀態，絕不使用靜態假資料。

    Returns
    -------
    LiveTelemetry
        包含以下欄位：

        - ``cpu_percent``        — 真實 CPU 使用率（0.0–100.0）
        - ``memory_used_mb``     — 已使用 RAM（MiB）
        - ``memory_total_mb``    — 總 RAM（MiB）
        - ``network_bytes_sent`` — 累計發送 Bytes
        - ``network_bytes_recv`` — 累計接收 Bytes

    ASGI Safety
    -----------
    psutil 同步阻塞呼叫透過 asyncio.to_thread() 在執行緒池執行，
    uvloop 事件迴圈在 0.1s 取樣期間保持非阻塞。
    """
    try:
        return await asyncio.to_thread(_collect_metrics_sync)
    except Exception as exc:
        logger.error(
            "[TELEMETRY LIVE] psutil 採集失敗 [%s]: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"系統指標採集失敗：{type(exc).__name__}",
        ) from exc
