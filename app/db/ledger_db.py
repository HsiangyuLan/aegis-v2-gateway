"""
FinOps Ledger Database — aiosqlite 非同步 SQLite 讀寫模組

職責
----
1. init_ledger_db(db_path)  — 建立 ledger_logs 資料表（冪等，若已存在則跳過）。
2. insert_ledger_entry(...)  — 非同步插入一筆推理交易紀錄。
3. 查詢邏輯由 app/api/ledger.py 各端點直接開啟連線執行，本模組只提供公共工具函式。

資料表結構
----------
CREATE TABLE IF NOT EXISTS ledger_logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,   -- ISO 8601 UTC
    service   TEXT    NOT NULL,   -- e.g. "secops_agent"
    tokens    INTEGER NOT NULL,   -- 本次推理消耗 tokens
    cost_usd  REAL    NOT NULL,   -- 換算 USD（tokens / 1000 × $0.000267）
    action    TEXT    NOT NULL,   -- BLOCK / ALLOW / RATE_LIMIT
    status    TEXT    NOT NULL    -- "ok" / "error_fail_closed" / 其他
)

設計原則
--------
- 全程使用 aiosqlite，確保 FastAPI 事件迴圈不被 SQLite I/O 阻塞。
- 所有讀寫包覆完整 try-except，失敗時以 exc_info=True 印出完整堆疊。
- WAL 模式 (journal_mode=WAL) 提升並發讀寫吞吐量。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# 費率常數：GPT-4o 輸出估算（同 dashboard.py 保持一致）
_COST_PER_1K_TOKENS: float = 0.000267  # USD / 1k tokens


# ── DDL ────────────────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ledger_logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    service   TEXT    NOT NULL,
    tokens    INTEGER NOT NULL,
    cost_usd  REAL    NOT NULL,
    action    TEXT    NOT NULL,
    status    TEXT    NOT NULL
)
"""

_CREATE_IDX_SQL = """
CREATE INDEX IF NOT EXISTS idx_ledger_logs_timestamp
ON ledger_logs (timestamp DESC)
"""


# ── 初始化 ─────────────────────────────────────────────────────────────────────

async def init_ledger_db(db_path: str) -> None:
    """
    建立 SQLite 資料庫並初始化 ledger_logs 資料表（冪等）。

    在 FastAPI lifespan startup 時呼叫一次即可。
    若資料庫或資料表已存在，此函式安全地跳過（IF NOT EXISTS）。

    Parameters
    ----------
    db_path:
        SQLite 檔案路徑（絕對或相對路徑）。
        若父目錄不存在，會自動建立。

    Raises
    ------
    aiosqlite.Error
        DB 初始化失敗時向上拋出，由 lifespan 捕捉並記錄。
    """
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(_CREATE_TABLE_SQL)
            await db.execute(_CREATE_IDX_SQL)
            await db.commit()
        logger.info("[LEDGER DB] 資料庫初始化完成 | path=%s", db_path)
    except Exception as exc:
        logger.error(
            "[LEDGER DB] 初始化失敗 [%s]: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        raise


# ── 寫入 ───────────────────────────────────────────────────────────────────────

async def insert_ledger_entry(
    db_path: str,
    *,
    service: str,
    tokens: int,
    action: str,
    status: str,
) -> None:
    """
    非同步插入一筆推理交易紀錄至 ledger_logs。

    cost_usd 由本函式依費率常數自動換算，呼叫端不需傳入。

    Parameters
    ----------
    db_path:
        SQLite 檔案路徑。
    service:
        服務識別名稱，例如 "secops_agent"。
    tokens:
        本次推理消耗的 token 數（simulated_tokens）。
    action:
        防禦決策字串（BLOCK / ALLOW / RATE_LIMIT）。
    status:
        執行狀態字串（"ok" / "error_fail_closed" 等）。
    """
    cost_usd: float = round(tokens / 1000.0 * _COST_PER_1K_TOKENS, 6)
    timestamp: str = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO ledger_logs (timestamp, service, tokens, cost_usd, action, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (timestamp, service, tokens, cost_usd, action, status),
            )
            await db.commit()
            logger.info(
                "[LEDGER DB INSERT] Successfully saved transaction ID: %d | "
                "service=%s tokens=%d cost_usd=%.6f action=%s status=%s",
                cursor.lastrowid,
                service,
                tokens,
                cost_usd,
                action,
                status,
            )
    except Exception as exc:
        logger.error(
            "[LEDGER DB INSERT] 寫入失敗 [%s]: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )


# ── 查詢輔助 ────────────────────────────────────────────────────────────────────

async def fetch_ledger_history(
    db_path: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    分頁查詢 ledger_logs，依時間遞減排序。

    Parameters
    ----------
    db_path:
        SQLite 檔案路徑。
    limit:
        每頁筆數，預設 50，上限 200。
    offset:
        跳過前 N 筆（0-based 分頁偏移）。

    Returns
    -------
    list[dict[str, Any]]
        每筆紀錄包含 id / timestamp / service / tokens / cost_usd / action / status。
        若資料庫尚未建立或查詢失敗，回傳空列表（Fail-Closed）。
    """
    safe_limit = max(1, min(limit, 200))

    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, timestamp, service, tokens, cost_usd, action, status
                FROM ledger_logs
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as exc:
        logger.error(
            "[LEDGER DB QUERY] 查詢失敗 [%s]: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return []


async def count_ledger_entries(db_path: str) -> int:
    """
    回傳 ledger_logs 的總筆數（供分頁計算 totalCount）。

    Parameters
    ----------
    db_path:
        SQLite 檔案路徑。

    Returns
    -------
    int
        總筆數；查詢失敗時回傳 0。
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM ledger_logs")
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
    except Exception as exc:
        logger.error(
            "[LEDGER DB COUNT] 計數失敗 [%s]: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return 0
