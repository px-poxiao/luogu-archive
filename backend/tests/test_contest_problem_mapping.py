"""比赛临时题号与正式题号映射回归测试。"""

from app.core.contest_problem_mapping import (
    align_problem_ids,
    normalize_problem_details,
    resolve_display_problem_ids,
    scoreboard_problem_ids,
)


def test_temporary_problem_ids_map_to_scoreboard_ids() -> None:
    temporary_ids = ["T783002", "T782491", "T784479", "T767475"]
    raw_details = {
        "P17169": {"score": 100, "runningTime": 2_607_000},
        "P17170": {"score": 100, "runningTime": 5_460_000},
        "P17171": {"score": 100, "runningTime": 10_018_000},
        "P17172": {"score": 36, "runningTime": 12_481_000},
    }

    extracted = scoreboard_problem_ids([{"details": raw_details}])
    assert extracted == ["P17169", "P17170", "P17171", "P17172"]

    # 旧归档没有持久化映射时，使用一条完整榜单记录恢复正式题号。
    display_ids = resolve_display_problem_ids(
        temporary_ids,
        [None, None, None, None],
        [raw_details],
    )
    assert display_ids == extracted

    normalized = normalize_problem_details(raw_details, temporary_ids, display_ids)
    assert [normalized[pid]["score"] for pid in display_ids] == [100, 100, 100, 36]


def test_unmatched_formal_ids_use_natural_order() -> None:
    display_ids = resolve_display_problem_ids(
        ["T1", "T2"],
        ["P20", "P10"],
        [{"P10": {}, "P20": {}}],
    )
    assert display_ids == ["P10", "P20"]


def test_same_problem_ids_keep_official_contest_order() -> None:
    """榜单 JSON 键即使乱序，也不能改变比赛页面定义的 A、B、C、D。"""

    official_ids = ["T765776", "T765416", "T758482", "T758107"]
    raw_details = {
        "T758107": {"score": 40},
        "T758482": {"score": 30},
        "T765416": {"score": 20},
        "T765776": {"score": 10},
    }

    # 模拟旧版本已经按 JSON 键顺序写入的错误映射。
    display_ids = resolve_display_problem_ids(
        official_ids,
        ["T765416", "T758107", "T758482", "T765776"],
        [raw_details],
    )
    assert display_ids == official_ids

    normalized = normalize_problem_details(raw_details, official_ids, display_ids)
    assert [normalized[pid]["score"] for pid in display_ids] == [10, 20, 30, 40]


def test_mixed_formal_and_temporary_ids_lock_exact_matches() -> None:
    """新比赛部分题目发布为正式号时，不能被榜单键顺序带偏。"""

    problem_ids = ["P17177", "P17178", "P17179", "T691524"]
    scoreboard_ids = ["P17178", "P17179", "P17180", "P17177"]

    display_ids = align_problem_ids(problem_ids, scoreboard_ids)
    assert display_ids == [
        "P17177",
        "P17178",
        "P17179",
        "P17180",
    ]

    raw_details = {
        "P17178": {"score": 20},
        "P17179": {"score": 30},
        "P17180": {"score": 40},
        "P17177": {"score": 10},
    }
    normalized = normalize_problem_details(raw_details, problem_ids, display_ids)
    assert [normalized[pid]["score"] for pid in display_ids] == [10, 20, 30, 40]
