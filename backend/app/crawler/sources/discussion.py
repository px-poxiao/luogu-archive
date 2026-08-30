"""讨论区爬虫：每个任务只读取一页，分页任务由首个任务继续派发。"""
from __future__ import annotations

import math
import time as _t
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.crawl_policy import crawl_trigger_allowed, is_user_requested_trigger
from app.core.exceptions import CrawlerError, CrawlerNotFound
from app.core.locks import DistributedLock
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.cookies import lease_account
from app.crawler.http import fetch_authed
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

# 一条大型讨论可能需要连续抓取数小时。活动链每完成一页都会续期；
# worker 停机超过此时间后锁会自然释放，调度器可以重新接管，不会永久卡住。
DISCUSSION_CHAIN_TTL_SEC = 6 * 60 * 60
_LEGACY_DRAIN_TTL_SEC = 24 * 60 * 60

_RENEW_CHAIN_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    return 1
end
return 0
"""

_RELEASE_CHAIN_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[2])
if ARGV[2] == '1' then
    redis.call('SETEX', KEYS[3], ARGV[3], '1')
end
return 1
"""


def _chain_key(discussion_id: int) -> str:
    return f"crawl:discussion_chain:{discussion_id}"


def _legacy_drain_key(discussion_id: int) -> str:
    return f"crawl:discussion_legacy_drained:{discussion_id}"


def _discovery_pending_key(discussion_id: int) -> str:
    return f"discovery:discussion_pending:{discussion_id}"


async def enqueue_discussion_crawl(
    discussion_id: int,
    *,
    page: int = 0,
    trigger: str = "manual",
    enqueue_remaining: bool = True,
    background: bool = False,
) -> str | None:
    """原子创建一条讨论归档链；已有活动链时不重复入队。"""
    if not crawl_trigger_allowed(trigger):
        log.info(
            "crawl_discussion.enqueue_skipped_by_policy",
            discussion_id=discussion_id,
            trigger=trigger,
        )
        return None
    redis = get_redis()
    lock = DistributedLock(redis)
    token = await lock.acquire(
        _chain_key(discussion_id),
        ttl_sec=DISCUSSION_CHAIN_TTL_SEC,
    )
    if token is None:
        log.info(
            "crawl_discussion.skip_active_chain",
            discussion_id=discussion_id,
            page=page,
            trigger=trigger,
        )
        return None

    try:
        # 兼容站点预览和旧版调度标记；该标记不再独立决定是否入队。
        await redis.setex(
            _discovery_pending_key(discussion_id),
            DISCUSSION_CHAIN_TTL_SEC,
            token,
        )
        from app.tasks.actors.crawl import crawl_discussion, crawl_discussion_bg

        target = crawl_discussion_bg if background else crawl_discussion
        message = target.send(
            discussion_id,
            page,
            trigger,
            enqueue_remaining,
            token,
        )
        return message.message_id
    except Exception:
        await lock.release(_chain_key(discussion_id), token)
        await redis.delete(_discovery_pending_key(discussion_id))
        raise


async def _claim_chain(
    discussion_id: int,
    chain_token: str | None,
) -> str | None:
    """校验新任务令牌，或让一条升级前遗留任务接管归档链。"""
    redis = get_redis()
    key = _chain_key(discussion_id)
    if chain_token:
        renew = redis.register_script(_RENEW_CHAIN_LUA)
        renewed = await renew(
            keys=[key],
            args=[chain_token, DISCUSSION_CHAIN_TTL_SEC],
        )
        if renewed:
            return chain_token
        # actor 失败时会主动释放链，随后队列使用相同参数重试。若期间没有
        # 新链接管，允许原令牌重新占有；SET NX 保证不会挤掉新任务。
        reclaimed = await redis.set(
            key,
            chain_token,
            nx=True,
            ex=DISCUSSION_CHAIN_TTL_SEC,
        )
        return chain_token if reclaimed else None

    # 部署前已经进入 Redis 的任务没有令牌。每个讨论只允许最先执行的
    # 那一条接管；一条新链完成后，剩余旧副本在一天内直接丢弃。
    if await redis.exists(_legacy_drain_key(discussion_id)):
        return None
    token = await DistributedLock(redis).acquire(
        key,
        ttl_sec=DISCUSSION_CHAIN_TTL_SEC,
    )
    return token


async def _renew_chain(discussion_id: int, chain_token: str) -> bool:
    redis = get_redis()
    renew = redis.register_script(_RENEW_CHAIN_LUA)
    renewed = bool(
        await renew(
            keys=[_chain_key(discussion_id)],
            args=[chain_token, DISCUSSION_CHAIN_TTL_SEC],
        )
    )
    if renewed:
        await redis.setex(
            _discovery_pending_key(discussion_id),
            DISCUSSION_CHAIN_TTL_SEC,
            chain_token,
        )
    return renewed


async def _release_chain(
    discussion_id: int,
    chain_token: str,
    *,
    suppress_legacy: bool,
) -> None:
    redis = get_redis()
    release = redis.register_script(_RELEASE_CHAIN_LUA)
    await release(
        keys=[
            _chain_key(discussion_id),
            _discovery_pending_key(discussion_id),
            _legacy_drain_key(discussion_id),
        ],
        args=[
            chain_token,
            "1" if suppress_legacy else "0",
            _LEGACY_DRAIN_TTL_SEC,
        ],
    )


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


def _non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _discussion_data(context: dict[str, Any]) -> dict[str, Any]:
    """从 lentille 完整响应或已解包响应中取得讨论原始数据。"""
    nested = context.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("post"), dict):
        return nested
    if isinstance(context.get("post"), dict) and isinstance(context.get("replies"), dict):
        return context
    raise CrawlerError(f"讨论响应字段缺失，可见 keys: {list(context.keys())}")


def _discussion_fields(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    post = data.get("post")
    replies = data.get("replies")
    if not isinstance(post, dict) or not isinstance(replies, dict):
        raise CrawlerError(f"讨论详情字段缺失，可见 keys: {list(data.keys())}")
    if post.get("valid") is False:
        raise CrawlerNotFound("讨论已被源站删除或隐藏")
    rows = replies.get("result")
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise CrawlerError("讨论回复列表格式异常")

    # recentReply 按接口定义只有 ID、作者和时间，没有正文，不能用于归档。
    # pinnedReply 是完整回复，可能不在当前 result 中，按回复 ID 补充。
    candidates = [row for row in rows if isinstance(row, dict)]
    for key in ("pinnedReply",):
        extra = post.get(key)
        if isinstance(extra, dict):
            candidates.append(extra)
    unique: dict[int, dict[str, Any]] = {}
    for row in candidates:
        try:
            reply_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        # result 中的完整回复排在前面；recentReply / pinnedReply 常是
        # 不含正文的精简对象，不能覆盖同 ID 的完整数据。
        unique.setdefault(reply_id, row)
    return post, replies, list(unique.values())


async def crawl_page(
    discussion_id: int,
    *,
    page: int = 0,
    trigger: str = "manual",
    enqueue_remaining: bool = True,
    chain_token: str | None = None,
) -> None:
    """读取一页讨论；page=0 时从本地最后归档页的前一页开始。"""
    async with db_session() as session:
        existing = await session.get(Discussion, discussion_id)
        paused = bool(
            existing is not None
            and existing.auto_crawl_paused
            and not is_user_requested_trigger(trigger)
        )
        if page <= 0:
            page = max(1, (existing.last_crawled_page or 1) - 1) if existing else 1

    claimed_token = await _claim_chain(discussion_id, chain_token)
    if claimed_token is None:
        log.info(
            "crawl_discussion.skip_duplicate_chain",
            discussion_id=discussion_id,
            page=page,
        )
        return
    await _renew_chain(discussion_id, claimed_token)

    # 部署前已经进入 Redis 的发现任务也会到达这里。先释放整条分页链，
    # 再标记旧副本已处理，确保不会继续请求下一页。
    if not crawl_trigger_allowed(trigger):
        log.info(
            "crawl_discussion.skipped_by_policy",
            discussion_id=discussion_id,
            page=page,
            trigger=trigger,
        )
        await _release_chain(
            discussion_id,
            claimed_token,
            suppress_legacy=True,
        )
        return

    if paused:
        log.info("crawl_discussion.skip_paused", discussion_id=discussion_id)
        await _release_chain(
            discussion_id,
            claimed_token,
            suppress_legacy=True,
        )
        return

    async with task_lock("discussion_page", f"{discussion_id}:{page}") as got:
        if not got:
            log.info("crawl_discussion.skip_locked", discussion_id=discussion_id, page=page)
            await _release_chain(
                discussion_id,
                claimed_token,
                suppress_legacy=False,
            )
            return
        try:
            finished = await _crawl_page_inner(
                discussion_id,
                page=page,
                trigger=trigger,
                enqueue_remaining=enqueue_remaining,
                chain_token=claimed_token,
            )
        except BaseException:
            # 网络错误交给 actor 重试；先释放链，重试消息才能重新取得所有权。
            await _release_chain(
                discussion_id,
                claimed_token,
                suppress_legacy=False,
            )
            raise
        if finished:
            await _release_chain(
                discussion_id,
                claimed_token,
                suppress_legacy=True,
            )


async def _crawl_page_inner(
    discussion_id: int,
    *,
    page: int,
    trigger: str,
    enqueue_remaining: bool,
    chain_token: str,
) -> bool:
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
        data = _discussion_data(result.data)
        post, replies, rows = _discussion_fields(data)
        rows = [
            row
            for row in rows
            if str(row.get("content") or "").strip()
        ]

        count_candidates = [
            value
            for value in (
                _non_negative_int(replies.get("count")),
                _non_negative_int(post.get("replyCount")),
            )
            if value is not None
        ]
        reply_count = max(count_candidates, default=0)
        raw_result = replies.get("result")
        result_count = len(raw_result) if isinstance(raw_result, (list, dict)) else 0
        per_page = max(_non_negative_int(replies.get("perPage")) or 0, result_count, 1)
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

            stored_reply_count = int(
                await session.scalar(
                    select(func.count(DiscussionReply.reply_id))
                    .join(
                        DiscussionReplyVersion,
                        DiscussionReplyVersion.id == DiscussionReply.current_version_id,
                    )
                    .where(
                        DiscussionReply.discussion_id == discussion_id,
                        DiscussionReplyVersion.content_md != "",
                        func.length(func.trim(DiscussionReplyVersion.content_md)) > 0,
                    )
                )
                or 0
            )
            reply_count = max(reply_count, stored_reply_count)
            total_pages = max(1, math.ceil(reply_count / per_page))
            page_out_of_range = page > total_pages

            now = utcnow()
            discussion.observed_reply_count = reply_count
            discussion.last_per_page = per_page
            discussion.last_crawled_at = now
            discussion.auto_crawl_paused = False
            discussion.auto_crawl_paused_at = None
            discussion.last_crawl_status = "ok"
            # 归档进度必须逐页更新，否则入口发现会一直认为大型讨论尚未开始，
            # 在旧活动标记过期后反复创建新的分页链。
            discussion.archived_reply_count = stored_reply_count
            if page == total_pages:
                discussion.last_crawled_page = total_pages
            elif not page_out_of_range:
                discussion.last_crawled_page = max(discussion.last_crawled_page, page)
            await session.commit()

        has_next_page = False
        if enqueue_remaining and page_out_of_range:
            _enqueue_next_page(
                discussion_id,
                page=max(1, total_pages - 1),
                trigger=trigger,
                chain_token=chain_token,
            )
            has_next_page = True
        elif enqueue_remaining and page < total_pages:
            _enqueue_next_page(
                discussion_id,
                page=page + 1,
                trigger=trigger,
                chain_token=chain_token,
            )
            has_next_page = True
        if has_next_page:
            await _renew_chain(discussion_id, chain_token)

        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=int((_t.monotonic() - started) * 1000),
        )
        return not has_next_page
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
        return True
    except Exception as exc:
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(exc),
            duration_ms=int((_t.monotonic() - started) * 1000),
        )
        log.error("crawl_discussion.failed", discussion_id=discussion_id, page=page, error=str(exc))
        raise


def _enqueue_next_page(
    discussion_id: int,
    *,
    page: int,
    trigger: str,
    chain_token: str,
) -> None:
    from app.tasks.actors.crawl import crawl_discussion, crawl_discussion_bg

    manual_batch = trigger.startswith("manual")
    target = crawl_discussion if manual_batch else crawl_discussion_bg
    child_trigger = "manual_followup" if manual_batch else trigger
    target.send(discussion_id, page, child_trigger, True, chain_token)
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
