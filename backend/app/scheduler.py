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
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, or_, select

from app.core.db import db_session
from app.core.logging import get_logger, setup_logging
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
    # 计算各桶的"上次爬取时间应早于"阈值（用 last_crawled_at 近似）
    async with db_session() as session:
        # S 桶：最近 3h 发过犇犇 & 上次爬虫 > 10 min 前
        q = (
            select(LuoguUser.uid)
            .where(
                LuoguUser.last_active_feed_at.is_not(None),
                LuoguUser.last_active_feed_at >= now - timedelta(hours=3),
                or_(
                    LuoguUser.last_crawled_at < now - timedelta(minutes=10),
                    LuoguUser.last_crawled_at.is_(None),
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
                    LuoguUser.last_crawled_at < now - timedelta(hours=1),
                    LuoguUser.last_crawled_at.is_(None),
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
                    LuoguUser.last_crawled_at < now - timedelta(hours=2, minutes=30),
                    LuoguUser.last_crawled_at.is_(None),
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
                    LuoguUser.last_crawled_at < now - timedelta(days=1),
                    LuoguUser.last_crawled_at.is_(None),
                ),
            )
            .limit(500)
        )
        c_bucket = [row[0] for row in (await session.execute(q)).all()]

    total = 0
    for uid in s_bucket + a_bucket + b_bucket + c_bucket:
        crawl_user_feeds.send(uid, 1, "scheduled")
        total += 1
    log.info(
        "feed_polling.enqueued",
        s=len(s_bucket),
        a=len(a_bucket),
        b=len(b_bucket),
        c=len(c_bucket),
        total=total,
    )


async def job_problem_tiered_polling() -> None:
    """题目分层扫描（只扫 solution_open 为 true 的）。

    入门 / 普及- 每 2h，普及/普及+/提高+/省选- 每 12h，省选+ 每 3 天
    """
    from app.tasks.actors.crawl import crawl_problem_solution
    now = utcnow()

    async with db_session() as session:
        # 入门 / 普及-
        q = (
            select(Problem.pid)
            .where(
                Problem.solution_open.is_(True),
                Problem.difficulty.in_(["入门", "普及-"]),
                or_(
                    Problem.last_solution_check_at < now - timedelta(hours=2),
                    Problem.last_solution_check_at.is_(None),
                ),
            )
            .limit(500)
        )
        tier1 = [r[0] for r in (await session.execute(q)).all()]

        # 普及/普及+/提高+/省选-
        q = (
            select(Problem.pid)
            .where(
                Problem.solution_open.is_(True),
                Problem.difficulty.in_(["普及/提高-", "普及+/提高", "提高+/省选-"]),
                or_(
                    Problem.last_solution_check_at < now - timedelta(hours=12),
                    Problem.last_solution_check_at.is_(None),
                ),
            )
            .limit(500)
        )
        tier2 = [r[0] for r in (await session.execute(q)).all()]

        # 省选/NOI- + NOI/CTSC
        q = (
            select(Problem.pid)
            .where(
                Problem.solution_open.is_(True),
                Problem.difficulty.in_(["省选/NOI-", "NOI/NOI+/CTSC"]),
                or_(
                    Problem.last_solution_check_at < now - timedelta(days=3),
                    Problem.last_solution_check_at.is_(None),
                ),
            )
            .limit(200)
        )
        tier3 = [r[0] for r in (await session.execute(q)).all()]

    for pid in tier1 + tier2 + tier3:
        crawl_problem_solution.send(pid, "scheduled")
    log.info(
        "problem_polling.enqueued",
        tier1=len(tier1), tier2=len(tier2), tier3=len(tier3),
    )


async def job_problem_list_scan() -> None:
    """每天凌晨扫前 20 页题目列表，发现新题。"""
    from app.tasks.actors.crawl import crawl_problem_list_page
    for page in range(1, 21):
        crawl_problem_list_page.send(page, "scheduled")


# ============================================================
# 启动入口
# ============================================================

def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    # 稍微错开分钟数，避免所有任务同时触发
    sched.add_job(job_discover_discuss, "interval", minutes=5, id="discover_discuss")
    sched.add_job(job_discover_article, "interval", minutes=10, id="discover_article")
    sched.add_job(job_crawl_judgement, "interval", hours=1, id="crawl_judgement")
    sched.add_job(job_feed_tiered_polling, "interval", minutes=10, id="feed_polling")
    sched.add_job(job_problem_tiered_polling, "interval", hours=1, id="problem_polling")
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
