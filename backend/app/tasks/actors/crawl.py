"""Crawler task actors.

Queue policy:
- crawler.hi: user-facing jobs that should complete quickly.
- crawler.mid: normal background jobs, discovery, stale refresh and cascades.
- crawler.low: all problem-list and problem-solution state jobs.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import dramatiq

from app.core.exceptions import (
    CrawlerAccountInvalid,
    CrawlerCooldownDeferred,
    CrawlerNotFound,
)
from app.core.logging import get_logger
from app.core.locks import DistributedLock
from app.core.redis_client import get_redis
from app.crawler.http import crawler_task_cooldown
from app.crawler.nodes import NodeKind, get_default_node
from app.tasks.asyncio_runner import run_async
from app.tasks.broker import (
    QUEUE_CRAWL_HI,
    QUEUE_CRAWL_LOW,
    QUEUE_CRAWL_MID,
    get_broker,
)
from app.tasks.problem_queue import release_problem_job

get_broker()

from app.crawler.sources.article import crawl_one as _crawl_article_one
from app.crawler.sources.discovery import (
    from_article_list as _discover_from_article_list,
    from_discuss as _discover_from_discuss,
)
from app.crawler.sources.feed import crawl_user_page as _crawl_feed_user_page
from app.crawler.sources.judgement import crawl_all as _crawl_judgement_all
from app.crawler.sources.paste import crawl_one as _crawl_paste_one
from app.crawler.sources.problem import (
    crawl_list_page as _crawl_problem_list_page,
    crawl_solution_state as _crawl_problem_solution_state,
)
from app.crawler.sources.user import crawl_one as _crawl_user_one

log = get_logger(__name__)

_RETRY = {
    "max_retries": 3,
    "min_backoff": 5_000,
    "max_backoff": 60_000,
    "throws": (CrawlerNotFound, CrawlerAccountInvalid),
}


async def _run_domain_task(
    factory: Callable[[], Awaitable[None]],
    *,
    cn: bool = False,
    kind: NodeKind = NodeKind.ANON,
    defer_when_busy: bool = True,
) -> None:
    """让域名冷却覆盖完整 actor，而不只覆盖 HTTP 响应阶段。"""
    node = get_default_node(kind, cn=cn)
    async with crawler_task_cooldown(
        node,
        get_redis(),
        defer_when_busy=defer_when_busy,
    ):
        await factory()


def _run_or_defer(actor_name: str, args: tuple, awaitable: Awaitable[None]) -> bool:
    """Run one actor, or requeue it without consuming a failure retry."""
    try:
        run_async(awaitable)
    except CrawlerCooldownDeferred as exc:
        delay_ms = exc.retry_after_ms + 100
        get_broker().get_actor(actor_name).send_with_options(args=args, delay=delay_ms)
        log.info(
            "actor.cooldown_deferred",
            actor=actor_name,
            delay_ms=delay_ms,
        )
        return False
    return True


def _scheduled_feed_key(uid: int) -> str:
    return f"scheduler:feed:queued:{uid}"


async def _run_feed_task(
    uid: int,
    page: int,
    trigger: str,
    dedup_token: str | None,
    *,
    high_priority: bool = False,
) -> None:
    try:
        await _run_domain_task(
            lambda: _crawl_feed_user_page(uid, page=page, trigger=trigger),
            kind=NodeKind.AUTHED,
        )
    except BaseException:
        # 失败时保留短期去重标记，覆盖 Dramatiq 重试窗口，避免调度器重复入队。
        raise
    else:
        if dedup_token and not high_priority:
            await DistributedLock(get_redis()).release(
                _scheduled_feed_key(uid),
                dedup_token,
            )


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_article(article_id: str, trigger: str = "manual") -> None:
    """User-facing article crawl: manual save or first unarchived visit."""
    log.info("actor.crawl_article", article_id=article_id, trigger=trigger)
    _run_or_defer(
        "crawl_article",
        (article_id, trigger),
        _run_domain_task(lambda: _crawl_article_one(article_id, trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_article_bg(article_id: str, trigger: str = "passive") -> None:
    """Background article crawl: stale refresh, discovery or cascade."""
    log.info("actor.crawl_article_bg", article_id=article_id, trigger=trigger)
    _run_or_defer(
        "crawl_article_bg",
        (article_id, trigger),
        _run_domain_task(lambda: _crawl_article_one(article_id, trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_paste(paste_id: str, trigger: str = "manual") -> None:
    """User-facing paste crawl: manual save or first unarchived visit."""
    log.info("actor.crawl_paste", paste_id=paste_id, trigger=trigger)
    _run_or_defer(
        "crawl_paste",
        (paste_id, trigger),
        _run_domain_task(lambda: _crawl_paste_one(paste_id, trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_paste_bg(paste_id: str, trigger: str = "passive") -> None:
    """Background paste crawl: stale refresh or cascade."""
    log.info("actor.crawl_paste_bg", paste_id=paste_id, trigger=trigger)
    _run_or_defer(
        "crawl_paste_bg",
        (paste_id, trigger),
        _run_domain_task(lambda: _crawl_paste_one(paste_id, trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_user(uid: int, trigger: str = "manual") -> None:
    """User-facing user profile crawl, for first unarchived visits."""
    log.info("actor.crawl_user", uid=uid, trigger=trigger)
    _run_or_defer(
        "crawl_user",
        (uid, trigger),
        _run_domain_task(lambda: _crawl_user_one(uid, trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_user_manual(uid: int, profile_done: bool = False) -> None:
    """Manual user refresh: profile plus feed page 1 in the same hi task."""
    log.info("actor.crawl_user_manual", uid=uid)
    # 两个阶段分别走完整冷却；第二阶段被延迟时不能重新爬一遍主页。
    if not profile_done:
        completed = _run_or_defer(
            "crawl_user_manual",
            (uid, False),
            _run_domain_task(
                lambda: _crawl_user_one(
                    uid,
                    trigger="manual",
                    enqueue_feed=False,
                    enqueue_content=True,
                )
            ),
        )
        if not completed:
            return
    _run_or_defer(
        "crawl_user_manual",
        (uid, True),
        _run_feed_task(uid, 1, "manual_save", None, high_priority=True),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_user_bg(uid: int, trigger: str = "passive") -> None:
    """Background user profile crawl: stale refresh, discovery or cascade."""
    log.info("actor.crawl_user_bg", uid=uid, trigger=trigger)
    _run_or_defer(
        "crawl_user_bg",
        (uid, trigger),
        _run_domain_task(lambda: _crawl_user_one(uid, trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_user_feeds(
    uid: int,
    page: int = 1,
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    """Scheduled, passive or cascaded feed crawl."""
    log.info("actor.crawl_user_feeds", uid=uid, page=page, trigger=trigger)
    _run_or_defer(
        "crawl_user_feeds",
        (uid, page, trigger, dedup_token),
        _run_feed_task(uid, page, trigger, dedup_token),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_user_feeds_hi(uid: int, page: int = 1, trigger: str = "manual") -> None:
    """Manual single-page feed crawl."""
    log.info("actor.crawl_user_feeds_hi", uid=uid, page=page, trigger=trigger)
    _run_or_defer(
        "crawl_user_feeds_hi",
        (uid, page, trigger),
        _run_feed_task(uid, page, trigger, None, high_priority=True),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_judgement(trigger: str = "scheduled") -> None:
    """Scheduled global judgement crawl."""
    log.info("actor.crawl_judgement", trigger=trigger)
    _run_or_defer(
        "crawl_judgement",
        (trigger,),
        _run_domain_task(lambda: _crawl_judgement_all(trigger=trigger), cn=True),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_judgement_hi(trigger: str = "manual") -> None:
    """Manual judgement crawl."""
    log.info("actor.crawl_judgement_hi", trigger=trigger)
    _run_or_defer(
        "crawl_judgement_hi",
        (trigger,),
        _run_domain_task(lambda: _crawl_judgement_all(trigger=trigger), cn=True),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def crawl_problem_list_page(
    page: int,
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    log.info("actor.crawl_problem_list_page", page=page, trigger=trigger)
    try:
        completed = _run_or_defer(
            "crawl_problem_list_page",
            (page, trigger, dedup_token),
            _run_domain_task(
                lambda: _crawl_problem_list_page(page, trigger=trigger),
                cn=True,
                defer_when_busy=False,
            ),
        )
    except (CrawlerNotFound, CrawlerAccountInvalid):
        run_async(release_problem_job("list", page, dedup_token))
        raise
    if completed:
        run_async(release_problem_job("list", page, dedup_token))


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def crawl_problem_list_page_hi(page: int, trigger: str = "manual") -> None:
    """Compatibility actor for old messages; problem list jobs now use low."""
    log.info("actor.crawl_problem_list_page_hi", page=page, trigger=trigger)
    _run_or_defer(
        "crawl_problem_list_page_hi",
        (page, trigger),
        _run_domain_task(
            lambda: _crawl_problem_list_page(page, trigger=trigger),
            cn=True,
            defer_when_busy=False,
        ),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def crawl_problem_solution(
    pid: str,
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    """Problem solution-state checks always use low."""
    log.info("actor.crawl_problem_solution", pid=pid, trigger=trigger)
    try:
        completed = _run_or_defer(
            "crawl_problem_solution",
            (pid, trigger, dedup_token),
            _run_domain_task(
                lambda: _crawl_problem_solution_state(pid, trigger=trigger),
                cn=True,
                defer_when_busy=False,
            ),
        )
    except (CrawlerNotFound, CrawlerAccountInvalid):
        run_async(release_problem_job("solution", pid.upper(), dedup_token))
        raise
    if completed:
        run_async(release_problem_job("solution", pid.upper(), dedup_token))


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def crawl_problem_solution_hi(pid: str, trigger: str = "manual") -> None:
    """Compatibility actor for old messages; problem checks now use low."""
    log.info("actor.crawl_problem_solution_hi", pid=pid, trigger=trigger)
    _run_or_defer(
        "crawl_problem_solution_hi",
        (pid, trigger),
        _run_domain_task(
            lambda: _crawl_problem_solution_state(pid, trigger=trigger),
            cn=True,
            defer_when_busy=False,
        ),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def discover_from_discuss(trigger: str = "scheduled") -> None:
    log.info("actor.discover_from_discuss", trigger=trigger)
    _run_or_defer(
        "discover_from_discuss",
        (trigger,),
        _run_domain_task(lambda: _discover_from_discuss(trigger=trigger)),
    )


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def discover_from_article_list(trigger: str = "scheduled") -> None:
    log.info("actor.discover_from_article_list", trigger=trigger)
    _run_or_defer(
        "discover_from_article_list",
        (trigger,),
        _run_domain_task(lambda: _discover_from_article_list(trigger=trigger)),
    )
