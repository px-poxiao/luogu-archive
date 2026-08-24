"""讨论区爬虫：每个任务只读取一页，分页任务由首个任务继续派发。"""
from __future__ import annotations

import math
import time as _t
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.exceptions import CrawlerError, CrawlerNotFound
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.cookies import lease_account
from app.crawler.http import fetch_authed
from app.crawler.lentille import data_from_lentille
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.article import _upsert_author_brief
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    sha256_hex,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_content import (
    Discussion,
    DiscussionReply,
    DiscussionReplyVersion,
    DiscussionVersion,
)

log = get_logger(__name__)


def _source_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _author_uid(author: Any) -> int | None:
    if not isinstance(author, dict) or not author.get("uid"):
        return None
    try:
        return int(author["uid"])
    except (TypeError, ValueError):
        return None


def _discussion_fields(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    post = data.get("post")
    replies = data.get("replies")
    if not isinstance(post, dict) or not isinstance(replies, dict):
        raise CrawlerError(f"讨论详情字段缺失，可见 keys: {list(data.keys())}")
    if post.get("valid") is False:
        raise CrawlerNotFound("讨论已被源站删除或隐藏")
    rows = replies.get("result")
    if not isinstance(rows, list):
        raise CrawlerError("讨论回复列表格式异常")

    # recentReply / pinnedReply 可能不在当前 result 中，按回复 ID 去重后一起归档。
    candidates = [row for row in rows if isinstance(row, dict)]
    for key in ("recentReply", "pinnedReply"):
        extra = post.get(key)
        if isinstance(extra, dict):
            candidates.append(extra)
    unique: dict[int, dict[str, Any]] = {}
    for row in candidates:
        try:
            unique[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return post, replies, list(unique.values())


async def crawl_page(
    discussion_id: int,
    *,
    page: int = 0,
    trigger: str = "manual",
    enqueue_remaining: bool = True,
) -> None:
    """读取一页讨论；page=0 时从本地最后归档页的前一页开始。"""
    async with db_session() as session:
        existing = await session.get(Discussion, discussion_id)
        if existing is not None and existing.auto_crawl_paused and trigger != "manual":
            log.info("crawl_discussion.skip_paused", discussion_id=discussion_id)
            return
        if page <= 0:
            page = max(1, (existing.last_crawled_page or 1) - 1) if existing else 1

    redis = get_redis()
    recent_key = f"crawl:discussion_page_recent:{discussion_id}:{page}"
    if await redis.exists(recent_key):
        log.info("crawl_discussion.skip_recent", discussion_id=discussion_id, page=page)
        return

    async with task_lock("discussion_page", f"{discussion_id}:{page}") as got:
        if not got:
            log.info("crawl_discussion.skip_locked", discussion_id=discussion_id, page=page)
            return
        await _crawl_page_inner(
            discussion_id,
            page=page,
            trigger=trigger,
            enqueue_remaining=enqueue_remaining,
        )


async def _crawl_page_inner(
    discussion_id: int,
    *,
    page: int,
    trigger: str,
    enqueue_remaining: bool,
) -> None:
    node = get_default_node(NodeKind.AUTHED, cn=True)
    url = f"https://www.luogu.com.cn/discuss/{discussion_id}"
    task_id = await record_task_start(
        "discussion",
        f"/discuss/{discussion_id}?page={page}",
        trigger=trigger_from("manual" if trigger.startswith("manual") else trigger),
        node_id=node.node_id,
    )
    started = _t.monotonic()
    try:
        async with lease_account(cn=True) as account:
            if account is None:
                raise CrawlerError("没有可用的爬取账号")
            result = await fetch_authed(
                url,
                node=node,
                redis=get_redis(),
                cookies=account.as_cookie_dict(),
                account_id=account.account_id,
                params={"page": page},
                parse="auto",
            )
        if result.data is None:
            raise CrawlerError("讨论页无 lentille-context")
        data = data_from_lentille(result.data)
        post, replies, rows = _discussion_fields(data)

        try:
            reply_count = max(0, int(replies.get("count") or post.get("replyCount") or 0))
            per_page = max(1, int(replies.get("perPage") or len(replies.get("result") or []) or 1))
        except (TypeError, ValueError) as exc:
            raise CrawlerError("讨论分页信息格式异常") from exc
        total_pages = max(1, math.ceil(reply_count / per_page))
        page_out_of_range = page > total_pages

        async with db_session() as session:
            discussion = await _upsert_discussion(
                session,
                discussion_id,
                post,
                data.get("forum"),
                node_id=node.node_id,
            )
            for row in rows:
                await _upsert_reply(
                    session,
                    discussion_id,
                    row,
                    node_id=node.node_id,
                )
                await _upsert_author_brief(session, row.get("author"))
            await _upsert_author_brief(session, post.get("author"))

            now = utcnow()
            discussion.observed_reply_count = reply_count
            discussion.last_per_page = per_page
            discussion.last_crawled_at = now
            discussion.auto_crawl_paused = False
            discussion.auto_crawl_paused_at = None
            discussion.last_crawl_status = "ok"
            if page == total_pages:
                discussion.last_crawled_page = total_pages
                discussion.archived_reply_count = reply_count
            elif not page_out_of_range:
                discussion.last_crawled_page = max(discussion.last_crawled_page, page)
            await session.commit()

        if enqueue_remaining and page_out_of_range:
            _enqueue_next_page(
                discussion_id,
                page=max(1, total_pages - 1),
                trigger=trigger,
            )
        elif enqueue_remaining and page < total_pages:
            _enqueue_next_page(
                discussion_id,
                page=page + 1,
                trigger=trigger,
            )
        if page == total_pages:
            await get_redis().delete(f"discovery:discussion_pending:{discussion_id}")
        await get_redis().setex(
            f"crawl:discussion_page_recent:{discussion_id}:{page}",
            60,
            "1",
        )

        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=int((_t.monotonic() - started) * 1000),
        )
    except CrawlerNotFound as exc:
        await _pause_existing(discussion_id)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.skipped,
            error_msg=str(exc),
            duration_ms=int((_t.monotonic() - started) * 1000),
        )
        # 已删除或暂不可见只停止自动抓取；保留本站已有内容，不向前端加标签。
        log.info("crawl_discussion.source_unavailable", discussion_id=discussion_id, page=page)
    except Exception as exc:
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(exc),
            duration_ms=int((_t.monotonic() - started) * 1000),
        )
        log.error("crawl_discussion.failed", discussion_id=discussion_id, page=page, error=str(exc))
        raise


def _enqueue_next_page(discussion_id: int, *, page: int, trigger: str) -> None:
    from app.tasks.actors.crawl import crawl_discussion, crawl_discussion_bg

    manual_batch = trigger.startswith("manual")
    target = crawl_discussion if manual_batch else crawl_discussion_bg
    child_trigger = "manual_followup" if manual_batch else trigger
    target.send(discussion_id, page, child_trigger, True)
    log.info(
        "crawl_discussion.enqueued_next_page",
        discussion_id=discussion_id,
        page=page,
        trigger=trigger,
    )


async def _pause_existing(discussion_id: int) -> None:
    async with db_session() as session:
        discussion = await session.get(Discussion, discussion_id)
        if discussion is None:
            return
        discussion.auto_crawl_paused = True
        discussion.auto_crawl_paused_at = utcnow()
        discussion.last_crawl_status = "source_unavailable"
        await session.commit()


async def _upsert_discussion(
    session: AsyncSession,
    discussion_id: int,
    post: dict[str, Any],
    forum_raw: Any,
    *,
    node_id: str,
) -> Discussion:
    now = utcnow()
    title = str(post.get("title") or f"讨论 {discussion_id}")[:500]
    content = str(post.get("content") or "")
    if content.strip() == "已删除" and post.get("valid") is not True:
        raise CrawlerNotFound("讨论已被源站删除或隐藏")
    content_hash = sha256_hex(f"{title}\0{content}")
    author_uid = _author_uid(post.get("author"))
    forum = forum_raw if isinstance(forum_raw, dict) else post.get("forum")
    forum = forum if isinstance(forum, dict) else {}

    discussion = await session.get(Discussion, discussion_id)
    if discussion is None:
        discussion = Discussion(
            discussion_id=discussion_id,
            author_uid=author_uid,
            forum_name=str(forum.get("name"))[:128] if forum.get("name") else None,
            forum_slug=str(forum.get("slug"))[:64] if forum.get("slug") else None,
            source_time=_source_time(post.get("time")),
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(discussion)
        await session.flush()
    else:
        discussion.author_uid = author_uid or discussion.author_uid
        discussion.forum_name = str(forum.get("name"))[:128] if forum.get("name") else discussion.forum_name
        discussion.forum_slug = str(forum.get("slug"))[:64] if forum.get("slug") else discussion.forum_slug
        discussion.source_time = _source_time(post.get("time")) or discussion.source_time

    same = await session.scalar(
        select(DiscussionVersion).where(
            DiscussionVersion.discussion_id == discussion_id,
            DiscussionVersion.content_hash == content_hash,
        )
    )
    if same is None:
        same = DiscussionVersion(
            discussion_id=discussion_id,
            title=title,
            content_md=content,
            content_hash=content_hash,
            crawled_at=now,
            crawler_node_id=node_id,
        )
        session.add(same)
        await session.flush()
    discussion.current_version_id = same.id
    return discussion


async def _upsert_reply(
    session: AsyncSession,
    discussion_id: int,
    row: dict[str, Any],
    *,
    node_id: str,
) -> None:
    try:
        reply_id = int(row["id"])
    except (KeyError, TypeError, ValueError):
        return
    now = utcnow()
    content = str(row.get("content") or "")
    content_hash = sha256_hex(content)
    reply = await session.get(DiscussionReply, reply_id)
    if reply is None:
        reply = DiscussionReply(
            reply_id=reply_id,
            discussion_id=discussion_id,
            author_uid=_author_uid(row.get("author")),
            source_time=_source_time(row.get("time")),
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(reply)
        await session.flush()
    else:
        # 回复 ID 全站唯一；若上游异常复用，不能把它搬到另一个讨论。
        if reply.discussion_id != discussion_id:
            log.warning("crawl_discussion.reply_id_conflict", reply_id=reply_id)
            return
        reply.author_uid = _author_uid(row.get("author")) or reply.author_uid
        reply.source_time = _source_time(row.get("time")) or reply.source_time
        reply.last_crawled_at = now

    same = await session.scalar(
        select(DiscussionReplyVersion).where(
            DiscussionReplyVersion.reply_id == reply_id,
            DiscussionReplyVersion.content_hash == content_hash,
        )
    )
    if same is None:
        same = DiscussionReplyVersion(
            reply_id=reply_id,
            content_md=content,
            content_hash=content_hash,
            crawled_at=now,
            crawler_node_id=node_id,
        )
        session.add(same)
        await session.flush()
    reply.current_version_id = same.id
