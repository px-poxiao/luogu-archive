"""入口页活跃用户发现。

目标：从 /discuss、/article 这些公开入口页扒出活跃用户 UID，
塞入分层轮询池（更新 LuoguUser.last_active_feed_at 触发 S 桶升级）。

策略简化版：每次扒到的 UID 如果近 24 小时没更新过，派发一次用户主页爬取，
让 user.crawl_one 来做完整更新。
"""
from __future__ import annotations

import re
import time as _t

from sqlalchemy import select

from app.core.db import db_session
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.lentille import data_from_lentille
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_user import LuoguUser

log = get_logger(__name__)

# 从 HTML / JSON 里兜底正则提取 uid
_UID_PAT = re.compile(r'/user/(\d+)')


def _uids_from_body(body: str, limit: int = 200) -> list[int]:
    uids: list[int] = []
    seen: set[int] = set()
    for m in _UID_PAT.finditer(body):
        uid = int(m.group(1))
        if uid in seen:
            continue
        seen.add(uid)
        uids.append(uid)
        if len(uids) >= limit:
            break
    return uids


async def _discover(url_path: str, task_type: str, *, trigger: str) -> list[int]:
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    task_id = await record_task_start(
        task_type, url_path, trigger=trigger_from(trigger), node_id=node.node_id
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(url_path, node=node, redis=redis)
        # lentille 结构化不稳定，统一用正则兜底
        uids = _uids_from_body(result.body_text)
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )
        return uids
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("discovery.failed", url=url_path, error=str(e))
        return []


async def from_discuss(*, trigger: str = "scheduled") -> None:
    uids = await _discover("/discuss", "discovery_discuss", trigger=trigger)
    log.info("discovery.discuss", count=len(uids))
    await _schedule_user_crawl(uids)


async def from_article_list(*, trigger: str = "scheduled") -> None:
    uids = await _discover("/article", "discovery_article", trigger=trigger)
    log.info("discovery.article", count=len(uids))
    await _schedule_user_crawl(uids)


async def _schedule_user_crawl(uids: list[int]) -> None:
    """对发现的 UID 派发用户主页爬取任务（如果最近 24h 没爬过）。"""
    if not uids:
        return
    from datetime import timedelta

    now = utcnow()
    recent_threshold = now - timedelta(hours=24)

    async with db_session() as session:
        q = select(LuoguUser.uid, LuoguUser.last_crawled_at).where(
            LuoguUser.uid.in_(uids)
        )
        rows = (await session.execute(q)).all()
        known = {r.uid: r.last_crawled_at for r in rows}

    # 未知 uid 或 24h 前爬的 → 派发
    to_crawl = [
        uid
        for uid in uids
        if known.get(uid) is None or known[uid] < recent_threshold
    ]
    if not to_crawl:
        return

    # 延迟 import，避免循环依赖
    from app.tasks.actors.crawl import crawl_user

    for uid in to_crawl:
        crawl_user.send(uid, "discovery")
    log.info("discovery.enqueued_user_crawl", count=len(to_crawl))
