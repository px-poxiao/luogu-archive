"""比赛临时题号与正式题号映射回归测试。"""

from app.core.contest_problem_mapping import (
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


def test_stored_mapping_has_priority_over_legacy_sample() -> None:
    display_ids = resolve_display_problem_ids(
        ["T1", "T2"],
        ["P20", "P10"],
        [{"P10": {}, "P20": {}}],
    )
    assert display_ids == ["P20", "P10"]


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
