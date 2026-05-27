"""题目爬虫：列表页 + 题解开放状态。

- 列表页 /problem/list?page=N
  发现新题号 + 维护 title / difficulty / tags
- 题解状态 /problem/<pid>
  匿名访问详情页，读 lentille 里的 problem.acceptSolution（true/false）
  ↑ 改造前用 /problem/solution/<pid> 需要 cookie；现在不需要，
  authed 节点完全释放给犇犇用。

所有路径都自动走 .com.cn 主站节点（fetch_anon 按域名挑节点）。
"""
from __future__ import annotations

import time as _t

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.lentille import (
    current_data_from_injection,
    data_from_lentille,
    extract_page_data,
)
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_content import Problem, ProblemSolutionHistory

log = get_logger(__name__)


# ============================================================
# 难度文本化
# ============================================================

_DIFF_MAP = {
    0: "暂无评定",
    1: "入门",
    2: "普及-",
    3: "普及/提高-",
    4: "普及+/提高",
    5: "提高+/省选-",
    6: "省选/NOI-",
    7: "NOI/NOI+/CTSC",
}

_DIFF_STRING_NORMALIZE = {v: v for v in _DIFF_MAP.values()}


def _diff_text(v) -> str | None:
    """归一化 difficulty 字段为中文文本。lentille 现在返 int(0-7)。"""
    if v is None:
        return None
    if isinstance(v, int):
        return _DIFF_MAP.get(v, f"unknown_{v}")
    if isinstance(v, str):
        s = v.strip()
        if s in _DIFF_STRING_NORMALIZE:
            return _DIFF_STRING_NORMALIZE[s]
        if s.isdigit():
            return _DIFF_MAP.get(int(s), f"unknown_{s}")
        log.warning("problem.unknown_difficulty_string", value=s)
        return s
    log.warning("problem.unknown_difficulty_type", type=type(v).__name__)
    return None


# ============================================================
# 列表页：/problem/list?page=N
# ============================================================

async def crawl_list_page(page: int, *, trigger: str = "scheduled") -> None:
    """爬题目列表一页，更新 problems 主表。"""
    async with task_lock("problem_list", str(page)) as got:
        if not got:
            log.info("crawl_problem_list.skip_locked", page=page)
            return
        await _crawl_list_inner(page, trigger=trigger)


def _extract_problem_items(kind: str, data: dict) -> list[dict]:
    """从 lentille / injection 两种 SSR 结构中取题目列表。"""
    if kind == "injection":
        current = current_data_from_injection(data)
        pr = current.get("problems")
        if isinstance(pr, dict) and isinstance(pr.get("result"), list):
            return pr["result"]
        if isinstance(pr, list):
            return pr
        raise CrawlerError(f"injection.currentData 里无 problems: keys={list(current.keys())}")

    inner = data_from_lentille(data)
    for key in ("problems", "result"):
        v = inner.get(key)
        if isinstance(v, dict) and isinstance(v.get("result"), list):
            return v["result"]
        if isinstance(v, list):
            return v
    raise CrawlerError(f"lentille.data 里无 problems: keys={list(inner.keys())}")


async def _crawl_list_inner(page: int, *, trigger: str) -> None:
    redis = get_redis()
    url_path = "/problem/list"
    # 列表页强制走 .com.cn（_resolve_url 已处理）；fetch_anon 自动选 cn 节点
    task_id = await record_task_start(
        "problem_list",
        f"{url_path}?page={page}",
        trigger=trigger_from(trigger),
        node_id=None,  # 节点 ID 在 fetch_anon 内部确定，这里 placeholder
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(
            url_path, redis=redis, params={"page": page}, parse="html"
        )
        kind, page_data = extract_page_data(result.body_text)
        items = _extract_problem_items(kind, page_data)

        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = item.get("pid")
            if not pid:
                continue
            # lentille 字段：name / difficulty(int) / tags(int[]) / flag(int)
            title = item.get("name") or item.get("title") or ""
            tags_raw = item.get("tags") or []
            tags = [int(t) for t in tags_raw if isinstance(t, (int, str)) and str(t).isdigit()]
            rows.append(
                {
                    "pid": str(pid),
                    "title": title[:500],
                    "difficulty": _diff_text(item.get("difficulty")),
                    "tags": tags,
                    "first_seen_at": utcnow(),
                }
            )

        if rows:
            sample = rows[0]
            log.info(
                "crawl_problem_list.sample",
                page=page, count=len(rows),
                pid=sample["pid"], title=sample["title"],
                difficulty=sample["difficulty"], tags=sample["tags"],
            )

        # 写库：UPSERT title / difficulty / tags（solution_open 由 _crawl_problem_inner 单独维护）
        new_pids: set[str] = set()
        if rows:
            async with db_session() as session:
                pids_in_batch = [r["pid"] for r in rows]
                existing_q = select(Problem.pid).where(Problem.pid.in_(pids_in_batch))
                existing_set = {r[0] for r in (await session.execute(existing_q)).all()}
                new_pids = set(pids_in_batch) - existing_set

                stmt = mysql_insert(Problem).values(rows)
                stmt = stmt.on_duplicate_key_update(
                    title=stmt.inserted.title,
                    difficulty=stmt.inserted.difficulty,
                    tags=stmt.inserted.tags,
                )
                await session.execute(stmt)
                await session.commit()

        # cascade 派题解检测：
        # - manual / 入口页发现等"高频用户触发"：批次内全部派
        # - scheduled / cascaded_*：只派 new_pids（首次见的题），避免每天定时
        #   扫一次就把 1000+ 已知题全部重派堵队列
        # - 同 pid 30 分钟 redis 去重（NX setex），防止短时多源并发派同一题
        # - 错峰 11s/题（节点 0.1 req/s = 10s/req，留 1s 余量）
        # - solution_open=False 且已检测过的老题不再派（已确认关闭，终态）
        if rows:
            from app.tasks.actors.crawl import crawl_problem_solution
            async with db_session() as session:
                pids_in_batch = [r["pid"] for r in rows]
                # 已确认关闭的老题排除
                closed_q = (
                    select(Problem.pid)
                    .where(Problem.pid.in_(pids_in_batch))
                    .where(Problem.solution_open.is_(False))
                    .where(Problem.last_solution_check_at.is_not(None))
                )
                closed_set = {r[0] for r in (await session.execute(closed_q)).all()}

            base_candidates = sorted(set(pids_in_batch) - closed_set)
            # scheduled / cascade 触发：只派新题，老题留给 tiered_polling
            is_low_priority_trigger = (
                trigger == "scheduled" or trigger.startswith("cascaded")
            )
            if is_low_priority_trigger:
                cascade_pids = [p for p in base_candidates if p in new_pids]
            else:
                cascade_pids = base_candidates

            # 30 分钟 redis NX 去重，防短时多源并发重复派
            dispatched = 0
            skipped_dedup = 0
            for pid in cascade_pids:
                dedup_key = f"crawl:dedup:problem_solution:{pid}"
                if not await redis.set(dedup_key, "1", ex=1800, nx=True):
                    skipped_dedup += 1
                    continue
                try:
                    crawl_problem_solution.send_with_options(
                        args=(pid, f"cascaded_from_list_{trigger}"),
                        delay=dispatched * 11_000,
                    )
                    dispatched += 1
                except Exception as e:
                    log.warning(
                        "crawl_problem_list.cascade_solution_failed",
                        pid=pid, error=str(e),
                    )
            log.info(
                "crawl_problem_list.cascade_solution_dispatched",
                page=page, new_count=len(new_pids),
                cascade_count=dispatched, skipped_dedup=skipped_dedup,
                total=len(pids_in_batch),
                low_priority=is_low_priority_trigger,
            )

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )
        log.info("crawl_problem_list.done", page=page, count=len(rows), kind=kind)
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("crawl_problem_list.failed", page=page, error=str(e))
        raise


# ============================================================
# 题解开放检测：/problem/<pid>
# ============================================================

async def crawl_solution_state(pid: str, *, trigger: str = "scheduled") -> None:
    """爬题目详情页，读 acceptSolution 字段判定题解是否开放。"""
    async with task_lock("problem_solution", pid) as got:
        if not got:
            log.info("crawl_problem_solution.skip_locked", pid=pid)
            return
        await _crawl_solution_inner(pid, trigger=trigger)


async def _crawl_solution_inner(pid: str, *, trigger: str) -> None:
    """匿名访问 /problem/<pid>，读 lentille.problem.acceptSolution。

    acceptSolution=true → 题解开放；false → 不允许提交题解。
    """
    redis = get_redis()
    url_path = f"/problem/{pid}"
    task_id = await record_task_start(
        "problem_solution",
        url_path,
        trigger=trigger_from(trigger),
        node_id=None,
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(url_path, redis=redis, parse="html")

        solution_open = _detect_solution_open(result.body_text)
        title_from_page = _extract_problem_title(result.body_text)
        difficulty_from_page = _extract_problem_difficulty(result.body_text)
        tags_from_page = _extract_problem_tags(result.body_text)

        async with db_session() as session:
            existing = await session.get(Problem, pid)
            now = utcnow()
            if existing is None:
                # cascade 派出去时还没入库 → 直接补 row
                session.add(
                    Problem(
                        pid=pid,
                        title=title_from_page or pid,
                        difficulty=difficulty_from_page,
                        tags=tags_from_page,
                        solution_open=solution_open,
                        last_solution_check_at=now,
                        first_seen_at=now,
                    )
                )
            else:
                # 状态变化 → 写历史
                if existing.solution_open != solution_open:
                    session.add(
                        ProblemSolutionHistory(
                            pid=pid,
                            solution_open=solution_open,
                        )
                    )
                existing.solution_open = solution_open
                existing.last_solution_check_at = now
                # 顺手刷 title/difficulty/tags（详情页这些字段比 list 接口准）
                if title_from_page:
                    existing.title = title_from_page
                if difficulty_from_page is not None:
                    existing.difficulty = difficulty_from_page
                if tags_from_page is not None:
                    existing.tags = tags_from_page
            await session.commit()

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )
        log.info(
            "crawl_problem_solution.done",
            pid=pid, solution_open=solution_open, trigger=trigger,
        )
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("crawl_problem_solution.failed", pid=pid, error=str(e))
        raise


def _get_problem_node(body_text: str) -> dict | None:
    """从 SSR body 里取 problem 节点（同时兼容 lentille 和 injection）。"""
    try:
        kind, page_data = extract_page_data(body_text)
        inner = (
            current_data_from_injection(page_data)
            if kind == "injection"
            else data_from_lentille(page_data)
        )
        if isinstance(inner.get("problem"), dict):
            return inner["problem"]
        return inner if isinstance(inner, dict) else None
    except Exception:
        return None


def _detect_solution_open(body_text: str) -> bool:
    """读 lentille.problem.acceptSolution。判不出来保守视作 False。"""
    p = _get_problem_node(body_text)
    if p is None:
        log.warning("problem_solution.indeterminate", body_head=body_text[:200])
        return False
    v = p.get("acceptSolution")
    if isinstance(v, bool):
        return v
    log.warning("problem_solution.no_acceptSolution_field", pid=p.get("pid"))
    return False


def _extract_problem_title(body_text: str) -> str | None:
    p = _get_problem_node(body_text)
    if p is None:
        return None
    v = p.get("name") or p.get("title")
    return v[:500] if isinstance(v, str) else None


def _extract_problem_difficulty(body_text: str) -> str | None:
    p = _get_problem_node(body_text)
    if p is None:
        return None
    return _diff_text(p.get("difficulty"))


def _extract_problem_tags(body_text: str) -> list[int] | None:
    p = _get_problem_node(body_text)
    if p is None:
        return None
    raw = p.get("tags") or []
    if not isinstance(raw, list):
        return None
    return [int(t) for t in raw if isinstance(t, (int, str)) and str(t).isdigit()]
