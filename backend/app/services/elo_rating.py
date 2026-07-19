"""洛谷比赛等级分预测纯算法。

公式来自 ``test`` 目录中已经通过历史比赛回放的版本。该模块只负责数学计算，
不访问数据库和网络，便于单独测试。
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log2, sqrt
from typing import Sequence


WEIGHT_DECAY = 0.9
EXP_BASE = 2.0
EXP_SCALE = 800.0
RANK_BASE = 6.0
RANK_SCALE = 400.0
LOW_EVENT_PENALTY = 1200.0


@dataclass(frozen=True)
class RatingParticipant:
    """单个参赛者的预测输入。"""

    uid: int
    rank: float
    old_rating: int
    historical_perfs: Sequence[float] = ()
    historical_rating_rperfs: Sequence[float] | None = None
    historical_event_count: int | None = None
    rated: bool = True
    apperf: float | None = None


@dataclass(frozen=True)
class RatingPrediction:
    """单个参赛者的预测结果。"""

    uid: int
    performance: float
    rperf: float
    new_rating: int
    delta: int


def _weights(count: int) -> list[float]:
    return [WEIGHT_DECAY ** (index + 1) for index in range(count)]


def _event_penalty(count: int) -> float:
    """AtCoder 风格的低参赛次数惩罚项。"""

    if count <= 0:
        return 0.0
    weights = _weights(count)
    current = sqrt(sum(value * value for value in weights)) / sum(weights)
    infinite = (1 - WEIGHT_DECAY) / sqrt(1 - WEIGHT_DECAY**2)
    return LOW_EVENT_PENALTY * (current - infinite) / (1 - infinite)


def _exp_transform(value: float) -> float:
    return EXP_BASE ** (value / EXP_SCALE)


def _exp_inverse(value: float) -> float:
    if value <= 0:
        return -10_000.0
    return EXP_SCALE * log2(value)


def average_perf(perfs_latest_first: Sequence[float]) -> float:
    """计算排名模型使用的赛前平均表现。"""

    if not perfs_latest_first:
        return 0.0
    weights = _weights(len(perfs_latest_first))
    return sum(perf * weight for perf, weight in zip(perfs_latest_first, weights)) / sum(weights)


def rating_from_rperfs(rperfs_latest_first: Sequence[float], *, rounded: bool = True) -> int | float:
    """按洛谷低分截到 0 的规则合成公开 Rating。"""

    if not rperfs_latest_first:
        return 0 if rounded else 0.0
    weights = _weights(len(rperfs_latest_first))
    numerator = sum(
        _exp_transform(rperf) * weight
        for rperf, weight in zip(rperfs_latest_first, weights)
    )
    internal = _exp_inverse(numerator / sum(weights)) - _event_penalty(len(weights))
    result = max(0.0, internal)
    return round(result) if rounded else result


def update_positive_rating(old_rating: int, history_count: int, latest_rperf: float) -> int:
    """从正的公开 Rating 聚合状态增量加入一场 RPerf。"""

    if old_rating <= 0 or history_count <= 0:
        raise ValueError("旧等级分和历史场次必须为正数")
    old_weight_sum = sum(_weights(history_count))
    old_exp_average = _exp_transform(old_rating + _event_penalty(history_count))
    new_exp_average = (
        _exp_transform(latest_rperf) + old_exp_average * old_weight_sum
    ) / (1 + old_weight_sum)
    internal = _exp_inverse(new_exp_average) - _event_penalty(history_count + 1)
    return round(max(0.0, internal))


def infer_increment_rperf(old_rating: int, history_count: int, new_rating: int) -> float:
    """由相邻两次正 Rating 反推最新一场 RPerf。"""

    if old_rating <= 0 or new_rating <= 0 or history_count <= 0:
        raise ValueError("反推增量 RPerf 需要正 Rating 和正历史场次")
    old_weight_sum = sum(_weights(history_count))
    old_average = _exp_transform(old_rating + _event_penalty(history_count))
    new_average = _exp_transform(new_rating + _event_penalty(history_count + 1))
    return _exp_inverse(new_average * (1 + old_weight_sum) - old_average * old_weight_sum)


def infer_complete_rperfs(
    ratings_oldest_first: Sequence[int],
    *,
    zero_history_rperf: float | None,
) -> list[float]:
    """从包含 0 的完整公开 Rating 序列恢复近似 RPerf，返回最新在前。"""

    ratings = [int(value) for value in ratings_oldest_first]
    if not ratings:
        return []
    first_positive = next((i for i, value in enumerate(ratings) if value > 0), None)
    if first_positive is None:
        boundary = zero_history_rperf
        if boundary is None:
            boundary = _event_penalty(len(ratings))
        return [boundary] * len(ratings)

    first_count = first_positive + 1
    prefix_value = ratings[first_positive] + _event_penalty(first_count)
    oldest_first = [prefix_value] * first_count
    for index in range(first_count, len(ratings)):
        old_rating = ratings[index - 1]
        new_rating = ratings[index]
        if old_rating > 0 and new_rating > 0:
            rperf = infer_increment_rperf(old_rating, index, new_rating)
        elif new_rating > 0:
            rperf = new_rating + _event_penalty(index + 1)
        else:
            rperf = zero_history_rperf
            if rperf is None:
                rperf = _event_penalty(index + 1)
        oldest_first.append(rperf)
    return list(reversed(oldest_first))


def zero_history_default(history_count: int) -> float:
    """返回历史回放校准出的全零 Rating 近似 RPerf。"""

    if history_count <= 0:
        return 0.0
    if history_count == 1:
        return 575.0
    if history_count == 2:
        return 675.0
    if history_count == 3:
        return 400.0
    return 350.0


def infer_contest_center(contest_name: str, rated_bound: float) -> float:
    """按洛谷常规分级推断新人初始实力，未知赛制使用历史样本回退值。"""

    for division, expected_bound in (("Div.4", 1200), ("Div.3", 1600), ("Div.2", 2000)):
        if division in contest_name and abs(rated_bound - expected_bound) < 1e-9:
            return rated_bound - 600
    return 700.0


def _expected_ahead(performance: float, strengths: Sequence[float]) -> float:
    total = 0.0
    for strength in strengths:
        exponent = (performance - strength) / RANK_SCALE
        if exponent > 60:
            continue
        if exponent < -60:
            total += 1.0
            continue
        total += 1 / (1 + RANK_BASE**exponent)
    return total


def performance_from_rank(rank: float, strengths: Sequence[float]) -> float:
    """根据平均名次和全体赛前实力二分求本场表现分。"""

    if not strengths or rank < 1 or rank > len(strengths):
        raise ValueError("排名必须位于参与等级分评定的用户范围内")
    target = rank - 0.5
    low = min(strengths) - 5_000
    high = max(strengths) + 5_000
    for _ in range(50):
        middle = (low + high) / 2
        if _expected_ahead(middle, strengths) > target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def predict_contest(
    participants: Sequence[RatingParticipant],
    *,
    rated_bound: float,
    center: float,
) -> list[RatingPrediction]:
    """使用完整参赛池预测一场比赛。"""

    rated = [participant for participant in participants if participant.rated]
    if not rated:
        return []
    strengths = [
        participant.apperf
        if participant.apperf is not None and isfinite(participant.apperf)
        else (
            average_perf(participant.historical_perfs)
            if participant.historical_perfs
            else (float(participant.old_rating) if participant.old_rating > 0 else center)
        )
        for participant in rated
    ]
    by_rank: dict[float, float] = {}
    results: list[RatingPrediction] = []
    for participant in rated:
        history_count = (
            participant.historical_event_count
            if participant.historical_event_count is not None
            else len(participant.historical_perfs)
        )
        if participant.rank not in by_rank:
            by_rank[participant.rank] = performance_from_rank(participant.rank, strengths)
        performance = by_rank[participant.rank]
        rperf = min(performance, rated_bound + 400)
        if participant.old_rating > 0 and history_count > 0:
            new_rating = update_positive_rating(participant.old_rating, history_count, rperf)
        else:
            history = participant.historical_rating_rperfs
            if history is None:
                history = participant.historical_perfs
            new_rating = int(rating_from_rperfs([rperf, *history]))
        # 单场结算后的个人等级分不得超过本场等级分上限。
        new_rating = min(new_rating, int(rated_bound))
        results.append(
            RatingPrediction(
                uid=participant.uid,
                performance=performance,
                rperf=rperf,
                new_rating=new_rating,
                delta=new_rating - participant.old_rating,
            )
        )
    return results
