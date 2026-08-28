from unittest.mock import AsyncMock, Mock, call

import pytest

from app.services import contest_archive
from app.tasks.actors import contest as contest_actors


@pytest.mark.asyncio
async def test_official_refresh_always_requests_fresh_profile(monkeypatch) -> None:
    """正式出分阶段不能复用一天内缓存，必须给榜内用户发联网任务。"""

    monkeypatch.setattr(
        contest_archive,
        "refresh_user_pending",
        AsyncMock(return_value=True),
    )
    send = Mock()
    monkeypatch.setattr(contest_actors.refresh_contest_user, "send", send)

    await contest_actors._prepare_refresh_user(100, 200, "official")

    send.assert_called_once_with(100, 200, "official", True)


@pytest.mark.asyncio
async def test_following_predictions_recalculate_without_intermediate_commit(
    monkeypatch,
) -> None:
    """后续比赛必须按时间顺序复用同一事务，不能逐场提前公开。"""

    session = object()
    calculate = AsyncMock()
    monkeypatch.setattr(contest_archive, "calculate_prediction", calculate)

    await contest_archive._recalculate_predictions_in_session(session, [11, 12, 13])

    assert calculate.await_args_list == [
        call(11, cascade=False, _session=session, _commit=False),
        call(12, cascade=False, _session=session, _commit=False),
        call(13, cascade=False, _session=session, _commit=False),
    ]
