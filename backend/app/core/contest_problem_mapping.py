"""比赛临时题号、正式题号与每题成绩的映射工具。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def scoreboard_problem_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """从榜单原始 JSON 中提取按 A、B、C 顺序排列的正式题号。

    Python JSON 解析会保留源对象顺序，因此必须在写入 MySQL JSON 之前提取。
    """

    best: list[str] = []
    for row in rows:
        details = row.get("details")
        if not isinstance(details, Mapping):
            continue
        current = [str(pid) for pid in details]
        if len(current) > len(best):
            best = current
    return best


def resolve_display_problem_ids(
    problem_ids: Sequence[str],
    stored_ids: Sequence[str | None],
    samples: Sequence[Mapping[str, Any] | None],
) -> list[str]:
    """优先使用已保存的正式题号，并为旧归档按完整榜单样本补映射。"""

    if len(problem_ids) != len(stored_ids):
        raise ValueError("比赛题号与正式题号映射数量不一致")

    legacy_ids: list[str] = []
    for details in samples:
        if not isinstance(details, Mapping):
            continue
        current = [str(pid) for pid in details]
        if len(current) > len(legacy_ids):
            legacy_ids = current

    # 榜单 details 是 JSON 对象，其键顺序不能视为官方题目顺序。若题号集合
    # 完全相同，应直接沿用比赛页面的 A、B、C 顺序，避免把同一批题目错误置换。
    complete_stored_ids = [str(pid) for pid in stored_ids if pid]
    if len(complete_stored_ids) == len(problem_ids):
        if set(complete_stored_ids) == set(problem_ids):
            return list(problem_ids)
        return complete_stored_ids

    if len(legacy_ids) == len(problem_ids) and set(legacy_ids) == set(problem_ids):
        return list(problem_ids)

    can_use_legacy_order = len(legacy_ids) == len(problem_ids)
    result: list[str] = []
    for index, (problem_id, stored_id) in enumerate(
        zip(problem_ids, stored_ids, strict=True)
    ):
        if stored_id:
            result.append(stored_id)
        elif can_use_legacy_order:
            result.append(legacy_ids[index])
        else:
            result.append(problem_id)
    return result


def normalize_problem_details(
    details: Mapping[str, Any] | None,
    problem_ids: Sequence[str],
    display_ids: Sequence[str],
) -> dict[str, Any]:
    """把一行每题成绩统一改成展示题号键。"""

    if not isinstance(details, Mapping):
        return {}
    if len(problem_ids) != len(display_ids):
        raise ValueError("比赛题号与展示题号数量不一致")

    normalized: dict[str, Any] = {}
    values = list(details.values())
    positional = len(values) == len(problem_ids)
    for index, (problem_id, display_id) in enumerate(
        zip(problem_ids, display_ids, strict=True)
    ):
        if display_id in details:
            normalized[display_id] = details[display_id]
        elif problem_id in details:
            normalized[display_id] = details[problem_id]
        elif positional:
            normalized[display_id] = values[index]
    return normalized
