"""题目爬虫：列表页 + 题解开放状态。

- 列表页 /problem/list?page=N   → 老版 SSR（_feInjection）
  用于发现最新题号 + 获取难度
- 题解状态 /problem/solution/<pid>   → 新版 SSR 或 HTML 兜底
  判断"是否允许提交题解"
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

        # 在写入前先记录"哪些 pid 是本批次新发现的"（DB 里之前不存在）
        new_pids: set[str] = set()
        if rows:
            async with db_session() as session:
                # 先查这批 pid 哪些已经存在
                pids_in_batch = [r["pid"] for r in rows]
                existing_q = select(Problem.pid).where(Problem.pid.in_(pids_in_batch))
                existing_set = {
                    r[0] for r in (await session.execute(existing_q)).all()
                }
                new_pids = set(pids_in_batch) - existing_set

                stmt = mysql_insert(Problem).values(rows)
                # 已存在的题目更新标题和难度，但 solution_open 不从列表接口确定
                stmt = stmt.on_duplicate_key_update(
                    title=stmt.inserted.title,
                    difficulty=stmt.inserted.difficulty,
                )
                await session.execute(stmt)
                await session.commit()

        # 1.md 原则：不允许提交题解的题一般不会重新开放，更新时只确定那些"允许提交题解"的题。
        # 具体策略：
        #   - 本批次新发现的题（DB 里还不存在）：cascade 扫一次确认初始状态
        #   - 已经 solution_open=True 的老题：cascade 重扫（确认是否仍然开放）
        #   - 已经 solution_open=False 的老题：跳过（视为终态，节省请求）
        # manual 触发才派；scheduled 巡检由 scheduler 单独管理（避免每次轮询雪崩）。
        if trigger == "manual" and rows:
            from app.tasks.actors.crawl import crawl_problem_solution
            async with db_session() as session:
                # 已开放的老题
                pids_in_batch = [r["pid"] for r in rows]
                open_q = (
                    select(Problem.pid)
                    .where(Problem.pid.in_(pids_in_batch))
                    .where(Problem.solution_open.is_(True))
                )
                open_pids = {r[0] for r in (await session.execute(open_q)).all()}
            cascade_pids = sorted(new_pids | open_pids)
            for i, pid in enumerate(cascade_pids):
                try:
                    crawl_problem_solution.send_with_options(
                        args=(pid, "cascaded_from_problem_list"),
                        delay=i * 3000,   # 每 3 秒一题
                    )
                except Exception as e:
                    log.warning(
                        "crawl_problem_list.cascade_solution_failed",
                        pid=pid, error=str(e),
                    )
            log.info(
                "crawl_problem_list.cascade_solution_dispatched",
                page=page,
                new_count=len(new_pids),
                open_count=len(open_pids),
                total=len(cascade_pids),
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


# 洛谷难度整数编码 → 文本（API 偶发返回 int 编号）
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

# 常见难度字符串值（防御式：洛谷可能也返回 string）
_DIFF_STRING_NORMALIZE = {
    # 已知洛谷网页的中文标签
    "暂无评定": "暂无评定",
    "入门": "入门",
    "普及-": "普及-",
    "普及/提高-": "普及/提高-",
    "普及+/提高": "普及+/提高",
    "提高+/省选-": "提高+/省选-",
    "省选/NOI-": "省选/NOI-",
    "NOI/NOI+/CTSC": "NOI/NOI+/CTSC",
}


def _diff_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, int):
        return _DIFF_MAP.get(v, f"unknown_{v}")
    if isinstance(v, str):
        # 标准化字符串：先看是不是已知文本，否则原样返回
        s = v.strip()
        if s in _DIFF_STRING_NORMALIZE:
            return _DIFF_STRING_NORMALIZE[s]
        # 偶发：洛谷返回数字字符串
        if s.isdigit():
            return _DIFF_MAP.get(int(s), f"unknown_{s}")
        log.warning("problem.unknown_difficulty_string", value=s)
        return s
    log.warning("problem.unknown_difficulty_type", value=v, type=type(v).__name__)
    return str(v)


async def crawl_solution_state(pid: str, *, trigger: str = "scheduled") -> None:
    """爬题解开放状态：/problem/solution/<pid>"""
    async with task_lock("problem_solution", pid) as got:
        if not got:
            log.info("crawl_problem_solution.skip_locked", pid=pid)
            return
        await _crawl_solution_inner(pid, trigger=trigger)


async def _crawl_solution_inner(pid: str, *, trigger: str) -> None:
    """题解开放检测必须带 Cookie 访问，否则洛谷返回 401。
    用 AUTHED 节点 + 账号池里的一个账号 cookie。
    """
    from app.crawler.cookies import lease_account, mark_account_ok
    from app.crawler.http import fetch_authed

    node = get_default_node(NodeKind.AUTHED)
    redis = get_redis()
    url_path = f"/problem/solution/{pid}"

    async with lease_account() as acc:
        if acc is None:
            task_id = await record_task_start(
                "problem_solution",
                url_path,
                trigger=trigger_from(trigger),
                node_id=node.node_id,
                account_id=None,
            )
            await record_task_done(
                task_id,
                status=CrawlTaskStatus.failed,
                error_msg="no_account_available: 所有 Cookie 账号都不可用（QPH 用满 / 被禁用 / 锁占用）",
                duration_ms=0,
            )
            log.warning("crawl_problem_solution.no_account_available", pid=pid)
            raise CrawlerError("题解开放检测需要 Cookie 账号，但当前无可用账号")

        task_id = await record_task_start(
            "problem_solution",
            url_path,
            trigger=trigger_from(trigger),
            node_id=node.node_id,
            account_id=acc.account_id,
        )
        start = _t.monotonic()
        try:
            result = await fetch_authed(
                url_path,
                node=node,
                redis=redis,
                cookies=acc.as_cookie_dict(),
                accept_json=False,
                parse="html",
            )
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
            await mark_account_ok(acc.account_id)
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

# lentille / injection 的判定字段名（按优先级试）
_SOLUTION_FIELDS = ("canSubmitSolution", "solutionOpen", "acceptingSolutions", "showSolution")


def _detect_solution_open(body_text: str) -> bool:
    """判断该题题解通道是否开放。

    策略：
      1. 优先看结构化字段（lentille 或 injection 里的 canSubmitSolution / showSolution 等）
      2. 找不到结构化字段 → 看负面关键字命中（"不允许提交题解"等）
      3. 都判不出 → **返回 False（保守）**
         理由：1.md 原则"不开放是终态"，宁可漏掉一题暂时不显示，也不要把
         大量"不允许"的题误判成允许。
    """
    # 1. 结构化字段
    try:
        kind, page_data = extract_page_data(body_text)
        if kind == "injection":
            current = current_data_from_injection(page_data)
        else:
            current = data_from_lentille(page_data)

        # 直接顶层字段
        for key in _SOLUTION_FIELDS:
            v = current.get(key)
            if isinstance(v, bool):
                return v
        # 嵌套在 problem 子节点里
        problem = current.get("problem")
        if isinstance(problem, dict):
            for key in _SOLUTION_FIELDS:
                v = problem.get(key)
                if isinstance(v, bool):
                    return v
    except Exception:
        pass

    # 2. 负面关键字明确命中 → 关闭
    for kw in _DENY_KEYWORDS:
        if kw in body_text:
            return False

    # 3. 啥也判断不出 —— 保守判关闭
    log.warning("problem_solution.indeterminate", body_head=body_text[:200])
    return False
