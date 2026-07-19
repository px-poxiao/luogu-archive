"""比赛是否计等级分的字段兼容测试。"""
from __future__ import annotations

from app.core.contest_rating import is_elo_rated


def test_negative_elo_threshold_means_unrated() -> None:
    """洛谷即使返回 rated=1，阈值为 -1 时仍是不计等级分比赛。"""

    assert is_elo_rated(1, -1) is False


def test_non_negative_elo_threshold_means_rated() -> None:
    """存在有效阈值且 rated 标记开启时才进入等级分流程。"""

    assert is_elo_rated(1, 2000) is True


def test_missing_or_disabled_rated_flag_means_unrated() -> None:
    """缺少有效阈值或 rated 标记关闭时均不应启动预测。"""

    assert is_elo_rated(1, None) is False
    assert is_elo_rated(0, 2000) is False
