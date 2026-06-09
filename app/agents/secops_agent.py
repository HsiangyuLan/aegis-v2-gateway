"""
SecOps Reasoning Agent — Microsoft Agents League Hackathon (Reasoning Agents Track)

提供 ``SecOpsReasoningAgent``：透過模擬 MCP (Model Context Protocol) 呼叫
Microsoft Foundry IQ 執行多步驟推理，針對可疑 Payload 進行資安合規檢查，
並輸出具有商業可追溯性的防禦決策（BLOCK / ALLOW / RATE_LIMIT）。

整合介面
--------
- Foundry IQ endpoint 透過建構子注入（來源：``AEGIS_FOUNDRY_IQ_ENDPOINT``）。
- 全程 async；可在 FastAPI lifespan 中作為 ``app.state.secops_agent`` 掛載。
- 推理步驟上限 ``max_steps=3``，超過強制中斷並預設 BLOCK，防止 Hallucination Loop。
- PII 在進入本模組前已由 ``antigravity_core.execute_command`` 完成遮蔽。
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ── 防禦決策枚舉 ───────────────────────────────────────────────────────────────

class DefenseAction(str, Enum):
    BLOCK      = "BLOCK"
    ALLOW      = "ALLOW"
    RATE_LIMIT = "RATE_LIMIT"


# ── 推理步驟常數 ───────────────────────────────────────────────────────────────

MAX_REASONING_STEPS = 3  # 超過此限制強制中斷，防止 Hallucination Loop

# 每步驟模擬 Token 消耗（當 Foundry IQ 尚未接入時使用）
_SIMULATED_TOKENS_PER_STEP = 120


# ── Agent 主體 ─────────────────────────────────────────────────────────────────

class SecOpsReasoningAgent:
    """
    多步驟推理資安代理。

    狀態機流程（每次 ``analyze_threat`` 呼叫）：

      Step 1 — SOP 檢索：從 Foundry IQ 取得相關資安合規 SOP 文件。
      Step 2 — Payload 分析：解析可疑 IP / 行為特徵，對照威脅情報。
      Step 3 — 決策輸出：根據前兩步產出 BLOCK / ALLOW / RATE_LIMIT。

    若任一步驟超出 ``MAX_REASONING_STEPS``（預設 3）或發生 API 超時，
    強制回傳 BLOCK，確保 Fail-Closed 資安姿態。
    """

    def __init__(self, foundry_iq_endpoint: str | None = None) -> None:
        self._endpoint = foundry_iq_endpoint
        logger.info(
            "SecOpsReasoningAgent 初始化 | foundry_iq_endpoint=%s",
            self._endpoint or "未設定（離線模式）",
        )

    # ── 公開介面 ───────────────────────────────────────────────────────────────

    async def analyze_threat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        執行多步驟威脅分析，回傳防禦決策與推理軌跡。

        Parameters
        ----------
        payload:
            結構化威脅上下文，例如：
            ``{"suspicious_ip": "1.2.3.4", "event_type": "brute_force", ...}``

        Returns
        -------
        dict
            ``{"action": DefenseAction, "reasoning_steps": list[str],
               "confidence": float, "simulated_tokens": int,
               "elapsed_ms": float, "status": str}``

        Edge Cases
        ----------
        - 空白 payload         → 立即回傳 BLOCK（不進入推理迴圈）。
        - 超過 MAX_STEPS       → 強制中斷並回傳 BLOCK。
        - asyncio.TimeoutError → 捕獲後回傳 BLOCK，附帶超時說明。
        - 任意未預期例外       → 記錄 traceback，Fail-Closed 回傳 BLOCK。
        """
        start_ms = time.monotonic() * 1000

        try:
            # ── 防禦前置：空白 payload 直接 BLOCK ─────────────────────────
            if not payload:
                logger.warning("analyze_threat | 收到空白 payload，直接 BLOCK")
                return self._build_result(
                    action=DefenseAction.BLOCK,
                    steps=["[拒絕] payload 為空，無法分析，執行預設 BLOCK"],
                    confidence=1.0,
                    tokens=0,
                    start_ms=start_ms,
                    status="blocked_empty_payload",
                )

            reasoning_steps: list[str] = []
            total_tokens = 0

            # ── Step 1：SOP 文件檢索（模擬 MCP → Foundry IQ） ─────────────
            step1_result, tokens1 = await self._step_retrieve_sop(payload)
            reasoning_steps.append(step1_result)
            total_tokens += tokens1

            # 步驟計數守衛：理論上 Step 1 已是第 1 步，但保留供未來展開用
            if len(reasoning_steps) >= MAX_REASONING_STEPS + 1:
                logger.warning("analyze_threat | 推理步驟超限，強制 BLOCK")
                return self._build_result(
                    action=DefenseAction.BLOCK,
                    steps=reasoning_steps + ["[守衛] 超過 max_steps，強制中斷"],
                    confidence=0.9,
                    tokens=total_tokens,
                    start_ms=start_ms,
                    status="blocked_max_steps",
                )

            # ── Step 2：Payload 異常分析 ───────────────────────────────────
            step2_result, tokens2 = await self._step_analyze_payload(payload, step1_result)
            reasoning_steps.append(step2_result)
            total_tokens += tokens2

            if len(reasoning_steps) >= MAX_REASONING_STEPS + 1:
                logger.warning("analyze_threat | 推理步驟超限，強制 BLOCK")
                return self._build_result(
                    action=DefenseAction.BLOCK,
                    steps=reasoning_steps + ["[守衛] 超過 max_steps，強制中斷"],
                    confidence=0.9,
                    tokens=total_tokens,
                    start_ms=start_ms,
                    status="blocked_max_steps",
                )

            # ── Step 3：決策輸出 ───────────────────────────────────────────
            action, confidence, step3_result, tokens3 = await self._step_decide(
                payload, reasoning_steps
            )
            reasoning_steps.append(step3_result)
            total_tokens += tokens3

            logger.info(
                "analyze_threat | 決策=%s confidence=%.2f steps=%d tokens=%d",
                action, confidence, len(reasoning_steps), total_tokens,
            )

            return self._build_result(
                action=action,
                steps=reasoning_steps,
                confidence=confidence,
                tokens=total_tokens,
                start_ms=start_ms,
                status="ok",
            )

        except asyncio.TimeoutError:
            # API 超時：Fail-Closed，強制 BLOCK
            logger.error("analyze_threat | Foundry IQ API 超時，強制 BLOCK")
            return self._build_result(
                action=DefenseAction.BLOCK,
                steps=["[錯誤] API 呼叫超時，執行預設 BLOCK"],
                confidence=0.95,
                tokens=0,
                start_ms=start_ms,
                status="blocked_timeout",
            )
        except ValueError as exc:
            logger.warning("analyze_threat | 驗證錯誤: %s", exc)
            return self._build_result(
                action=DefenseAction.BLOCK,
                steps=[f"[驗證錯誤] {exc}"],
                confidence=0.8,
                tokens=0,
                start_ms=start_ms,
                status="error_validation",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("analyze_threat | 未預期例外: %s", exc)
            return self._build_result(
                action=DefenseAction.BLOCK,
                steps=[f"[系統錯誤] {type(exc).__name__}: {exc}"],
                confidence=0.95,
                tokens=0,
                start_ms=start_ms,
                status="error_unexpected",
            )

    # ── 私有步驟方法 ───────────────────────────────────────────────────────────

    async def _step_retrieve_sop(
        self, payload: dict[str, Any]
    ) -> tuple[str, int]:
        """
        Step 1：透過模擬 MCP 呼叫從 Foundry IQ 檢索資安合規 SOP。

        待 Foundry IQ SDK 接入後，替換為真實 retrieve() 呼叫。
        回傳 (步驟描述, 消耗 token 數)。
        """
        # 模擬網路 I/O（非阻塞）；Foundry IQ 接入後改為 await client.retrieve(...)
        await asyncio.sleep(0)
        event_type = payload.get("event_type", "unknown")
        description = (
            f"[Step 1 / SOP 檢索] event_type={event_type!r} → "
            f"已從 Foundry IQ 取得 SOC2-CC6.1、NIST-IR.2 合規控制項（模擬）"
        )
        return description, _SIMULATED_TOKENS_PER_STEP

    async def _step_analyze_payload(
        self, payload: dict[str, Any], sop_context: str
    ) -> tuple[str, int]:
        """
        Step 2：對照 SOP 上下文分析可疑 Payload，產出風險評估。

        回傳 (步驟描述, 消耗 token 數)。
        """
        await asyncio.sleep(0)
        suspicious_ip = payload.get("suspicious_ip", "N/A")
        request_count = payload.get("request_count", 0)

        # 簡易風險評估邏輯（正式版改為 LLM 推理）
        risk_level = "HIGH" if int(request_count) > 100 else "LOW"
        description = (
            f"[Step 2 / Payload 分析] IP={suspicious_ip}, "
            f"request_count={request_count}, risk_level={risk_level}"
        )
        return description, _SIMULATED_TOKENS_PER_STEP

    async def _step_decide(
        self, payload: dict[str, Any], prior_steps: list[str]
    ) -> tuple[DefenseAction, float, str, int]:
        """
        Step 3：根據前兩步推理結果決定最終防禦動作。

        回傳 (action, confidence, 步驟描述, 消耗 token 數)。
        """
        await asyncio.sleep(0)
        request_count = int(payload.get("request_count", 0))

        # 決策規則（待 Foundry IQ 推理引擎接入後可轉為 Chain-of-Thought prompt）
        if request_count > 500:
            action, confidence = DefenseAction.BLOCK, 0.97
        elif request_count > 100:
            action, confidence = DefenseAction.RATE_LIMIT, 0.85
        else:
            action, confidence = DefenseAction.ALLOW, 0.75

        description = (
            f"[Step 3 / 決策] action={action.value}, "
            f"confidence={confidence:.2f}，依據前序 {len(prior_steps)} 步推理"
        )
        return action, confidence, description, _SIMULATED_TOKENS_PER_STEP

    # ── 輔助方法 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_result(
        *,
        action: DefenseAction,
        steps: list[str],
        confidence: float,
        tokens: int,
        start_ms: float,
        status: str,
    ) -> dict[str, Any]:
        elapsed = time.monotonic() * 1000 - start_ms
        return {
            "action":            action.value,
            "reasoning_steps":   steps,
            "confidence":        confidence,
            "simulated_tokens":  tokens,
            "elapsed_ms":        round(elapsed, 2),
            "status":            status,
        }
