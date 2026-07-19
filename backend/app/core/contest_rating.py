"""比赛等级分字段的统一判定。"""
from __future__ import annotations


def is_elo_rated(rated_type: int, elo_threshold: int | None) -> bool:
    """判断洛谷比赛是否计等级分。

    洛谷会对部分不计等级分比赛返回 ``rated=1``，同时用
    ``eloThreshold=-1`` 表示不参与 Elo 结算，因此两个字段必须一起判断。
    """

    return rated_type > 0 and elo_threshold is not None and elo_threshold >= 0
