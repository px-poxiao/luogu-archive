"""爬虫队列任务定义。

队列约定：
- crawler.hi：用户正在等待的任务。
- crawler.mid：发现、过期刷新和级联等普通后台任务。
- crawler.low：题库同步与题解状态任务。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.exceptions import (
    CrawlerAccountInvalid,
    CrawlerNotFound,
)
from app.core.locks import DistributedLock
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import crawler_task_cooldown
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.article import crawl_one as _crawl_article_one
from app.crawler.sources.discovery import (
    from_article_list as _discover_from_article_list,
)
from app.crawler.sources.discovery import (
    from_discuss as _discover_from_discuss,
)
from app.crawler.sources.discussion import crawl_page as _crawl_discussion_page
from app.crawler.sources.feed import crawl_user_page as _crawl_feed_user_page
from app.crawler.sources.judgement import crawl_all as _crawl_judgement_all
from app.crawler.sources.paste import crawl_one as _crawl_paste_one
from app.crawler.sources.problem import (
    sync_problem_catalog as _sync_problem_catalog,
)
from app.crawler.sources.problem import (
    crawl_solution_state as _crawl_problem_solution_state,
)
from app.crawler.sources.user import crawl_one as _crawl_user_one
from app.tasks.asyncio_runner import run_async
from app.tasks.broker import (
    ANON_CN,
    ANON_COM,
    AUTH_CN,
    AUTH_COM,
    NO_RESOURCES,
    QUEUE_CRAWL_HI,
    QUEUE_CRAWL_LOW,
    QUEUE_CRAWL_MID,
    TaskResources,
    actor,
)
from app.tasks.problem_queue import release_problem_job
from app.services.takedown_probe import run_takedown_probe

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
    """执行任务；资源临时不可用时交给新队列原地重试，不再生成重复消息。"""
    del actor_name, args
    run_async(awaitable)
    return True


def _manual_user_resources(
    args: tuple,
    _kwargs: dict,
) -> TaskResources:
    """手动保存用户分两阶段：先匿名主页，再使用账号抓第一页犇犇。"""

    profile_done = bool(args[1]) if len(args) > 1 else False
    return AUTH_COM if profile_done else ANON_COM


def _takedown_probe_resources(args: tuple, _kwargs: dict) -> TaskResources:
    """犇犇探测需要账号，其余探测只使用匿名国际站资源。"""
    return AUTH_COM if len(args) > 1 and args[1] == "feed" else ANON_COM


@actor(queue_name=QUEUE_CRAWL_HI, resources=_takedown_probe_resources, max_retries=0)
def probe_takedown_target(token: str, target_type: str) -> None:
    """删除申请探测走现有高优先级队列，不占用 API 进程。"""
    log.info("actor.probe_takedown_target", token=token, target_type=target_type)
    _run_or_defer(
        "probe_takedown_target",
        (token, target_type),
        _run_domain_task(
            lambda: run_takedown_probe(token),
            kind=NodeKind.AUTHED if target_type == "feed" else NodeKind.ANON,
        ),
    )


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
        # 失败时保留短期去重标记，覆盖队列重试窗口，避免调度器重复入队。
        raise
    else:
        if dedup_token and not high_priority:
            await DistributedLock(get_redis()).release(
                _scheduled_feed_key(uid),
                dedup_token,
            )


@actor(queue_name=QUEUE_CRAWL_HI, resources=ANON_COM, **_RETRY)
def crawl_article(article_id: str, trigger: str = "manual") -> None:
    """用户触发的文章抓取：手动保存或首次访问未收录文章。"""
    log.info("actor.crawl_article", article_id=article_id, trigger=trigger)
    _run_or_defer(
        "crawl_article",
        (article_id, trigger),
        _run_domain_task(lambda: _crawl_article_one(article_id, trigger=trigger)),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=ANON_COM, **_RETRY)
def crawl_article_bg(article_id: str, trigger: str = "passive") -> None:
    """后台文章抓取：过期刷新、发现或级联。"""
    log.info("actor.crawl_article_bg", article_id=article_id, trigger=trigger)
    _run_or_defer(
        "crawl_article_bg",
        (article_id, trigger),
        _run_domain_task(lambda: _crawl_article_one(article_id, trigger=trigger)),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=ANON_COM, **_RETRY)
def crawl_paste(paste_id: str, trigger: str = "manual") -> None:
    """用户触发的剪贴板抓取：手动保存或首次访问未收录内容。"""
    log.info("actor.crawl_paste", paste_id=paste_id, trigger=trigger)
    _run_or_defer(
        "crawl_paste",
        (paste_id, trigger),
        _run_domain_task(lambda: _crawl_paste_one(paste_id, trigger=trigger)),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=ANON_COM, **_RETRY)
def crawl_paste_bg(paste_id: str, trigger: str = "passive") -> None:
    """后台剪贴板抓取：过期刷新或级联。"""
    log.info("actor.crawl_paste_bg", paste_id=paste_id, trigger=trigger)
    _run_or_defer(
        "crawl_paste_bg",
        (paste_id, trigger),
        _run_domain_task(lambda: _crawl_paste_one(paste_id, trigger=trigger)),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=AUTH_CN, **_RETRY)
def crawl_discussion(
    discussion_id: int,
    page: int = 0,
    trigger: str = "manual",
    enqueue_remaining: bool = True,
) -> None:
    """用户触发的讨论保存；每个 actor 仅请求一页。"""
    log.info("actor.crawl_discussion", discussion_id=discussion_id, page=page, trigger=trigger)
    _run_or_defer(
        "crawl_discussion",
        (discussion_id, page, trigger, enqueue_remaining),
        _crawl_discussion_page(
            discussion_id,
            page=page,
            trigger=trigger,
            enqueue_remaining=enqueue_remaining,
        ),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=AUTH_CN, **_RETRY)
def crawl_discussion_bg(
    discussion_id: int,
    page: int = 0,
    trigger: str = "discovery",
    enqueue_remaining: bool = True,
) -> None:
    """首页发现触发的讨论增量归档；每个 actor 仅请求一页。"""
    log.info("actor.crawl_discussion_bg", discussion_id=discussion_id, page=page, trigger=trigger)
    _run_or_defer(
        "crawl_discussion_bg",
        (discussion_id, page, trigger, enqueue_remaining),
        _crawl_discussion_page(
            discussion_id,
            page=page,
            trigger=trigger,
            enqueue_remaining=enqueue_remaining,
        ),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=ANON_COM, **_RETRY)
def crawl_user(uid: int, trigger: str = "manual") -> None:
    """用户触发的主页抓取，用于首次访问未收录用户。"""
    log.info("actor.crawl_user", uid=uid, trigger=trigger)
    _run_or_defer(
        "crawl_user",
        (uid, trigger),
        _run_domain_task(lambda: _crawl_user_one(uid, trigger=trigger)),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=_manual_user_resources, **_RETRY)
def crawl_user_manual(uid: int, profile_done: bool = False) -> None:
    """手动刷新用户：先抓主页，再以高优先级抓犇犇第一页。"""
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
        # 第二阶段依赖账号，重新入队后由调度器原子选择最早可用账号。
        crawl_user_manual.send(uid, True)
        return
    _run_or_defer(
        "crawl_user_manual",
        (uid, True),
        _run_feed_task(uid, 1, "manual_save", None, high_priority=True),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=ANON_COM, **_RETRY)
def crawl_user_bg(uid: int, trigger: str = "passive") -> None:
    """后台用户主页抓取：过期刷新、发现或级联。"""
    log.info("actor.crawl_user_bg", uid=uid, trigger=trigger)
    _run_or_defer(
        "crawl_user_bg",
        (uid, trigger),
        _run_domain_task(lambda: _crawl_user_one(uid, trigger=trigger)),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=AUTH_COM, **_RETRY)
def crawl_user_feeds(
    uid: int,
    page: int = 1,
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    """定时、被动或级联触发的犇犇抓取。"""
    log.info("actor.crawl_user_feeds", uid=uid, page=page, trigger=trigger)
    _run_or_defer(
        "crawl_user_feeds",
        (uid, page, trigger, dedup_token),
        _run_feed_task(uid, page, trigger, dedup_token),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=AUTH_COM, **_RETRY)
def crawl_user_feeds_hi(uid: int, page: int = 1, trigger: str = "manual") -> None:
    """手动触发的单页犇犇抓取。"""
    log.info("actor.crawl_user_feeds_hi", uid=uid, page=page, trigger=trigger)
    _run_or_defer(
        "crawl_user_feeds_hi",
        (uid, page, trigger),
        _run_feed_task(uid, page, trigger, None, high_priority=True),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=ANON_CN, **_RETRY)
def crawl_judgement(trigger: str = "scheduled") -> None:
    """定时抓取全站陶片放逐。"""
    log.info("actor.crawl_judgement", trigger=trigger)
    _run_or_defer(
        "crawl_judgement",
        (trigger,),
        _run_domain_task(lambda: _crawl_judgement_all(trigger=trigger), cn=True),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=ANON_CN, **_RETRY)
def crawl_judgement_hi(trigger: str = "manual") -> None:
    """手动触发的陶片放逐抓取。"""
    log.info("actor.crawl_judgement_hi", trigger=trigger)
    _run_or_defer(
        "crawl_judgement_hi",
        (trigger,),
        _run_domain_task(lambda: _crawl_judgement_all(trigger=trigger), cn=True),
    )


@actor(queue_name=QUEUE_CRAWL_LOW, resources=NO_RESOURCES, **_RETRY)
def sync_problem_catalog(
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    """从洛谷 CDN 的官方题库包全量同步题目元数据。"""
    log.info("actor.sync_problem_catalog", trigger=trigger)
    try:
        completed = _run_or_defer(
            "sync_problem_catalog",
            (trigger, dedup_token),
            _sync_problem_catalog(trigger=trigger),
        )
    except BaseException:
        run_async(release_problem_job("catalog", "official", dedup_token))
        raise
    if completed:
        run_async(release_problem_job("catalog", "official", dedup_token))


@actor(queue_name=QUEUE_CRAWL_LOW, resources=NO_RESOURCES, max_retries=0)
def crawl_problem_list_page(
    page: int,
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    """消费升级前残留的旧分页消息，不再访问题目列表。"""
    log.info("actor.crawl_problem_list_page_ignored", page=page, trigger=trigger)
    run_async(release_problem_job("list", page, dedup_token))


@actor(queue_name=QUEUE_CRAWL_LOW, resources=NO_RESOURCES, max_retries=0)
def crawl_problem_list_page_hi(page: int, trigger: str = "manual") -> None:
    """消费升级前残留的旧高优先级分页消息，不再访问题目列表。"""
    log.info("actor.crawl_problem_list_page_hi_ignored", page=page, trigger=trigger)


@actor(queue_name=QUEUE_CRAWL_LOW, resources=ANON_CN, **_RETRY)
def crawl_problem_solution(
    pid: str,
    trigger: str = "scheduled",
    dedup_token: str | None = None,
) -> None:
    """题解开放状态检查始终使用低优先级。"""
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


@actor(queue_name=QUEUE_CRAWL_LOW, resources=ANON_CN, **_RETRY)
def crawl_problem_solution_hi(pid: str, trigger: str = "manual") -> None:
    """兼容旧消息；题目检查现在统一使用低优先级。"""
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


@actor(queue_name=QUEUE_CRAWL_MID, resources=ANON_CN, **_RETRY)
def discover_from_discuss(trigger: str = "scheduled") -> None:
    log.info("actor.discover_from_discuss", trigger=trigger)
    _run_or_defer(
        "discover_from_discuss",
        (trigger,),
        _run_domain_task(lambda: _discover_from_discuss(trigger=trigger), cn=True),
    )


@actor(queue_name=QUEUE_CRAWL_HI, resources=ANON_CN, **_RETRY)
def discover_from_discuss_hi(trigger: str = "manual") -> None:
    """用户主动更新讨论区目录，只把首页发现请求放入高优先级。"""
    log.info("actor.discover_from_discuss_hi", trigger=trigger)
    _run_or_defer(
        "discover_from_discuss_hi",
        (trigger,),
        _run_domain_task(lambda: _discover_from_discuss(trigger=trigger), cn=True),
    )


@actor(queue_name=QUEUE_CRAWL_MID, resources=ANON_COM, **_RETRY)
def discover_from_article_list(trigger: str = "scheduled") -> None:
    log.info("actor.discover_from_article_list", trigger=trigger)
    _run_or_defer(
        "discover_from_article_list",
        (trigger,),
        _run_domain_task(lambda: _discover_from_article_list(trigger=trigger)),
    )
