"""
FinOps Ledger API — Aegis V2 推理交易總帳查詢端點

端點：GET /api/ledger/history

設計原則
--------
- 資料來源：finops_ledger.db（SQLite）中的 ledger_logs 資料表。
- 全程透過 aiosqlite 非同步讀取，不阻塞 uvloop 事件迴圈。
- 支援 LIMIT / OFFSET 分頁，並依 timestamp DESC 排序。
- Pydantic BaseModel 嚴格約束每筆紀錄格式。
- 禁止回傳死資料：每次請求均執行真實 SELECT 查詢。
- Fail-Closed：任何 DB 異常均回傳空列表，附帶 logger 告警，
  絕不向前端傳播 HTTP 500。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.db.ledger_db import count_ledger_entries, fetch_ledger_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ledger", tags=["Ledger"])


# ── Response Models ──────────────────────────────────────────────────────────────

class LedgerEntry(BaseModel):
    """
    單筆推理交易紀錄。

    Attributes
    ----------
    id:
        資料庫自動遞增主鍵。
    timestamp:
        ISO 8601 UTC 時間戳。
    service:
        發起推理的服務名稱（如 "secops_agent"）。
    tokens:
        本次推理消耗的 token 數。
    cost_usd:
        換算後的 USD 成本（tokens / 1000 × $0.000267），精確到小數第六位。
    action:
        防禦決策（BLOCK / ALLOW / RATE_LIMIT）。
    status:
        執行狀態（"ok" / "error_fail_closed" 等）。
    """

    id: int = Field(..., ge=1, description="資料庫主鍵 ID")
    timestamp: str = Field(..., description="ISO 8601 UTC 時間戳")
    service: str = Field(..., description="服務識別名稱")
    tokens: int = Field(..., ge=0, description="消耗 tokens 數")
    cost_usd: float = Field(..., ge=0.0, description="換算 USD 成本")
    action: str = Field(..., description="防禦決策（BLOCK/ALLOW/RATE_LIMIT）")
    status: str = Field(..., description="執行狀態")


class LedgerHistoryResponse(BaseModel):
    """
    分頁查詢結果回應模型。

    Attributes
    ----------
    total_count:
        資料表總筆數（不受 limit/offset 影響），供前端計算總頁數。
    limit:
        本次查詢的每頁筆數上限。
    offset:
        本次查詢的起始偏移量。
    entries:
        本頁的推理交易紀錄列表，依時間遞減排序。
    """

    total_count: int = Field(..., ge=0, description="資料表總筆數")
    limit: int = Field(..., ge=1, description="每頁筆數")
    offset: int = Field(..., ge=0, description="分頁偏移量")
    entries: list[LedgerEntry] = Field(..., description="本頁推理交易紀錄")


# ── API Endpoint ────────────────────────────────────────────────────────────────

@router.get(
    "/history",
    response_model=LedgerHistoryResponse,
    summary="FinOps 總帳歷史 — 真實 SQLite 分頁查詢，禁止死資料",
)
async def ledger_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200, description="每頁筆數（1–200）"),
    offset: int = Query(default=0, ge=0, description="分頁偏移量（0-based）"),
) -> LedgerHistoryResponse:
    """
    分頁查詢 finops_ledger.db 中的推理交易總帳，依時間遞減排序。

    此端點每次均執行真實 ``SELECT * FROM ledger_logs ORDER BY timestamp DESC``
    搭配 LIMIT / OFFSET，絕不回傳任何靜態假資料。

    Parameters
    ----------
    limit:
        每頁最多回傳筆數，範圍 1–200，預設 50。
    offset:
        跳過前 N 筆，預設 0（從最新一筆開始）。

    Returns
    -------
    LedgerHistoryResponse
        包含 ``total_count``（總筆數）、分頁參數與 ``entries`` 紀錄列表。

    ASGI Safety
    -----------
    所有 aiosqlite 呼叫均為原生 async/await，不需要 to_thread() 包裝，
    uvloop 事件迴圈在整個查詢過程中保持非阻塞。
    """
    from app.core.config import get_settings  # 延遲匯入避免循環依賴

    settings = get_settings()
    db_path: str = settings.finops_ledger_db_path

    logger.info(
        "[LEDGER API] GET /history | limit=%d offset=%d | db=%s",
        limit,
        offset,
        db_path,
    )

    rows: list[dict[str, Any]] = await fetch_ledger_history(
        db_path, limit=limit, offset=offset
    )
    total_count: int = await count_ledger_entries(db_path)

    entries = [LedgerEntry(**row) for row in rows]

    logger.info(
        "[LEDGER API] 查詢完成 | total=%d 回傳=%d 筆",
        total_count,
        len(entries),
    )

    return LedgerHistoryResponse(
        total_count=total_count,
        limit=limit,
        offset=offset,
        entries=entries,
    )
