"""洛谷比赛列表、详情与排行榜抓取。

所有请求都经过项目统一的 crawler HTTP 层，因此 ``luogu.com.cn`` 会严格执行
每次请求完成后冷却 10 秒的限制。这里只抓排行榜结果，不请求任何提交记录。
"""
from __future__ import annotations

from typing import Any

from app.core.exceptions import CrawlerError
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.lentille import data_from_lentille


CN_BASE = "https://www.luogu.com.cn"


def _context_data(result_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result_data, dict):
        return {}
    data = data_from_lentille(result_data)
    return data if data else result_data


def _find_contest_list(value: Any) -> list[dict[str, Any]]:
    """兼容洛谷前端上下文字段改名，寻找比赛列表对象。"""

    if isinstance(value, list):
        rows = [item for item in value if isinstance(item, dict)]
        if rows and all("id" in row and "name" in row and "endTime" in row for row in rows):
            return rows
        for item in rows:
            found = _find_contest_list(item)
            if found:
                return found
    elif isinstance(value, dict):
        # 优先常见分页字段，避免误命中比赛正文中的其他列表。
        for key in ("result", "contests", "items", "records"):
            if key in value:
                found = _find_contest_list(value[key])
                if found:
                    return found
        for child in value.values():
            found = _find_contest_list(child)
            if found:
                return found
    return []


async def fetch_first_page() -> list[dict[str, Any]]:
    """抓取比赛列表第一页。"""

    result = await fetch_anon(
        f"{CN_BASE}/contest/list",
        redis=get_redis(),
        parse="html",
    )
    rows = _find_contest_list(_context_data(result.data))
    if not rows:
        raise CrawlerError("比赛列表页面中没有找到比赛数据")
    return rows


def _problem_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从比赛详情上下文提取题目，保留原顺序。"""

    for key in ("problems", "contestProblems", "problemList"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            result: list[dict[str, Any]] = []
            for pid, item in value.items():
                if isinstance(item, dict):
                    result.append({"pid": pid, **item})
            if result:
                return result
    return []


async def fetch_detail(contest_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """抓取比赛基础信息与题目元数据。"""

    result = await fetch_anon(
        f"{CN_BASE}/contest/{contest_id}",
        redis=get_redis(),
        parse="html",
    )
    data = _context_data(result.data)
    contest = data.get("contest")
    if not isinstance(contest, dict):
        raise CrawlerError(f"比赛 {contest_id} 详情中没有 contest 对象")
    return contest, _problem_rows(data)


async def fetch_scoreboard(contest_id: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按每页 50 人抓完整排行榜。"""

    rows: list[dict[str, Any]] = []
    page = 1
    meta: dict[str, Any] = {}
    while True:
        result = await fetch_anon(
            f"{CN_BASE}/fe/api/contest/scoreboard/{contest_id}",
            redis=get_redis(),
            params={"page": page},
            accept_json=True,
            parse="json",
        )
        payload = result.data or {}
        scoreboard = payload.get("scoreboard")
        if not isinstance(scoreboard, dict):
            raise CrawlerError(f"比赛 {contest_id} 榜单第 {page} 页缺少 scoreboard")
        batch = scoreboard.get("result") or []
        if not isinstance(batch, list):
            raise CrawlerError(f"比赛 {contest_id} 榜单第 {page} 页格式错误")
        meta = {key: value for key, value in scoreboard.items() if key != "result"}
        rows.extend(item for item in batch if isinstance(item, dict))
        total = int(scoreboard.get("count") or len(rows))
        if not batch or len(rows) >= total:
            break
        page += 1
    return rows, meta
