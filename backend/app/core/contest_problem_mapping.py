"""比赛临时题号、正式题号与每题成绩的映射工具。"""

from __future__ import annotations

import re
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


def _problem_id_sort_key(pid: str) -> tuple[str, int, str]:
    """按题号前缀和数字自然排序，避免 P10 排在 P2 前面。"""

    matched = re.fullmatch(r"([A-Za-z]+)(\d+)", pid)
    if matched is None:
        return pid.casefold(), -1, pid
    return matched.group(1).casefold(), int(matched.group(2)), pid


def align_problem_ids(
    problem_ids: Sequence[str],
    candidate_ids: Sequence[str],
) -> list[str]:
    """把榜单题号集合对齐到比赛页面定义的 A、B、C 顺序。

    榜单 ``details`` 的键顺序可能取决于参赛者的提交顺序，不能作为列顺序。
    已经相同的正式题号先原位锁定；临时题号对应的剩余正式题号再自然排序填入。
    """

    normalized_problem_ids = [str(pid) for pid in problem_ids]
    normalized_candidate_ids = [str(pid) for pid in candidate_ids]
    if len(normalized_problem_ids) != len(normalized_candidate_ids):
        return normalized_candidate_ids

    # 题号必须一一对应。遇到重复键时保留候选顺序，避免凭空制造映射。
    if len(set(normalized_candidate_ids)) != len(normalized_candidate_ids):
        return normalized_candidate_ids

    remaining = set(normalized_candidate_ids)
    result: list[str | None] = [None] * len(normalized_problem_ids)
    for index, problem_id in enumerate(normalized_problem_ids):
        if problem_id in remaining:
            result[index] = problem_id
            remaining.remove(problem_id)

    unresolved = [index for index, pid in enumerate(result) if pid is None]
    ordered_remaining = sorted(remaining, key=_problem_id_sort_key)
    if len(unresolved) != len(ordered_remaining):
        return normalized_candidate_ids
    for index, candidate_id in zip(unresolved, ordered_remaining, strict=True):
        result[index] = candidate_id

    return [str(pid) for pid in result]


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
        return align_problem_ids(problem_ids, complete_stored_ids)

    if len(legacy_ids) == len(problem_ids):
        return align_problem_ids(problem_ids, legacy_ids)

    result: list[str] = []
    for index, (problem_id, stored_id) in enumerate(
        zip(problem_ids, stored_ids, strict=True)
    ):
        if stored_id:
            result.append(stored_id)
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
