"""定时调度器（APScheduler）。

单独的进程运行：python -m app.scheduler
- 题目分层扫描（按难度）
- 犇犇分层轮询（按用户最近活跃度）
- 入口页发现
- Cookie 账号心跳自检

这里只负责**派发 Dramatiq 任务**，不直接爬。
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, func, or_, select

from app.core.db import db_session
from app.core.logging import get_logger, setup_logging
from app.core.locks import DistributedLock
from app.core.redis_client import get_redis
from app.models._common import utcnow
from app.models.luogu_content import Problem
from app.models.luogu_user import LuoguUser

log = get_logger(__name__)


# ============================================================
# 定时任务定义
# ============================================================

async def job_discover_discuss() -> None:
    """每 5 分钟扫 /discuss。"""
    from app.tasks.actors.crawl import discover_from_discuss
    discover_from_discuss.send("scheduled")


async def job_discover_article() -> None:
    """每 10 分钟扫 /article。"""
    from app.tasks.actors.crawl import discover_from_article_list
    discover_from_article_list.send("scheduled")


async def job_crawl_judgement() -> None:
    """每小时拉一次陶片。"""
    from app.tasks.actors.crawl import crawl_judgement
    crawl_judgement.send("scheduled")


async def job_discover_contests() -> None:
    """每小时扫描比赛列表第一页，登记新比赛并归档刚结束的比赛。"""
    from app.tasks.actors.contest import discover_contests

    discover_contests.send()


async def job_probe_contest_official() -> None:
    """每小时检查仍在等待正式等级分的比赛。"""
    from app.models.contest import Contest, ContestArchiveStatus
    from app.tasks.actors.contest import probe_contest_official

    async with db_session() as session:
        contest_ids = list(
            (
                await session.execute(
                    select(Contest.id).where(
                        Contest.status == ContestArchiveStatus.predicted,
                        Contest.rated_type > 0,
                        Contest.elo_done.is_(False),
                    )
                )
            ).scalars().all()
        )
    for index, contest_id in enumerate(contest_ids):
        probe_contest_official.send_with_options(args=(contest_id,), delay=index * 1_000)


async def job_feed_tiered_polling() -> None:
    """犇犇分层轮询：根据 last_active_feed_at 决定哪些用户该爬。

    分层规则（3.md 七.2）：
      ≤ 3h  每 10 min
      3h~1d 每 1h
      1d~2d 每 2~3h（统一 2.5h）
      2d~7d 每 1d
      >7d   不轮询
    """
    from app.tasks.actors.crawl import crawl_user_feeds
    now = utcnow()
    # 计算各桶的"上次犇犇爬取时间应早于"阈值。
    async with db_session() as session:
        # S 桶：最近 3h 发过犇犇 & 上次爬虫 > 10 min 前
        q = (
            select(LuoguUser.uid)
            .where(
                LuoguUser.last_active_feed_at.is_not(None),
                LuoguUser.last_active_feed_at >= now - timedelta(hours=3),
                or_(
                    LuoguUser.last_feed_crawled_at < now - timedelta(minutes=10),
                    LuoguUser.last_feed_crawled_at.is_(None),
                ),
            )
            .limit(500)
        )
        s_bucket = [row[0] for row in (await session.execute(q)).all()]

        # A 桶：3h~1d，间隔 1h
        q = (
            select(LuoguUser.uid)
            .where(
                LuoguUser.last_active_feed_at < now - timedelta(hours=3),
                LuoguUser.last_active_feed_at >= now - timedelta(days=1),
                or_(
                    LuoguUser.last_feed_crawled_at < now - timedelta(hours=1),
                    LuoguUser.last_feed_crawled_at.is_(None),
                ),
            )
            .limit(500)
        )
        a_bucket = [row[0] for row in (await session.execute(q)).all()]

        # B 桶：1d~2d，间隔 2.5h
        q = (
            select(LuoguUser.uid)
            .where(
                LuoguUser.last_active_feed_at < now - timedelta(days=1),
                LuoguUser.last_active_feed_at >= now - timedelta(days=2),
                or_(
                    LuoguUser.last_feed_crawled_at < now - timedelta(hours=2, minutes=30),
                    LuoguUser.last_feed_crawled_at.is_(None),
                ),
            )
            .limit(500)
        )
        b_bucket = [row[0] for row in (await session.execute(q)).all()]

        # C 桶：2d~7d，间隔 1d
        q = (
            select(LuoguUser.uid)
            .where(
                LuoguUser.last_active_feed_at < now - timedelta(days=2),
                LuoguUser.last_active_feed_at >= now - timedelta(days=7),
                or_(
                    LuoguUser.last_feed_crawled_at < now - timedelta(days=1),
                    LuoguUser.last_feed_crawled_at.is_(None),
                ),
            )
            .limit(500)
        )
        c_bucket = [row[0] for row in (await session.execute(q)).all()]

    redis = get_redis()
    lock = DistributedLock(redis)
    total = 0
    deduped = 0
    for uid in s_bucket + a_bucket + b_bucket + c_bucket:
        dedup_key = f"scheduler:feed:queued:{uid}"
        token = secrets.token_urlsafe(18)
        # 成功任务会主动释放；失败/丢失消息最多阻塞半小时，覆盖重试窗口即可。
        queued = await redis.set(dedup_key, token, nx=True, ex=30 * 60)
        if not queued:
            deduped += 1
            continue
        try:
            crawl_user_feeds.send(uid, 1, "scheduled", token)
            total += 1
        except Exception:
            await lock.release(dedup_key, token)
            raise
    log.info(
        "feed_polling.enqueued",
        s=len(s_bucket),
        a=len(a_bucket),
        b=len(b_bucket),
        c=len(c_bucket),
        total=total,
        deduped=deduped,
    )


async def job_problem_tier_hourly() -> None:
    """tier1（入门 / 普及-）：每小时派一次"距上次检查 ≥ 1h"的题。

    每小时的目标周期是 1h，所以查 last_solution_check_at < now-1h（含 NULL）的题。
    只轮询当前仍标记为开放的题；一旦检测到关闭，写回 False 后退出自动观察池。
    11s/题错峰，cn 节点 0.1 req/s 是上限。
    """
    from app.tasks.actors.crawl import crawl_problem_solution
    now = utcnow()

    async with db_session() as session:
        q = (
            select(Problem.pid)
            .where(
                Problem.solution_open.is_(True),
                Problem.difficulty.in_(["入门", "普及-"]),
                or_(
                    Problem.last_solution_check_at < now - timedelta(hours=1),
                    Problem.last_solution_check_at.is_(None),
                ),
            )
            .order_by(
                Problem.last_solution_check_at.is_not(None),
                Problem.last_solution_check_at.asc(),
            )
        )
        pids = [r[0] for r in (await session.execute(q)).all()]

    for i, pid in enumerate(pids):
        crawl_problem_solution.send_with_options(
            args=(pid, "scheduled"), delay=i * 11_000,
        )
    log.info("problem_polling.tier_hourly", count=len(pids))


async def job_problem_tier_daily() -> None:
    """tier2（普及）：每天派一次"距上次检查 ≥ 24h"的题。"""
    from app.tasks.actors.crawl import crawl_problem_solution
    now = utcnow()

    async with db_session() as session:
        q = (
            select(Problem.pid)
            .where(
                Problem.solution_open.is_(True),
                Problem.difficulty.in_(["普及", "普及/提高-"]),
                or_(
                    Problem.last_solution_check_at < now - timedelta(hours=24),
                    Problem.last_solution_check_at.is_(None),
                ),
            )
            .order_by(
                Problem.last_solution_check_at.is_not(None),
                Problem.last_solution_check_at.asc(),
            )
        )
        pids = [r[0] for r in (await session.execute(q)).all()]

    for i, pid in enumerate(pids):
        crawl_problem_solution.send_with_options(
            args=(pid, "scheduled"), delay=i * 11_000,
        )
    log.info("problem_polling.tier_daily", count=len(pids))


async def job_problem_tier_weekly() -> None:
    """tier3（其他档）：每天派 1/7 的"距上次检查 ≥ 7d"的题，让全周均匀分摊。

    覆盖：普及+/提高-、提高、提高+/省选-、省选/NOI-、NOI/NOI+/CTS、暂无评定。
    只轮询当前仍标记为开放的题；关闭后不再自动复查。

    避免周一一次性把全档 1000+ 道题全派进队列堵住其他用户操作。
    取最旧的 ceil(N/7) 条，每天派一次，7 天正好把全档转完一轮。
    """
    import math
    from app.tasks.actors.crawl import crawl_problem_solution
    now = utcnow()

    other_diffs = [
        "普及+/提高-", "普及+/提高", "提高", "提高+/省选-", "省选/NOI-", "NOI/NOI+/CTS", "NOI/NOI+/CTSC", "unknown_8", "暂无评定",
    ]
    async with db_session() as session:
        # 总数（用于今日配额计算）
        total_q = (
            select(func.count(Problem.pid))
            .where(
                Problem.solution_open.is_(True),
                or_(
                    Problem.difficulty.in_(other_diffs),
                    Problem.difficulty.is_(None),
                ),
            )
        )
        total = (await session.execute(total_q)).scalar_one()
        # 今日配额：覆盖全档 7 天，多 1 题保证收敛
        daily_quota = max(1, math.ceil(total / 7))

        q = (
            select(Problem.pid)
            .where(
                Problem.solution_open.is_(True),
                or_(
                    Problem.difficulty.in_(other_diffs),
                    Problem.difficulty.is_(None),
                ),
                or_(
                    Problem.last_solution_check_at < now - timedelta(days=7),
                    Problem.last_solution_check_at.is_(None),
                ),
            )
            .order_by(
                Problem.last_solution_check_at.is_not(None),
                Problem.last_solution_check_at.asc(),
            )
            .limit(daily_quota)
        )
        pids = [r[0] for r in (await session.execute(q)).all()]

    for i, pid in enumerate(pids):
        crawl_problem_solution.send_with_options(
            args=(pid, "scheduled"), delay=i * 11_000,
        )
    log.info(
        "problem_polling.tier_weekly", count=len(pids),
        total_in_tier=total, daily_quota=daily_quota,
    )


async def job_problem_list_scan() -> None:
    """每天凌晨扫前 20 页题目列表，发现新题。

    新题进 problems 表后，list 页 cascade 会自动派一次 solution 检测（去重 30min）。
    """
    from app.tasks.actors.crawl import crawl_problem_list_page
    for page in range(1, 21):
        # 每页错峰 11s，让 cn 节点不被一口气怼 20 个 list 请求
        crawl_problem_list_page.send_with_options(
            args=(page, "scheduled"),
            delay=(page - 1) * 11_000,
        )


# ============================================================
# 启动入口
# ============================================================

def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    # 稍微错开分钟数，避免所有任务同时触发
    sched.add_job(job_discover_discuss, "interval", minutes=5, id="discover_discuss")
    sched.add_job(job_discover_article, "interval", minutes=10, id="discover_article")
    sched.add_job(job_crawl_judgement, "interval", hours=1, id="crawl_judgement")
    sched.add_job(job_discover_contests, "interval", hours=1, id="discover_contests")
    sched.add_job(
        job_probe_contest_official,
        "interval",
        hours=1,
        id="probe_contest_official",
    )
    sched.add_job(job_feed_tiered_polling, "interval", minutes=10, id="feed_polling")
    sched.add_job(job_problem_tier_hourly, "interval", hours=1, id="problem_tier_hourly")
    # tier2 每天凌晨 02:17 开始
    sched.add_job(job_problem_tier_daily, "cron", hour=2, minute=17, id="problem_tier_daily")
    # tier3 每天 02:33 派 1/7 配额，7 天滚完一轮
    sched.add_job(job_problem_tier_weekly, "cron", hour=2, minute=33, id="problem_tier_weekly")
    # 列表页发现新题，凌晨 02:13
    sched.add_job(job_problem_list_scan, "cron", hour=2, minute=13, id="problem_list_scan")
    return sched


async def main() -> None:
    setup_logging()
    sched = build_scheduler()
    sched.start()
    log.info("scheduler.started", jobs=[j.id for j in sched.get_jobs()])
    # 常驻
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
