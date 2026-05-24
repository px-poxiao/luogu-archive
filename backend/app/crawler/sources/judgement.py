"""陶片放逐爬虫。

端点：GET <base>/judgement   Accept: application/json
返回：{logs: [{user, reason, revokedPermission, addedPermission, time}]}
500 条一次性给，不分页。无需登录。
"""
from __future__ import annotations

import time as _t
from datetime import datetime, timezone

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_content import Judgement
from app.models.luogu_user import LuoguUser

log = get_logger(__name__)


async def crawl_all(*, trigger: str = "scheduled") -> None:
    """爬全站陶片 500 条，全局单次锁（无参数）。"""
    async with task_lock("judgement", "all", ttl_sec=60) as got:
        if not got:
            log.info("crawl_judgement.skip_locked")
            return
        await _crawl_inner(trigger=trigger)


async def _crawl_inner(*, trigger: str) -> None:
    # /judgement 走 cn 主站（_resolve_url 强制），节点也得用 cn 主站节点
    # 否则海外节点 token bucket / 熔断状态会被主站 0.1 req/s 限速污染
    node = get_default_node(NodeKind.ANON, cn=True)
    redis = get_redis()
    task_id = await record_task_start(
        "judgement", "/judgement", trigger=trigger_from(trigger), node_id=node.node_id
    )

    start = _t.monotonic()
    try:
        result = await fetch_anon(
            "/judgement", node=node, redis=redis, accept_json=True, parse="json"
        )
        if result.data is None or "logs" not in result.data:
            raise CrawlerError("judgement 返回无 logs")

        logs = result.data["logs"]
        if not isinstance(logs, list):
            raise CrawlerError("judgement.logs 非数组")

        async with db_session() as session:
            count = await _insert_judgements(session, logs)
            await _sync_users_from_judgement(session, logs)
            await session.commit()

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )
        log.info("crawl_judgement.done", inserted=count, total=len(logs))
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("crawl_judgement.failed", error=str(e))
        raise


async def _insert_judgements(session: AsyncSession, logs: list) -> int:
    """批量 INSERT IGNORE，UNIQUE(uid,time,reason_hash) 自动去重。"""
    import hashlib

    rows = []
    for log_item in logs:
        if not isinstance(log_item, dict):
            continue
        user = log_item.get("user") or {}
        uid = int(user.get("uid") or 0)
        if uid == 0:
            continue
        t = log_item.get("time")
        if t is None:
            continue
        reason = log_item.get("reason") or ""
        reason_hash = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:32]
        rows.append(
            {
                "uid": uid,
                "username_snapshot": user.get("name") or f"UID_{uid}",
                "reason": reason,
                "reason_hash": reason_hash,
                "revoked_permission": int(log_item.get("revokedPermission") or 0),
                "added_permission": int(log_item.get("addedPermission") or 0),
                "time": datetime.fromtimestamp(int(t), tz=timezone.utc),
                "crawled_at": utcnow(),
            }
        )
    if not rows:
        return 0
    stmt = mysql_insert(Judgement).values(rows).prefix_with("IGNORE")
    await session.execute(stmt)
    return len(rows)


async def _sync_users_from_judgement(session: AsyncSession, logs: list) -> None:
    """陶片返回里带完整 user 对象，顺便 upsert luogu_users 主表最新信息。

    不走完整的 user.crawl_one（会再发一次请求），仅做最精简的"已知字段"更新。
    注意：同一批 logs 里同一个 uid 可能出现多次，用 seen set 去重，
    避免"第一次 session.get 未命中 → add 未 flush → 第二次再 add → 主键冲突"。
    """
    from app.models._common import LuoguColor

    now = utcnow()
    seen: set[int] = set()
    for log_item in logs:
        user = log_item.get("user") or {}
        uid = int(user.get("uid") or 0)
        if uid == 0 or uid in seen:
            continue
        seen.add(uid)
        name = user.get("name") or f"UID_{uid}"
        try:
            color = LuoguColor(user.get("color") or "Gray")
        except ValueError:
            color = LuoguColor.Gray

        existing = await session.get(LuoguUser, uid)
        if existing is None:
            session.add(
                LuoguUser(
                    uid=uid,
                    name=name,
                    avatar=user.get("avatar"),
                    background=user.get("background"),
                    slogan=user.get("slogan"),
                    badge=user.get("badge"),
                    color=color,
                    is_admin=bool(user.get("isAdmin")),
                    is_banned=bool(user.get("isBanned")),
                    ccf_level=int(user.get("ccfLevel") or 0),
                    xcpc_level=int(user.get("xcpcLevel") or 0),
                    first_crawled_at=now,
                    last_crawled_at=now,
                )
            )
        else:
            # 不动 name_versions（避免和完整 user 爬虫抢，由 user.crawl_one 管理）
            existing.avatar = user.get("avatar") or existing.avatar
            existing.color = color
            existing.is_admin = bool(user.get("isAdmin"))
            existing.is_banned = bool(user.get("isBanned"))
            existing.last_crawled_at = now
