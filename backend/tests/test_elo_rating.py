"""等级分生产公式回归测试。"""
from __future__ import annotations

from app.services.elo_rating import (
    RatingParticipant,
    infer_complete_rperfs,
    predict_contest,
)


def test_prediction_is_stable_for_mixed_histories() -> None:
    """正分、零分和新人同时参赛时应得到稳定结果。"""

    histories = [[1200, 1260, 1310], [0, 0], []]
    ranks = [1.0, 2.0, 3.0]
    old_ratings = [1310, 0, 0]
    inputs: list[RatingParticipant] = []
    for uid, (ratings, rank, old_rating) in enumerate(
        zip(histories, ranks, old_ratings), start=1
    ):
        inputs.append(
            RatingParticipant(
                uid=uid,
                rank=rank,
                old_rating=old_rating,
                historical_perfs=infer_complete_rperfs(
                    ratings, zero_history_rperf=None
                ),
                historical_rating_rperfs=infer_complete_rperfs(
                    ratings, zero_history_rperf=575.0
                ),
                historical_event_count=len(ratings),
            )
        )

    results = predict_contest(inputs, rated_bound=2000, center=1400)

    assert [result.uid for result in results] == [1, 2, 3]
    assert [result.new_rating for result in results] == [1435, 376, 0]
    assert [result.delta for result in results] == [125, 376, 0]


def test_new_rating_does_not_exceed_contest_bound() -> None:
    """高表现用户的新等级分也必须截断到本场上限。"""

    inputs = [
        RatingParticipant(
            uid=1,
            rank=1,
            old_rating=1999,
            historical_perfs=[4000],
            historical_event_count=1,
        ),
        RatingParticipant(
            uid=2,
            rank=2,
            old_rating=1900,
            historical_perfs=[3800],
            historical_event_count=1,
        ),
    ]

    results = predict_contest(inputs, rated_bound=2000, center=1400)

    assert [result.new_rating for result in results] == [2000, 2000]
    assert [result.delta for result in results] == [1, 100]
