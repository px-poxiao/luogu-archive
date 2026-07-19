"""比赛归档与等级分任务 actor。"""
from __future__ import annotations

from datetime import timedelta, timezone

import dramatiq

from app.core.db import db_session
from app.core.logging import get_logger
from app.models._common import utcnow
from app.models.contest import Contest
from app.models.luogu_user import LuoguUser
from app.tasks.asyncio_runner import run_async
from app.tasks.broker import QUEUE_CRAWL_MID, get_broker


get_broker()
log = get_logger(__name__)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=2, min_backoff=10_000)
def discover_contests() -> None:
    """扫描洛谷比赛列表第一页。"""

    from app.services.contest_archive import discover_first_page

    run_async(discover_first_page())


async def _archive(contest_id: int, trigger: str, force: bool) -> None:
    from app.services.contest_archive import archive_one, mark_failed

    try:
        await archive_one(contest_id, force=force)
    except Exception as exc:
        await mark_failed(contest_id, exc)
        log.error("contest.archive_failed", contest_id=contest_id, trigger=trigger, error=str(exc))
        raise


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=2, min_backoff=10_000)
def archive_contest(contest_id: int, trigger: str = "scheduled", force: bool = False) -> None:
    """归档一场已经结束的比赛。"""

    run_async(_archive(contest_id, trigger, force))


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
            await crawl_one(
                uid,
                trigger="internal",
                enqueue_feed=False,
                enqueue_content=False,
            )
            profile_source = "fresh"
    except Exception as exc:
        # 产品约定每个阶段只请求一次；失败立即使用档案馆缓存，不让 Dramatiq 重试。
        log.warning(
            "contest.user_refresh_failed",
            contest_id=contest_id,
            uid=uid,
            phase=phase,
            error=str(exc),
        )
    finally:
        # 正式阶段同样需要赛前快照，用于没有参加评定的用户显示 0 变化。
        await snapshot_user(contest_id, uid, profile_source=profile_source)
        await refresh_finished(contest_id, phase)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def refresh_contest_user(contest_id: int, uid: int, phase: str) -> None:
    """按严格域名限速刷新一名参赛者。"""

    run_async(_refresh_user(contest_id, uid, phase))


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
    from app.crawler.sources.user import crawl_one
    from app.services.contest_archive import (
        begin_official_refresh,
        detect_official_from_user,
        official_probe_uids,
    )

    uids = await official_probe_uids(contest_id)
    detected = False
    for uid in uids:
        try:
            await crawl_one(
                uid,
                trigger="internal",
                enqueue_feed=False,
                enqueue_content=False,
            )
        except Exception as exc:
            log.warning(
                "contest.official_probe_user_failed",
                contest_id=contest_id,
                uid=uid,
                error=str(exc),
            )
            continue
        if await detect_official_from_user(contest_id, uid):
            detected = True
            break

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest:
            contest.last_official_check_at = utcnow()
            await session.commit()
    if detected:
        await begin_official_refresh(contest_id)


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, max_retries=0)
def probe_contest_official(contest_id: int) -> None:
    """每小时只检查阈值内前 20 名是否出现正式记录。"""

    run_async(_probe_official(contest_id))
