"""犇犇爬虫（唯一需要 Cookie）。

端点：GET <base>/api/feed/list?user={uid}&page={n}
需要：cookie {_uid, __client_id}
返回：{feeds: {count, perPage, result: [{id, type, time, content, user}]}}

严格走 AUTHED 节点 + Cookie 池 + 最保守限流。
"""
from __future__ import annotations

import time as _t
from datetime import datetime, timezone

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.exceptions import (
    CrawlerAccountInvalid,
    CrawlerBlockedError,
    CrawlerError,
)
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.cookies import (
    lease_account,
    mark_account_failed,
    mark_account_ok,
)
from app.crawler.http import fetch_authed
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, LuoguColor, utcnow
from app.models.luogu_content import Feed
from app.models.luogu_user import LuoguUser

log = get_logger(__name__)


async def crawl_user_page(uid: int, *, page: int = 1, trigger: str = "scheduled") -> None:
    """爬某用户犇犇的一页。"""
    lock_id = f"{uid}:{page}"
    async with task_lock("feed", lock_id, ttl_sec=60) as got:
        if not got:
            log.info("crawl_feed.skip_locked", uid=uid, page=page)
            return
        await _crawl_inner(uid, page, trigger=trigger)


async def _crawl_inner(uid: int, page: int, *, trigger: str) -> None:
    node = get_default_node(NodeKind.AUTHED)
    redis = get_redis()
    url_path = f"/api/feed/list?user={uid}&page={page}"

    async with lease_account() as acc:
        if acc is None:
            # 池子枯竭：所有账号 QPH 已用满 / 全被禁用 / 全被锁。
            # 写一条 failed 审计便于在管理后台和 crawl_task 表里看到，
            # 否则任务直接消失，运维只能去 worker.log 翻 qph_exceeded。
            task_id = await record_task_start(
                "feed",
                url_path,
                trigger=trigger_from(trigger),
                node_id=node.node_id,
                account_id=None,
            )
            await record_task_done(
                task_id,
                status=CrawlTaskStatus.failed,
                error_msg="no_account_available: 所有 Cookie 账号都不可用（QPH 用满 / 被禁用 / 锁占用）",
                duration_ms=0,
            )
            log.warning("crawl_feed.no_account_available", uid=uid)
            raise CrawlerError("没有可用的爬取账号")

        task_id = await record_task_start(
            "feed",
            url_path,
            trigger=trigger_from(trigger),
            node_id=node.node_id,
            account_id=acc.account_id,
        )
        start = _t.monotonic()
        try:
            result = await fetch_authed(
                url_path,
                node=node,
                redis=redis,
                cookies=acc.as_cookie_dict(),
                account_id=acc.account_id,
                params={"user": uid, "page": page},
                accept_json=True,
                parse="json",
            )
            if result.data is None or "feeds" not in result.data:
                raise CrawlerError("feed 返回无 feeds 字段")
            feeds_obj = result.data["feeds"]
            results = feeds_obj.get("result") or []
            if not isinstance(results, list):
                raise CrawlerError("feeds.result 非数组")

            async with db_session() as session:
                inserted = await _insert_feeds(session, results)
                await _sync_users_from_feeds(session, results)
                # 若是 page=1 且有数据，更新该用户 last_active_feed_at
                if page == 1 and results:
                    latest_time = max(int(r.get("time") or 0) for r in results if isinstance(r, dict))
                    if latest_time > 0:
                        u = await session.get(LuoguUser, uid)
                        if u is not None:
                            new_dt = datetime.fromtimestamp(latest_time, tz=timezone.utc)
                            # MySQL 拿出来是 naive，强制补 UTC 再比较
                            cur = u.last_active_feed_at
                            if cur is not None and cur.tzinfo is None:
                                cur = cur.replace(tzinfo=timezone.utc)
                            if cur is None or cur < new_dt:
                                u.last_active_feed_at = new_dt
                await session.commit()

            dur = int((_t.monotonic() - start) * 1000)
            await record_task_done(
                task_id,
                status=CrawlTaskStatus.success,
                http_status=result.status,
                duration_ms=dur,
            )
            await mark_account_ok(acc.account_id)
            log.info("crawl_feed.done", uid=uid, page=page, inserted=inserted, total=len(results))

        except CrawlerAccountInvalid as e:
            # cookie 失效 → 立即禁用账号
            dur = int((_t.monotonic() - start) * 1000)
            await record_task_done(
                task_id,
                status=CrawlTaskStatus.failed,
                error_msg=str(e),
                duration_ms=dur,
            )
            await mark_account_failed(
                acc.account_id, reason=f"Cookie 失效: {e}", disable=True
            )
            raise
        except CrawlerBlockedError as e:
            # 注意：CrawlerBlockedError 既可能是真"目标站点拦截"（429/CF），
            # 也可能是"节点令牌桶排队超时" —— 后者跟账号无关，不该让账号背锅。
            # 通过 error message 区分两类。
            dur = int((_t.monotonic() - start) * 1000)
            await record_task_done(
                task_id,
                status=CrawlTaskStatus.rate_limited,
                error_msg=str(e),
                duration_ms=dur,
            )
            if "限流/熔断中" in str(e) or "等待" in str(e):
                # 节点排队超时，不计入账号失败
                log.info("crawl_feed.node_busy", uid=uid, page=page, error=str(e))
            else:
                await mark_account_failed(
                    acc.account_id, reason=f"被拦截（429/403）: {e}", disable=False
                )
            raise
        except Exception as e:
            dur = int((_t.monotonic() - start) * 1000)
            await record_task_done(
                task_id,
                status=CrawlTaskStatus.failed,
                error_msg=str(e),
                duration_ms=dur,
            )
            log.error("crawl_feed.failed", uid=uid, page=page, error=str(e))
            raise


async def _insert_feeds(session: AsyncSession, rows: list) -> int:
    """按犇犇原始 id 做主键，重复的自动忽略。"""
    data = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        fid = r.get("id")
        user = r.get("user") or {}
        uid = int(user.get("uid") or 0)
        t = r.get("time")
        if fid is None or uid == 0 or t is None:
            continue
        data.append(
            {
                "id": int(fid),
                "author_uid": uid,
                "type": int(r.get("type") or 1),
                "time": datetime.fromtimestamp(int(t), tz=timezone.utc),
                "content_md": r.get("content") or "",
                "crawled_at": utcnow(),
            }
        )
    if not data:
        return 0
    stmt = mysql_insert(Feed).values(data).prefix_with("IGNORE")
    await session.execute(stmt)
    return len(data)


async def _sync_users_from_feeds(session: AsyncSession, rows: list) -> None:
    """顺带更新发言用户的基本信息。"""
    now = utcnow()
    seen: set[int] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        user = r.get("user") or {}
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
            existing.avatar = user.get("avatar") or existing.avatar
            existing.color = color
            existing.is_admin = bool(user.get("isAdmin"))
            existing.is_banned = bool(user.get("isBanned"))
            existing.last_crawled_at = now
