"""公开比赛 API 回归测试。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.api.v1.contest import user_rating_predictions
from app.models.contest import Contest, ContestArchiveStatus, ContestParticipant


class _Rows:
    def __init__(self, rows: list[tuple[ContestParticipant, Contest]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[ContestParticipant, Contest]]:
        return self._rows


class _Db:
    def __init__(self, rows: list[tuple[ContestParticipant, Contest]]) -> None:
        self._rows = rows

    async def execute(self, _statement) -> _Rows:  # noqa: ANN001
        return _Rows(self._rows)


def _row(
    contest_id: int,
    *,
    old_rating: int,
    predicted_rating: int,
    predicted_delta: int,
) -> tuple[ContestParticipant, Contest]:
    now = datetime(2026, 7, contest_id, tzinfo=timezone.utc)
    contest = Contest(
        id=contest_id,
        name=f"比赛 {contest_id}",
        start_time=now,
        end_time=now,
        rated_type=1,
        elo_threshold=2000,
        elo_done=False,
        status=ContestArchiveStatus.predicted,
        predicted_at=now,
    )
    participant = ContestParticipant(
        contest_id=contest_id,
        uid=123,
        rank_order=contest_id,
        score=500,
        is_penalized=False,
        old_rating=old_rating,
        predicted_rating=predicted_rating,
        predicted_delta=predicted_delta,
        warning_reasons=["测试提示"] if contest_id == 2 else None,
    )
    return participant, contest


async def test_user_rating_predictions_returns_summary_and_items() -> None:
    response = await user_rating_predictions(
        123,
        _Db(
            [
                _row(1, old_rating=1000, predicted_rating=1040, predicted_delta=40),
                _row(2, old_rating=1040, predicted_rating=1065, predicted_delta=25),
            ]
        ),
    )

    assert response.uid == 123
    assert response.count == 2
    assert response.latest_predicted_rating == 1065
    assert response.total_predicted_delta == 65
    assert response.items[1].warnings == ["测试提示"]


async def test_user_rating_predictions_returns_empty_payload() -> None:
    response = await user_rating_predictions(404, _Db([]))

    assert response.uid == 404
    assert response.count == 0
    assert response.latest_predicted_rating is None
    assert response.total_predicted_delta == 0
    assert response.items == []
