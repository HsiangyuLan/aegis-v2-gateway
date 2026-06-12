"""
Dashboard Stats API — Aegis V2 SecOps 儀表板黃金指標聚合端點

設計原則
--------
- 資料來源：logs/finops/agent_inference.jsonl（由 SecOpsReasoningAgent 寫入）
- 三大黃金指標計算邏輯：
    * total_blocked        — action == "BLOCK" 的事件總數
    * total_cost_saved_usd — 所有 BLOCK 事件的 simulated_tokens 加總 × $0.000267/1k
    * avg_confidence       — 全部紀錄的 confidence 平均值
- 所有 I/O 均在 asyncio.to_thread() 執行緒池執行，不阻塞 uvloop 事件迴圈。
- 採用三層 Fail-Closed 防禦，嚴禁向前端傳播 HTTP 500。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# ── 費率常數 ────────────────────────────────────────────────────────────────────
_COST_PER_1K_TOKENS: float = 0.000267  # USD / 1k tokens（GPT-4o 輸出估算值）


# ── Response Model ──────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    """
    儀表板三大黃金指標回應模型。

    Attributes
    ----------
    total_blocked:
        ``action == "BLOCK"`` 的事件總計數，代表已成功攔截的威脅次數。
    total_cost_saved_usd:
        所有 BLOCK 事件 ``simulated_tokens`` 加總 × $0.000267/1k，
        代表節省的 USD 推理成本，精確到小數第二位。
    avg_confidence:
        全部紀錄中 ``confidence`` 欄位的平均值（0.0–1.0），
        精確到小數第二位。
    """

    total_blocked: int = Field(
        ..., ge=0, description="已攔截的 BLOCK 事件總數"
    )
    total_cost_saved_usd: float = Field(
        ..., ge=0.0, description="節省的 USD 成本總和（精確到小數第二位）"
    )
    avg_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="防禦決策的平均信心分數（精確到小數第二位）"
    )

    @classmethod
    def zero(cls) -> "DashboardStats":
        """回傳全零降級實例，用於 Fail-Closed 場景（檔案不存在 / 解析失敗）。"""
        return cls(total_blocked=0, total_cost_saved_usd=0.0, avg_confidence=0.0)


# ── 同步計算核心（在 Thread Pool 執行，絕不直接 await）─────────────────────────

def _compute_stats_sync(jsonl_path: Path) -> DashboardStats:
    """
    從 agent_inference.jsonl 讀取並計算三大黃金指標。

    本函式為純同步函式，必須透過 ``asyncio.to_thread()`` 呼叫，
    嚴禁在 async 上下文中直接執行，以避免阻塞 uvloop 事件迴圈。

    Parameters
    ----------
    jsonl_path:
        agent_inference.jsonl 的絕對路徑。

    Returns
    -------
    DashboardStats
        計算成功時回傳三大指標；遭遇任何異常時優雅降級回傳全零實例。

    Edge Cases
    ----------
    - FileNotFoundError:
        系統冷啟動、尚無攻擊事件寫入時觸發，以 INFO 記錄並回傳全零。
    - json.JSONDecodeError:
        JSONL 行格式損毀時跳過該行，以 WARNING 記錄。
    - Exception:
        其他不預期異常的最後防線，以 ERROR 記錄並降級，確保永遠回傳合法 JSON。
    """
    try:
        os.makedirs(jsonl_path.parent, exist_ok=True)

        if not jsonl_path.exists():
            logger.info(
                "agent_inference.jsonl 尚未建立，回傳全零 Fallback | path=%s",
                jsonl_path,
            )
            return DashboardStats.zero()

        records: list[dict[str, Any]] = []
        with jsonl_path.open("r", encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "JSONL 第 %d 行解析失敗，略過 | path=%s | error=%s",
                        lineno,
                        jsonl_path,
                        exc,
                    )

        if not records:
            logger.info("agent_inference.jsonl 為空，回傳全零 Fallback | path=%s", jsonl_path)
            return DashboardStats.zero()

        # ── 計算三大黃金指標 ───────────────────────────────────────────────────
        block_records = [r for r in records if r.get("action") == "BLOCK"]
        total_blocked: int = len(block_records)

        blocked_tokens: float = sum(
            float(r.get("simulated_tokens", 0)) for r in block_records
        )
        total_cost_saved_usd: float = round(
            blocked_tokens / 1000.0 * _COST_PER_1K_TOKENS, 2
        )

        confidence_values = [
            float(r["confidence"])
            for r in records
            if "confidence" in r
        ]
        avg_confidence: float = round(
            sum(confidence_values) / len(confidence_values) if confidence_values else 0.0,
            2,
        )

        logger.debug(
            "Dashboard stats 計算完成 | path=%s | total_blocked=%d | "
            "cost_saved=%.4f | avg_confidence=%.2f",
            jsonl_path,
            total_blocked,
            total_cost_saved_usd,
            avg_confidence,
        )

        return DashboardStats(
            total_blocked=total_blocked,
            total_cost_saved_usd=total_cost_saved_usd,
            avg_confidence=avg_confidence,
        )

    except FileNotFoundError:
        logger.info(
            "agent_inference.jsonl 不存在（冷啟動），回傳全零 Fallback | path=%s",
            jsonl_path,
        )
        return DashboardStats.zero()

    except Exception as exc:
        logger.error(
            "Dashboard stats 計算遭遇未預期異常 [%s] | path=%s | error=%s",
            type(exc).__name__,
            jsonl_path,
            exc,
        )
        return DashboardStats.zero()


# ── API Endpoint ────────────────────────────────────────────────────────────────

@router.get(
    "/stats",
    response_model=DashboardStats,
    summary="Dashboard 黃金指標聚合 — 供前端元件直接 fetch",
)
async def dashboard_stats(request: Request) -> DashboardStats:
    """
    聚合 agent_inference.jsonl 並回傳三大黃金指標（Golden Signals）。

    此端點為前端 Dashboard 元件的唯一資料來源，設計為「永不失敗」：
    面對任何 I/O 或解析異常，均優雅降級回傳全零 JSON，
    確保前端可渲染「暫無資料」佔位符而非顯示錯誤頁。

    Returns
    -------
    DashboardStats
        包含以下三個黃金指標：

        - ``total_blocked``         — 已攔截的 BLOCK 事件數量（整數）
        - ``total_cost_saved_usd``  — 節省的 USD 成本（浮點數，小數第二位）
        - ``avg_confidence``        — 防禦決策平均信心分數（浮點數，小數第二位）

    ASGI Safety
    -----------
    所有 JSONL 磁碟 I/O 工作透過 ``asyncio.to_thread()`` 在執行緒池執行，
    uvloop 事件迴圈在計算期間始終保持非阻塞狀態。
    """
    from app.core.config import get_settings  # 延遲匯入避免循環依賴

    settings = get_settings()
    jsonl_path = Path(settings.finops_log_dir) / "agent_inference.jsonl"

    return await asyncio.to_thread(_compute_stats_sync, jsonl_path)
