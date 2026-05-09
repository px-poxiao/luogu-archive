"""题目爬虫：列表页 + 题解开放状态。

- 列表页 /problem/list?page=N
  用于发现最新题号 + 获取难度
- 题解状态 /problem/solution/<pid>
  判断"是否允许提交题解"。允许则 solution_open=True。
  页面上有"提交题解"按钮时允许，页面显示"该题目不允许提交题解"时禁止。

两种方式：
- 列表页拿 lentille-context，data.problems 或类似字段
- 题解状态页：看 lentille 里的 solution 相关字段或页面文案关键字
"""
from __future__ import annotations

import time as _t

from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.lentille import data_from_lentille
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
            url_path, node=node, redis=redis, params={"page": page}
        )
        if result.data is None:
            raise CrawlerError("题目列表页无 lentille-context")
        data = data_from_lentille(result.data)

        # 洛谷返回结构：data.problems.result 或 data.result（猜测）
        items = None
        for node_k in ("problems", "result"):
            v = data.get(node_k)
            if isinstance(v, dict) and isinstance(v.get("result"), list):
                items = v["result"]
                break
            if isinstance(v, list):
                items = v
                break
        if items is None:
            raise CrawlerError(f"题目列表 data keys={list(data.keys())}")

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
                    "title": item.get("title") or "",
                    "difficulty": _diff_text(item.get("difficulty")),
                    "solution_open": bool(item.get("showSolution", False)),
                    "first_seen_at": utcnow(),
                }
            )

        if rows:
            async with db_session() as session:
                stmt = mysql_insert(Problem).values(rows)
                # 已存在的题目更新标题和难度，但 solution_open 不从列表接口确定（列表可能不给）
                stmt = stmt.on_duplicate_key_update(
                    title=stmt.inserted.title,
                    difficulty=stmt.inserted.difficulty,
                )
                await session.execute(stmt)
                await session.commit()

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )
        log.info("crawl_problem_list.done", page=page, count=len(rows))
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
        result = await fetch_anon(url_path, node=node, redis=redis)
        # 判断 solution_open
        # 策略：先看 lentille 数据里是否有 canSubmitSolution / isAllowed 字段
        # 再回退到页面文本关键字
        solution_open = _detect_solution_open(result.body_text, result.data)

        async with db_session() as session:
            existing = await session.get(Problem, pid)
            now = utcnow()
            if existing is None:
                # 列表爬虫还没发现这题，先占位建一行（避免 FK 爆炸）
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


def _detect_solution_open(body_text: str, data: dict | None) -> bool:
    # 优先结构化字段（实测可能的位置）
    if isinstance(data, dict):
        inner = data_from_lentille(data)
        for key in ("canSubmitSolution", "solutionOpen", "acceptingSolutions"):
            v = inner.get(key)
            if isinstance(v, bool):
                return v
    # 回退：文本关键字
    for kw in _DENY_KEYWORDS:
        if kw in body_text:
            return False
    # 既没结构化字段也没负面关键字 → 默认认为开放（宁松勿严）
    return True
