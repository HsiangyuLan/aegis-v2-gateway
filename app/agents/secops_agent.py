"""
SecOps Reasoning Agent — 生產環境版本（GitHub Models GPT-4o）

提供 ``SecOpsReasoningAgent``：透過 OpenAI SDK 連接 GitHub Models GPT-4o 算力，
執行真實 LLM 推理，針對可疑 Payload 進行資安合規檢查，
並輸出具有商業可追溯性的防禦決策（BLOCK / ALLOW / RATE_LIMIT）。

整合介面
--------
- Foundry API Key 與 Endpoint 透過 ``app.core.config`` 讀取（來源：`.env`）。
- 全程 async；可在 FastAPI lifespan 中作為 ``app.state.secops_agent`` 掛載。
- 啟用 JSON Mode (`response_format={"type": "json_object"}`)，確保輸出結構穩定。
- 任何例外均觸發 Fail-Closed 機制，回傳預設 BLOCK，確保 API Gateway 不崩潰。
- PII 在進入本模組前已由 ``antigravity_core.execute_command`` 完成遮蔽。
"""
from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.db.ledger_db import insert_ledger_entry

logger = logging.getLogger(__name__)

# ── 防禦決策枚舉 ───────────────────────────────────────────────────────────────

class DefenseAction(str, Enum):
    BLOCK      = "BLOCK"
    ALLOW      = "ALLOW"
    RATE_LIMIT = "RATE_LIMIT"


# ── 常數 ───────────────────────────────────────────────────────────────────────

MAX_REASONING_STEPS = 3  # 規定 LLM 最多執行 3 步推理

# Fail-Closed 預設回傳：任何 API 異常均回傳此安全基線，確保 Gateway 不崩潰
_FAIL_CLOSED_RESPONSE: dict[str, Any] = {
    "action": "BLOCK",
    "confidence": 1.0,
    "reasoning_steps": ["API 呼叫失敗，觸發 Fail-Closed 安全機制，預設阻擋"],
    "simulated_tokens": 0,
}

# 合法 action 值集合（用於回傳驗證）
_VALID_ACTIONS = frozenset(a.value for a in DefenseAction)

# ── System Prompt（微軟 Foundry IQ 企業級 SecOps 分析師角色） ──────────────────

_SYSTEM_PROMPT = (
    "你是一個微軟 Foundry IQ 支援的企業級 SecOps 分析師。"
    "請根據傳入的資安日誌與 Payload 進行邏輯推理，判斷這是否為惡意攻擊。"
    f"請執行最多 {MAX_REASONING_STEPS} 個推理步驟後給出結論。\n\n"
    "你必須以純 JSON 格式回傳，包含以下四個 Key（不得包含其他欄位）：\n"
    "- action (string): 防禦決策，必須是 BLOCK、ALLOW 或 RATE_LIMIT 其中之一\n"
    "- confidence (float): 信心分數，範圍 0.0 到 1.0\n"
    "- reasoning_steps (array of strings): 你的推理步驟，每個元素為一個步驟描述\n"
    "- simulated_tokens (integer): 模擬本次分析消耗的 token 量，供 FinOps 紀錄\n"
)


# ── Agent 主體 ─────────────────────────────────────────────────────────────────

class SecOpsReasoningAgent:
    """
    多步驟推理資安代理（生產環境版本）。

    透過 GitHub Models GPT-4o 執行真實 LLM 推理，
    產出 BLOCK / ALLOW / RATE_LIMIT 防禦決策。

    啟動流程：
      1. 從 ``get_settings()`` 讀取 FOUNDRY_API_KEY 與 FOUNDRY_ENDPOINT。
      2. 建立 ``AsyncOpenAI`` 客戶端（指向 GitHub Models endpoint）。
      3. 每次 ``analyze_threat`` 呼叫均發送真實 Chat Completion 請求。
      4. 任何例外均觸發 Fail-Closed，回傳預設 BLOCK。
    """

    def __init__(self) -> None:
        settings = get_settings()
        # 建立非同步 OpenAI 客戶端，指向 GitHub Models 端點
        self.llm_client = AsyncOpenAI(
            api_key=settings.foundry_api_key,
            base_url=settings.foundry_endpoint,
        )
        self._ledger_db_path: str = settings.finops_ledger_db_path
        logger.info(
            "SecOpsReasoningAgent 初始化（生產模式）| endpoint=%s | api_key_set=%s | ledger_db=%s",
            settings.foundry_endpoint,
            bool(settings.foundry_api_key),
            self._ledger_db_path,
        )

    # ── 公開介面 ───────────────────────────────────────────────────────────────

    async def analyze_threat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        執行真實 LLM 威脅分析，回傳防禦決策與推理軌跡。

        Parameters
        ----------
        payload:
            結構化威脅上下文，例如：
            ``{"suspicious_ip": "1.2.3.4", "event_type": "brute_force", ...}``

        Returns
        -------
        dict
            ``{"action": str, "confidence": float, "reasoning_steps": list[str],
               "simulated_tokens": int, "elapsed_ms": float, "status": str}``

        Edge Cases
        ----------
        - 空白 payload   → 立即回傳 BLOCK（不消耗 LLM token）。
        - API 任何例外   → Fail-Closed，回傳預設 BLOCK，附帶錯誤 status。
        - 非法 action 值 → 視為 API 格式異常，同樣觸發 Fail-Closed。
        """
        start_ms = time.monotonic() * 1000

        # ── 防禦前置：空白 payload 直接 BLOCK，不消耗 LLM token ─────────────
        if not payload:
            logger.warning("analyze_threat | 收到空白 payload，直接 BLOCK")
            return self._build_result(
                llm_response={
                    **_FAIL_CLOSED_RESPONSE,
                    "reasoning_steps": ["payload 為空，無法分析，執行預設 BLOCK"],
                },
                start_ms=start_ms,
                status="blocked_empty_payload",
            )

        try:
            # ── 組裝使用者訊息，含完整 payload 上下文 ────────────────────────
            user_message = (
                "以下是需要分析的資安事件 Payload：\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                f"請執行最多 {MAX_REASONING_STEPS} 步的邏輯推理後給出最終判斷。"
            )

            # ── 呼叫 GitHub Models GPT-4o，強制啟用 JSON Mode ────────────────
            response = await self.llm_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # 低溫度確保輸出穩定、可重現
            )

            raw_content = response.choices[0].message.content or "{}"
            llm_data: dict[str, Any] = json.loads(raw_content)

            # ── 驗證四個必要 Key 存在性 ───────────────────────────────────────
            for required_key in ("action", "confidence", "reasoning_steps", "simulated_tokens"):
                if required_key not in llm_data:
                    raise ValueError(f"LLM 回傳缺少必要 Key: {required_key!r}")

            # ── 驗證 action 值合法性 ──────────────────────────────────────────
            if llm_data["action"] not in _VALID_ACTIONS:
                raise ValueError(f"LLM 回傳非法 action 值: {llm_data['action']!r}，必須為 {_VALID_ACTIONS}")

            tokens_used: int = int(llm_data.get("simulated_tokens", 0))
            action_value: str = llm_data["action"]

            logger.info(
                "analyze_threat | LLM 決策=%s confidence=%.2f simulated_tokens=%d",
                action_value,
                float(llm_data.get("confidence", 0.0)),
                tokens_used,
            )

            result = self._build_result(
                llm_response=llm_data,
                start_ms=start_ms,
                status="ok",
            )

            # ── 非同步寫入 FinOps SQLite Ledger（fire-and-forget，不阻塞回傳）────
            import asyncio as _asyncio
            _asyncio.ensure_future(
                insert_ledger_entry(
                    self._ledger_db_path,
                    service="secops_agent",
                    tokens=tokens_used,
                    action=action_value,
                    status="ok",
                )
            )

            return result

        except Exception as exc:
            # ── Graceful Degradation：任何例外（Timeout / ConnectionError / 解析錯誤）
            #    均觸發 Fail-Closed，直接回傳預設 BLOCK，絕不讓 Gateway 崩潰。
            logger.exception(
                "analyze_threat | API 呼叫失敗，觸發 Fail-Closed 安全機制 | %s: %s",
                type(exc).__name__,
                exc,
            )
            result = self._build_result(
                llm_response=_FAIL_CLOSED_RESPONSE,
                start_ms=start_ms,
                status="error_fail_closed",
            )

            # ── 失敗情況同樣寫入 Ledger，記錄 0 tokens + fail 狀態 ─────────────
            import asyncio as _asyncio
            _asyncio.ensure_future(
                insert_ledger_entry(
                    self._ledger_db_path,
                    service="secops_agent",
                    tokens=0,
                    action="BLOCK",
                    status="error_fail_closed",
                )
            )

            return result

    # ── 輔助方法 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_result(
        *,
        llm_response: dict[str, Any],
        start_ms: float,
        status: str,
    ) -> dict[str, Any]:
        """
        將 LLM 回傳與執行元數據合併為標準輸出格式。

        Parameters
        ----------
        llm_response:
            已驗證的 LLM JSON 回傳（或 Fail-Closed 預設值）。
        start_ms:
            ``time.monotonic() * 1000`` 的起始時間戳，用於計算 elapsed_ms。
        status:
            執行狀態字串（"ok" / "error_fail_closed" / "blocked_empty_payload" 等）。
        """
        elapsed = time.monotonic() * 1000 - start_ms
        return {
            "action":           llm_response.get("action", "BLOCK"),
            "confidence":       float(llm_response.get("confidence", 1.0)),
            "reasoning_steps":  llm_response.get("reasoning_steps", []),
            "simulated_tokens": int(llm_response.get("simulated_tokens", 0)),
            "elapsed_ms":       round(elapsed, 2),
            "status":           status,
        }
