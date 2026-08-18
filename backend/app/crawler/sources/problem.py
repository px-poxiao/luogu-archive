"""题目爬虫：官方题库包 + 题解开放状态。

- 官方题库包 latest.ndjson.gz
  全量维护 pid / title / difficulty / tags
- 题解状态 /problem/<pid>
  匿名访问详情页，读 lentille 里的 problem.acceptSolution（true/false）
  ↑ 改造前用 /problem/solution/<pid> 需要 cookie；现在不需要，
  authed 节点完全释放给犇犇用。

题库包走洛谷 CDN，不占用主站限流资源；题解状态走 .com.cn 主站节点。
"""
from __future__ import annotations

import json
import time as _t
import zlib
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon, get_http_client
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

_PROBLEMSET_URL = "https://cdn.luogu.com.cn/problemset-open/latest.ndjson.gz"
_PROBLEMSET_BATCH_SIZE = 500
_PROBLEMSET_MIN_RECORDS = 1_000


# ============================================================
# 难度文本化
# ============================================================

_DIFF_MAP = {
    0: "暂无评定",
    1: "入门",
    2: "普及-",
    3: "普及",
    4: "普及+/提高-",
    5: "提高",
    6: "提高+/省选-",
    7: "省选/NOI-",
    8: "NOI/NOI+/CTS",
}

_DIFF_STRING_NORMALIZE = {v: v for v in _DIFF_MAP.values()}
_DIFF_STRING_NORMALIZE.update(
    {
        "普及/提高-": "普及",
        "普及+/提高": "普及+/提高-",
        "NOI/NOI+/CTSC": "NOI/NOI+/CTS",
    }
)


def _diff_text(v) -> str | None:
    """归一化 difficulty 字段为中文文本。lentille 现在返 int(0-8)。"""
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
# 官方题库包：latest.ndjson.gz
# ============================================================

async def _iter_gzip_ndjson(chunks: AsyncIterator[bytes]) -> AsyncIterator[dict]:
    """增量解压 gzip NDJSON，避免把完整题面包一次性放进内存。"""

    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pending = b""
    async for chunk in chunks:
        pending += decoder.decompress(chunk)
        lines = pending.split(b"\n")
        pending = lines.pop()
        for line in lines:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value

    pending += decoder.flush()
    if not decoder.eof:
        raise CrawlerError("官方题库包下载不完整")
    if pending.strip():
        value = json.loads(pending)
        if isinstance(value, dict):
            yield value


def _problemset_row(item: dict, now) -> dict | None:
    pid = str(item.get("pid") or "").strip().upper()
    title = str(item.get("title") or "").strip()
    if not pid or not title:
        return None

    tags_raw = item.get("tags")
    tags = (
        [tag for tag in tags_raw if isinstance(tag, (str, int))]
        if isinstance(tags_raw, list)
        else []
    )
    return {
        "pid": pid[:32],
        "title": title[:500],
        "difficulty": _diff_text(item.get("difficulty")),
        "tags": tags,
        "first_seen_at": now,
    }


async def sync_problem_catalog(*, trigger: str = "scheduled") -> None:
    """下载官方题库包，并全量更新其中每一道题的元数据。"""

    async with task_lock("problem_catalog", "official", ttl_sec=30 * 60) as got:
        if not got:
            log.info("problem_catalog.skip_locked")
            return
    task_id = await record_task_start(
        "problem_catalog",
        _PROBLEMSET_URL,
        trigger=trigger_from(trigger),
    )
    start = _t.monotonic()
    http_status: int | None = None
    try:
        rows_by_pid: dict[str, dict] = {}
        now = utcnow()
        client = get_http_client()
        async with client.stream(
            "GET",
            _PROBLEMSET_URL,
            headers={
                "Accept": "application/gzip",
                "Accept-Encoding": "identity",
            },
            timeout=120,
        ) as response:
            http_status = response.status_code
            response.raise_for_status()
            async for item in _iter_gzip_ndjson(response.aiter_raw()):
                row = _problemset_row(item, now)
                if row is not None:
                    rows_by_pid[row["pid"]] = row

        rows = list(rows_by_pid.values())
        if len(rows) < _PROBLEMSET_MIN_RECORDS:
            raise CrawlerError(f"官方题库包记录异常，仅解析到 {len(rows)} 道题")

        async with db_session() as session:
            existing_set = set((await session.execute(select(Problem.pid))).scalars())
            new_pids = set(rows_by_pid) - existing_set
            for offset in range(0, len(rows), _PROBLEMSET_BATCH_SIZE):
                batch = rows[offset:offset + _PROBLEMSET_BATCH_SIZE]
                stmt = mysql_insert(Problem).values(batch)
                stmt = stmt.on_duplicate_key_update(
                    title=stmt.inserted.title,
                    difficulty=stmt.inserted.difficulty,
                    tags=stmt.inserted.tags,
                    updated_at=now,
                )
                await session.execute(stmt)
            await session.commit()

        from app.tasks.problem_queue import enqueue_problem_solution

        dispatched = 0
        skipped_dedup = 0
        dispatch_failed = 0
        for pid in sorted(new_pids):
            try:
                queued = await enqueue_problem_solution(
                    pid,
                    f"cascaded_from_catalog_{trigger}",
                    delay_ms=dispatched * 11_000,
                )
            except Exception as exc:
                dispatch_failed += 1
                log.warning(
                    "problem_catalog.cascade_solution_failed",
                    pid=pid,
                    error=str(exc),
                )
                continue
            if queued.enqueued:
                dispatched += 1
            else:
                skipped_dedup += 1

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=http_status,
            duration_ms=dur,
        )
        log.info(
            "problem_catalog.done",
            count=len(rows),
            new_count=len(new_pids),
            cascade_count=dispatched,
            skipped_dedup=skipped_dedup,
            dispatch_failed=dispatch_failed,
            trigger=trigger,
        )
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            http_status=http_status,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("problem_catalog.failed", error=str(e), trigger=trigger)
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

