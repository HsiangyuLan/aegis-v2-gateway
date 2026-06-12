"""
Agent Execute API — Aegis V2 即時威脅分析觸發端點

POST /api/agent/execute
接收 { "action_type": "THREAT_ANALYSIS" }

執行流程
--------
1. 隨機選擇兩種硬核攻擊場景之一（SQL Injection / Credential Leak）。
2. asyncio.sleep(0.8–1.5s) — 模擬大腦推理耗時（可在 Telemetry 面板看到 CPU 峰值）。
3. 呼叫 SecOpsReasoningAgent.analyze_threat 執行真實 LLM 推理。
4. SecOpsAgent 內部已透過 asyncio.ensure_future 非阻塞寫入 finops_ledger.db。
5. 回傳完整推理結果（action / confidence / reasoning_steps / tokens / elapsed_ms）。

設計原則
--------
- 全程 async，不阻塞 uvloop 事件迴圈。
- Fail-Closed：任何例外均回傳預設 BLOCK，絕不讓 Gateway 崩潰。
- 完整 try-except 包覆，失敗時以 exc_info=True 記錄完整堆疊追蹤。
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["Agent"])

# ── 兩種硬核攻擊情境（random.choice 隨機挑選）─────────────────────────────────

_ATTACK_SCENARIOS: list[dict[str, Any]] = [
    {
        "suspicious_ip": "10.0.0.99",
        "event_type":    "sql_injection",
        "request_count": 47,
        "raw_log":       "admin' -- DROP TABLE entries;--",
    },
    {
        "suspicious_ip": "192.168.1.105",
        "event_type":    "credential_leak",
        "request_count": 3,
        "raw_log":       "Foundry API Key leaked on GitHub public gist: sk-foundry-...",
    },
]


# ── Request / Response Models ──────────────────────────────────────────────────

class AgentExecuteRequest(BaseModel):
    """觸發 Agent 執行請求體。"""

    action_type: str = Field(
        default="THREAT_ANALYSIS",
        description="執行類型，目前僅支援 THREAT_ANALYSIS",
    )


class AgentExecuteResponse(BaseModel):
    """
    Agent 執行回應體，包含完整推理結果與觸發場景資訊。

    Attributes
    ----------
    action_type:
        本次觸發類型（如 "THREAT_ANALYSIS"）。
    scenario:
        隨機選中的攻擊場景（suspicious_ip / event_type / raw_log）。
    action:
        SecOps Agent 防禦決策（BLOCK / ALLOW / RATE_LIMIT）。
    confidence:
        LLM 信心分數（0.0–1.0）。
    reasoning_steps:
        LLM 推理步驟清單。
    simulated_tokens:
        本次推理消耗 token 數（供 FinOps 成本計算）。
    elapsed_ms:
        總執行耗時（含 sleep 模擬 + LLM 推理），單位 ms。
    status:
        執行狀態（"ok" / "error_fail_closed"）。
    """

    action_type:      str
    scenario:         dict[str, Any]
    action:           str
    confidence:       float
    reasoning_steps:  list[str]
    simulated_tokens: int
    elapsed_ms:       float
    status:           str


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post(
    "/execute",
    response_model=AgentExecuteResponse,
    summary="觸發 SecOps Agent 即時威脅分析 — 隨機硬核攻擊場景",
)
async def agent_execute(
    body: AgentExecuteRequest,
    request: Request,
) -> AgentExecuteResponse:
    """
    隨機挑選一種硬核攻擊場景，呼叫 SecOpsReasoningAgent 執行真實 LLM 推理，
    並非同步寫入 finops_ledger.db（由 SecOpsAgent 內部 ensure_future 處理）。

    Parameters
    ----------
    body.action_type:
        觸發類型，預設 "THREAT_ANALYSIS"。

    Returns
    -------
    AgentExecuteResponse
        包含防禦決策、信心分數、推理步驟、Token 消耗與執行耗時。

    Notes
    -----
    - 分析前加入 0.8–1.5 秒隨機延遲，模擬大腦推理耗時，
      可同步在 Telemetry 面板觀察到 CPU 使用率短暫峰值。
    - SecOpsAgent 內部已透過 asyncio.ensure_future 非阻塞寫入 SQLite Ledger；
      此端點不需額外重複寫入。
    - Fail-Closed：任何例外（LLM 超時、連線失敗）均回傳預設 BLOCK，
      絕不讓 API Gateway 崩潰。
    """
    scenario: dict[str, Any] = random.choice(_ATTACK_SCENARIOS)

    logger.info(
        "[AGENT EXECUTE] 觸發威脅分析 | action_type=%s | ip=%s | event=%s",
        body.action_type,
        scenario["suspicious_ip"],
        scenario["event_type"],
    )

    # ── 大腦推理耗時模擬（造成 CPU 峰值可在 Telemetry 面板觀察）──────────────
    delay: float = random.uniform(0.8, 1.5)
    await asyncio.sleep(delay)

    try:
        result: dict[str, Any] = await request.app.state.secops_agent.analyze_threat(
            scenario
        )

        logger.info(
            "[AGENT EXECUTE] 推理完成 | action=%s | confidence=%.2f | tokens=%d | elapsed_ms=%.1f",
            result.get("action", "BLOCK"),
            float(result.get("confidence", 0.0)),
            int(result.get("simulated_tokens", 0)),
            float(result.get("elapsed_ms", 0.0)),
        )

        return AgentExecuteResponse(
            action_type=body.action_type,
            scenario=scenario,
            action=str(result.get("action", "BLOCK")),
            confidence=float(result.get("confidence", 1.0)),
            reasoning_steps=list(result.get("reasoning_steps", [])),
            simulated_tokens=int(result.get("simulated_tokens", 0)),
            elapsed_ms=float(result.get("elapsed_ms", 0.0)),
            status=str(result.get("status", "ok")),
        )

    except Exception as exc:
        logger.error(
            "[AGENT EXECUTE] 執行失敗，觸發 Fail-Closed [%s]: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return AgentExecuteResponse(
            action_type=body.action_type,
            scenario=scenario,
            action="BLOCK",
            confidence=1.0,
            reasoning_steps=["API 呼叫失敗，觸發 Fail-Closed 安全機制，預設阻擋"],
            simulated_tokens=0,
            elapsed_ms=0.0,
            status="error_fail_closed",
        )
