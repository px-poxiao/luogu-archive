"""题目爬虫：列表页 + 题解开放状态。

- 列表页 /problem/list?page=N   → 老版 SSR（_feInjection）
  用于发现最新题号 + 获取难度
- 题解状态 /problem/solution/<pid>   → 新版 SSR 或 HTML 兜底
  判断"是否允许提交题解"
"""
from __future__ import annotations

import time as _t

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
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_content import Problem, ProblemSolutionHistory

log = get_logger(__name__)


async def crawl_list_page(page: int, *, trigger: str = "scheduled") -> None:
    """爬题目列表一页，更新 problems 主表。"""
    async with task_lock("problem_list", str(page)) as got:
        if not got:
            log.info("crawl_problem_list.skip_locked", page=page)
            return
        await _crawl_list_inner(page, trigger=trigger)


def _extract_problem_items(kind: str, data: dict) -> list[dict]:
    """从两种 SSR 结构中取题目列表。

    - injection（老版）：currentData.problems = { result: [...], perPage, count }
    - lentille（新版）：data.problems 同样位置，兜底也看 data.result
    """
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
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    url_path = "/problem/list"
    task_id = await record_task_start(
        "problem_list",
        f"{url_path}?page={page}",
        trigger=trigger_from(trigger),
        node_id=node.node_id,
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(
            url_path, node=node, redis=redis, params={"page": page}, parse="html"
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
            rows.append(
                {
                    "pid": str(pid),
                    "title": (item.get("title") or "")[:500],
                    "difficulty": _diff_text(item.get("difficulty")),
                    "solution_open": bool(item.get("showSolution", False)),
                    "first_seen_at": utcnow(),
                }
            )

        if rows:
            async with db_session() as session:
                stmt = mysql_insert(Problem).values(rows)
                # 已存在的题目更新标题和难度，但 solution_open 不从列表接口确定
                stmt = stmt.on_duplicate_key_update(
                    title=stmt.inserted.title,
                    difficulty=stmt.inserted.difficulty,
                )
                await session.execute(stmt)
                await session.commit()

        # 列表页只能拿到标题/难度；solution_open 必须靠 /problem/solution/<pid> 判断。
        # 这里对本页所有题目派发 crawl_problem_solution，错峰避免打爆节点。
        # manual 触发才派；scheduled 巡检由 scheduler 单独管理（避免每次轮询雪崩）。
        if trigger == "manual" and rows:
            from app.tasks.actors.crawl import crawl_problem_solution
            for i, r in enumerate(rows):
                try:
                    crawl_problem_solution.send_with_options(
                        args=(r["pid"], "cascaded_from_problem_list"),
                        delay=i * 3000,   # 每 3 秒一题
                    )
                except Exception as e:
                    log.warning(
                        "crawl_problem_list.cascade_solution_failed",
                        pid=r["pid"], error=str(e),
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


# 洛谷难度整数编码 → 文本
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


def _diff_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return _DIFF_MAP.get(v, f"unknown_{v}")
    return str(v)


async def crawl_solution_state(pid: str, *, trigger: str = "scheduled") -> None:
    """爬题解开放状态：/problem/solution/<pid>"""
    async with task_lock("problem_solution", pid) as got:
        if not got:
            log.info("crawl_problem_solution.skip_locked", pid=pid)
            return
        await _crawl_solution_inner(pid, trigger=trigger)


async def _crawl_solution_inner(pid: str, *, trigger: str) -> None:
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    url_path = f"/problem/solution/{pid}"
    task_id = await record_task_start(
        "problem_solution",
        url_path,
        trigger=trigger_from(trigger),
        node_id=node.node_id,
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(url_path, node=node, redis=redis, parse="html")
        # 判断 solution_open：先尝试解析结构化数据，失败回退到文本匹配
        solution_open = _detect_solution_open(result.body_text)

        async with db_session() as session:
            existing = await session.get(Problem, pid)
            now = utcnow()
            if existing is None:
                session.add(
                    Problem(
                        pid=pid,
                        title=pid,
                        solution_open=solution_open,
                        last_solution_check_at=now,
                        first_seen_at=now,
                    )
                )
            else:
                if existing.solution_open != solution_open:
                    session.add(
                        ProblemSolutionHistory(
                            pid=pid,
                            solution_open=solution_open,
                        )
                    )
                existing.solution_open = solution_open
                existing.last_solution_check_at = now
            await session.commit()

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
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


# 负面关键字：命中即视作"不允许提交题解"
_DENY_KEYWORDS = (
    "不允许提交题解",
    "不可以提交题解",
    "题解已关闭",
    "已禁止题解",
)


def _detect_solution_open(body_text: str) -> bool:
    # 先尝试结构化
    try:
        kind, page_data = extract_page_data(body_text)
        if kind == "injection":
            current = current_data_from_injection(page_data)
            for key in ("canSubmitSolution", "solutionOpen", "acceptingSolutions"):
                v = current.get(key)
                if isinstance(v, bool):
                    return v
        else:
            inner = data_from_lentille(page_data)
            for key in ("canSubmitSolution", "solutionOpen", "acceptingSolutions"):
                v = inner.get(key)
                if isinstance(v, bool):
                    return v
    except Exception:
        pass
    # 文本兜底
    for kw in _DENY_KEYWORDS:
        if kw in body_text:
            return False
    return True
