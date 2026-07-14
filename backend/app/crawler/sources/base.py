"""数据源爬虫的公共工具。

- sha256_hex       对内容做 SHA-256（版本判重）
- record_task      写 CrawlTask 审计日志
- with_task_lock   同 URL 幂等锁上下文
"""
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import db_session
from app.core.locks import DistributedLock, lock_key
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.models._common import CrawlTaskStatus, CrawlTrigger, utcnow
from app.models.task import CrawlTask

log = get_logger(__name__)


def sha256_hex(text: str) -> str:
    """归一化的内容哈希：先统一换行再 hash，避免 CRLF/LF 抖动造成假版本。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@asynccontextmanager
async def task_lock(scope: str, ident: str, *, ttl_sec: int | None = None):
    """同 URL 只允许一个 worker 在爬。拿不到锁即 yield False。

    scope 例：'article' / 'user' / 'feed'
    ident 例：article_id / uid / "{uid}:{page}"
    """
    redis = get_redis()
    lock = DistributedLock(redis)
    key = lock_key(f"crawl:{scope}", ident)
    # 正常任务可能包含解析、批量写库和审计；锁不能早于任务级限流租约失效。
    effective_ttl = max(ttl_sec or settings.CRAWLER_TASK_LOCK_TTL_SEC, 300)
    async with lock.guard(key, ttl_sec=effective_ttl) as got:
        yield got


async def record_task_start(
    task_type: str,
    url: str,
    *,
    trigger: CrawlTrigger,
    node_id: str | None = None,
    account_id: int | None = None,
) -> int:
    """爬虫启动时写一条 pending 记录，返回 CrawlTask.id 便于后续更新。"""
    async with db_session() as session:
        t = CrawlTask(
            task_type=task_type,
            url=url,
            node_id=node_id,
            account_id=account_id,
            status=CrawlTaskStatus.running,
            triggered_by=trigger,
            started_at=utcnow(),
        )
        session.add(t)
        await session.commit()
        return t.id


async def record_task_done(
    task_id: int,
    *,
    status: CrawlTaskStatus,
    http_status: int | None = None,
    error_msg: str | None = None,
    duration_ms: int | None = None,
) -> None:
    async with db_session() as session:
        t = await session.get(CrawlTask, task_id)
        if t is None:
            log.warning("crawl_task_missing", task_id=task_id)
            return
        t.status = status
        t.http_status = http_status
        t.error_msg = error_msg[:4000] if error_msg else None
        t.duration_ms = duration_ms
        t.finished_at = utcnow()
        await session.commit()


def trigger_from(str_val: str) -> CrawlTrigger:
    """把 actor 的 trigger str 转为枚举。"""
    try:
        return CrawlTrigger(str_val)
    except ValueError:
        return CrawlTrigger.internal


async def get_session() -> AsyncSession:
    """便于非上下文场景拿 session（调用方负责关闭）。"""
    # 主要给调用方：async with db_session() as session: ...
    # 本函数基本不被直接调用，保留作为备用
    raise RuntimeError("请使用 db_session() 上下文管理器")
