"""比赛归档与等级分任务 actor。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta, timezone
from typing import TypeVar

import dramatiq

from app.core.db import db_session
from app.core.exceptions import CrawlerCooldownDeferred
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import crawler_task_cooldown
from app.crawler.nodes import NodeKind, get_default_node
from app.models._common import utcnow
from app.models.contest import Contest
from app.models.luogu_user import LuoguUser
from app.tasks.asyncio_runner import run_async
from app.tasks.broker import QUEUE_CRAWL_MID, get_broker


get_broker()
log = get_logger(__name__)
T = TypeVar("T")


async def _run_cn_task(factory: Callable[[], Awaitable[T]]) -> T:
    node = get_default_node(NodeKind.ANON, cn=True)
    async with crawler_task_cooldown(
        node,
        get_redis(),
        defer_when_busy=True,
    ):
        return await factory()


async def _run_com_task(factory: Callable[[], Awaitable[T]]) -> T:
    node = get_default_node(NodeKind.ANON)
    async with crawler_task_cooldown(
        node,
        get_redis(),
        defer_when_busy=True,
    ):
        return await factory()


def _defer(actor_name: str, args: tuple, exc: CrawlerCooldownDeferred) -> None:
    delay_ms = exc.retry_after_ms + 100
    get_broker().get_actor(actor_name).send_with_options(args=args, delay=delay_ms)
    log.info("actor.cooldown_deferred", actor=actor_name, delay_ms=delay_ms)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=2, min_backoff=10_000)
def discover_contests() -> None:
    """扫描洛谷比赛列表第一页。"""

    from app.services.contest_archive import discover_first_page

    try:
        run_async(_run_cn_task(discover_first_page))
    except CrawlerCooldownDeferred as exc:
        _defer("discover_contests", (), exc)


async def _archive(contest_id: int, trigger: str, force: bool) -> None:
    from app.crawler.sources.base import task_lock
    from app.services.contest_archive import archive_one, mark_failed

    async with task_lock("contest_archive", str(contest_id), ttl_sec=6 * 3600) as got:
        if not got:
            log.info("contest.archive_already_running", contest_id=contest_id, trigger=trigger)
            return
        try:
            await _run_cn_task(
                lambda: archive_one(contest_id, trigger=trigger, force=force)
            )
        except CrawlerCooldownDeferred as exc:
            _defer("archive_contest", (contest_id, trigger, force), exc)
        except Exception as exc:
            await mark_failed(contest_id, exc)
            log.error(
                "contest.archive_failed",
                contest_id=contest_id,
                trigger=trigger,
                error=str(exc),
            )
            raise


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=2, min_backoff=10_000)
def archive_contest(contest_id: int, trigger: str = "scheduled", force: bool = False) -> None:
    """抓比赛详情并启动分页榜单流水线。"""

    run_async(_archive(contest_id, trigger, force))


async def _archive_scoreboard_page(
    contest_id: int,
    page: int,
    trigger: str,
    run_id: str,
) -> None:
    from app.crawler.sources.base import task_lock
    from app.services.contest_archive import archive_scoreboard_page, mark_failed

    async with task_lock(
        "contest_scoreboard_page",
        f"{contest_id}:{run_id}:{page}",
        ttl_sec=30 * 60,
    ) as got:
        if not got:
            return
        try:
            await _run_cn_task(
                lambda: archive_scoreboard_page(
                    contest_id,
                    page,
                    trigger=trigger,
                    run_id=run_id,
                )
            )
        except CrawlerCooldownDeferred as exc:
            _defer(
                "archive_contest_scoreboard_page",
                (contest_id, page, trigger, run_id),
                exc,
            )
        except Exception as exc:
            await mark_failed(contest_id, exc)
            log.error(
                "contest.scoreboard_page_failed",
                contest_id=contest_id,
                page=page,
                trigger=trigger,
                error=str(exc),
            )
            raise


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def archive_contest_scoreboard_page(
    contest_id: int,
    page: int,
    trigger: str = "scheduled",
    run_id: str = "",
) -> None:
    """抓取并保存一页比赛榜单。"""

    run_async(_archive_scoreboard_page(contest_id, page, trigger, run_id))


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def finalize_contest_scoreboard(contest_id: int, run_id: str) -> None:
    """全部榜单页完成后统一汇总并派发用户主页任务。"""

    from app.services.contest_archive import finalize_scoreboard, mark_failed

    async def finalize() -> None:
        try:
            await finalize_scoreboard(contest_id, run_id)
        except Exception as exc:
            await mark_failed(contest_id, exc)
            raise

    run_async(finalize())


async def _refresh_user(contest_id: int, uid: int, phase: str) -> None:
    from app.crawler.sources.user import crawl_one
    from app.services.contest_archive import refresh_finished, snapshot_user

    profile_source = "cache"
    try:
        # 比赛任务只需要用户资料和 Elo，不级联抓犇犇、文章或剪贴板。
        async with db_session() as session:
            user = await session.get(LuoguUser, uid)
        last_crawled_at = user.last_crawled_at if user else None
        if last_crawled_at is not None and last_crawled_at.tzinfo is None:
            last_crawled_at = last_crawled_at.replace(tzinfo=timezone.utc)

        # 一天内已成功刷新过的主页直接复用，避免比赛批量任务重复访问洛谷。
        if last_crawled_at is not None and last_crawled_at >= utcnow() - timedelta(days=1):
            profile_source = "recent"
        else:
            # 比赛任务只需要用户资料和 Elo，不级联抓犇犇、文章或剪贴板。
            await _run_com_task(
                lambda: crawl_one(
                    uid,
                    trigger="internal",
                    enqueue_feed=False,
                    enqueue_content=False,
                )
            )
            profile_source = "fresh"
    except CrawlerCooldownDeferred:
        raise
    except Exception as exc:
        # 产品约定每个阶段只请求一次；失败立即使用档案馆缓存，不让 Dramatiq 重试。
        log.warning(
            "contest.user_refresh_failed",
            contest_id=contest_id,
            uid=uid,
            phase=phase,
            error=str(exc),
        )
    # 正式阶段同样需要赛前快照，用于没有参加评定的用户显示 0 变化。
    await snapshot_user(contest_id, uid, profile_source=profile_source)
    await refresh_finished(contest_id, uid, phase)


async def _run_refresh_user(contest_id: int, uid: int, phase: str) -> None:
    from app.services.contest_archive import refresh_user_pending

    if await refresh_user_pending(contest_id, uid, phase):
        await _refresh_user(contest_id, uid, phase)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def refresh_contest_user(contest_id: int, uid: int, phase: str) -> None:
    """刷新一名参赛者；一个 actor 至多请求一个用户主页。"""

    try:
        run_async(_run_refresh_user(contest_id, uid, phase))
    except CrawlerCooldownDeferred as exc:
        _defer("refresh_contest_user", (contest_id, uid, phase), exc)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=1)
def calculate_contest_prediction(contest_id: int) -> None:
    """所有赛前快照就绪后计算唯一一版预测。"""

    from app.services.contest_archive import calculate_prediction

    run_async(calculate_prediction(contest_id))


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=1)
def finalize_contest_official(contest_id: int) -> None:
    """最后一次用户刷新完成后保存正式结果。"""

    from app.services.contest_archive import finalize_official

    run_async(finalize_official(contest_id))


async def _probe_official(contest_id: int) -> None:
    from app.services.contest_archive import official_probe_uids

    uids = await official_probe_uids(contest_id)
    for uid in uids:
        probe_contest_official_user.send(contest_id, int(uid))


async def _probe_official_user(contest_id: int, uid: int) -> None:
    from app.crawler.sources.user import crawl_one
    from app.services.contest_archive import begin_official_refresh, detect_official_from_user

    try:
        await _run_com_task(
            lambda: crawl_one(
                uid,
                trigger="internal",
                enqueue_feed=False,
                enqueue_content=False,
            )
        )
    except CrawlerCooldownDeferred:
        raise
    except Exception as exc:
        log.warning(
            "contest.official_probe_user_failed",
            contest_id=contest_id,
            uid=uid,
            error=str(exc),
        )
        return

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest:
            contest.last_official_check_at = utcnow()
            await session.commit()
    if await detect_official_from_user(contest_id, uid):
        detected_key = f"contest:official_detected:{contest_id}"
        if not await get_redis().set(detected_key, "1", nx=True, ex=24 * 3600):
            return
        await begin_official_refresh(contest_id)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def probe_contest_official(contest_id: int) -> None:
    """派发阈值内前 20 名的单用户正式记录探测任务。"""

    run_async(_probe_official(contest_id))


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def probe_contest_official_user(contest_id: int, uid: int) -> None:
    """只刷新一名用户并检查目标比赛的正式等级分记录。"""

    try:
        run_async(_probe_official_user(contest_id, uid))
    except CrawlerCooldownDeferred as exc:
        _defer("probe_contest_official_user", (contest_id, uid), exc)
