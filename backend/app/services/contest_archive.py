"""比赛归档、用户赛前快照、等级分预测与正式结算服务。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select

from app.core.db import db_session
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.models._common import LuoguColor, utcnow
from app.models.contest import (
    Contest,
    ContestArchiveStatus,
    ContestParticipant,
    ContestProblem,
)
from app.models.luogu_content import Problem
from app.models.luogu_user import LuoguUser, UserEloHistory
from app.services.elo_rating import (
    RatingParticipant,
    compose_rating_history,
    infer_contest_center,
    predict_contest,
)


log = get_logger(__name__)


def _to_datetime(value: int | float | None) -> datetime:
    if not value:
        return utcnow()
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _utc_datetime(value: datetime) -> datetime:
    """MySQL 可能返回无时区 datetime，统一按 UTC 补齐后再在 Python 中比较。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _safe_color(value: Any) -> LuoguColor:
    try:
        return LuoguColor(str(value))
    except ValueError:
        return LuoguColor.Gray


def _rank_values(rows: list[dict[str, Any]]) -> dict[int, float]:
    """按洛谷 OI 榜规则计算并列平均名次，处罚行不合并。"""

    result: dict[int, float] = {}
    index = 0
    while index < len(rows):
        row = rows[index]
        score = row.get("score")
        user = row.get("user") if isinstance(row, dict) else None
        if isinstance(score, (int, float)) and score < 0:
            if isinstance(user, dict) and isinstance(user.get("uid"), int):
                result[int(user["uid"])] = float(index + 1)
            index += 1
            continue
        end = index + 1
        while end < len(rows) and rows[end].get("score") == score:
            end += 1
        average = ((index + 1) + end) / 2
        for same in rows[index:end]:
            same_user = same.get("user") if isinstance(same, dict) else None
            if isinstance(same_user, dict) and isinstance(same_user.get("uid"), int):
                result[int(same_user["uid"])] = average
        index = end
    return result


def _normalize_problem(item: dict[str, Any], index: int) -> tuple[str, str, str, dict] | None:
    problem = item.get("problem") if isinstance(item.get("problem"), dict) else item
    pid = problem.get("pid") or problem.get("id")
    if not isinstance(pid, str) or not pid:
        return None
    label = item.get("label") or item.get("displayId") or chr(ord("A") + index)
    title = problem.get("title") or problem.get("name") or ""
    return pid, str(label), str(title), item


async def discover_first_page() -> int:
    """保存比赛列表第一页，并派发刚结束比赛的归档任务。"""

    from app.crawler.sources.contest import fetch_first_page
    from app.tasks.actors.contest import archive_contest

    rows = await fetch_first_page()
    now = utcnow()
    ended_ids: list[int] = []
    async with db_session() as session:
        for raw in rows:
            contest_id = raw.get("id")
            if not isinstance(contest_id, int):
                continue
            contest = await session.get(Contest, contest_id)
            if contest is None:
                contest = Contest(
                    id=contest_id,
                    name=str(raw.get("name") or contest_id),
                    start_time=_to_datetime(raw.get("startTime")),
                    end_time=_to_datetime(raw.get("endTime")),
                    method=raw.get("method"),
                    rated_type=int(raw.get("rated") or 0),
                    elo_threshold=raw.get("eloThreshold"),
                    elo_done=bool(raw.get("eloDone")),
                    problem_count=int(raw.get("problemCount") or 0),
                    participant_count=int(raw.get("totalParticipants") or 0),
                    status=ContestArchiveStatus.discovered,
                    raw_data=raw,
                )
                session.add(contest)
            elif contest.status == ContestArchiveStatus.discovered:
                contest.name = str(raw.get("name") or contest.name)
                contest.start_time = _to_datetime(raw.get("startTime"))
                contest.end_time = _to_datetime(raw.get("endTime"))
                contest.raw_data = raw
            if _utc_datetime(contest.end_time) <= now and contest.status in {
                ContestArchiveStatus.discovered,
                ContestArchiveStatus.failed,
            }:
                contest.status = ContestArchiveStatus.queued
                ended_ids.append(contest_id)
        await session.commit()

    for index, contest_id in enumerate(ended_ids):
        # 归档任务自身受 cn 域名门限制；这里稍微错峰，避免同一刻堆入 worker。
        archive_contest.send_with_options(args=(contest_id, "scheduled"), delay=index * 1_000)
    return len(ended_ids)


async def archive_one(contest_id: int, *, force: bool = False) -> None:
    """抓比赛详情和完整榜单，并开始唯一一次赛前用户刷新。"""

    from app.crawler.sources.contest import fetch_detail, fetch_scoreboard

    async with db_session() as session:
        existing = await session.get(Contest, contest_id)
        if existing and existing.status in {
            ContestArchiveStatus.crawling,
            ContestArchiveStatus.refreshing_users,
        } and not force:
            return
        if existing:
            existing.status = ContestArchiveStatus.crawling
            existing.error_message = None
            await session.commit()

    raw_contest, raw_problems = await fetch_detail(contest_id)
    end_time = _to_datetime(raw_contest.get("endTime"))
    if end_time > utcnow() and not force:
        async with db_session() as session:
            contest = await session.get(Contest, contest_id)
            if contest:
                contest.status = ContestArchiveStatus.discovered
                await session.commit()
        return
    scoreboard, scoreboard_meta = await fetch_scoreboard(contest_id)
    ranks = _rank_values(scoreboard)

    # 处罚用户按产品约定统一移到榜单末尾。
    ordered_rows = sorted(
        enumerate(scoreboard),
        key=lambda pair: (float(pair[1].get("score") or 0) < 0, pair[0]),
    )

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest is None:
            contest = Contest(
                id=contest_id,
                name=str(raw_contest.get("name") or contest_id),
                start_time=_to_datetime(raw_contest.get("startTime")),
                end_time=end_time,
            )
            session.add(contest)
        contest.name = str(raw_contest.get("name") or contest.name)
        contest.start_time = _to_datetime(raw_contest.get("startTime"))
        contest.end_time = end_time
        contest.method = raw_contest.get("method")
        contest.rated_type = int(raw_contest.get("rated") or 0)
        contest.elo_threshold = raw_contest.get("eloThreshold")
        contest.elo_done = bool(raw_contest.get("eloDone"))
        contest.problem_count = int(raw_contest.get("problemCount") or 0)
        contest.participant_count = len(scoreboard)
        contest.raw_data = {**raw_contest, "scoreboardMeta": scoreboard_meta}
        contest.error_message = None

        await session.execute(delete(ContestProblem).where(ContestProblem.contest_id == contest_id))
        await session.execute(
            delete(ContestParticipant).where(ContestParticipant.contest_id == contest_id)
        )

        normalized = [
            value
            for index, item in enumerate(raw_problems)
            if (value := _normalize_problem(item, index)) is not None
        ]
        if not normalized and scoreboard:
            details = scoreboard[0].get("details") or {}
            if isinstance(details, dict):
                normalized = [
                    (str(pid), chr(ord("A") + index), "", {"pid": pid})
                    for index, pid in enumerate(details.keys())
                ]
        pids = [item[0] for item in normalized]
        known_titles: dict[str, str] = {}
        if pids:
            problem_rows = await session.execute(select(Problem.pid, Problem.title).where(Problem.pid.in_(pids)))
            known_titles = {pid: title for pid, title in problem_rows.all()}
        for index, (pid, label, title, raw) in enumerate(normalized):
            session.add(
                ContestProblem(
                    contest_id=contest_id,
                    pid=pid,
                    label=label,
                    title=title or known_titles.get(pid, ""),
                    order_index=index,
                    raw_data=raw,
                )
            )

        for display_index, (_, row) in enumerate(ordered_rows, start=1):
            user = row.get("user") if isinstance(row.get("user"), dict) else {}
            uid = user.get("uid")
            if not isinstance(uid, int):
                continue
            score = float(row.get("score") or 0)
            session.add(
                ContestParticipant(
                    contest_id=contest_id,
                    uid=uid,
                    name=str(user.get("name") or uid),
                    color=_safe_color(user.get("color")),
                    avatar=user.get("avatar"),
                    rank_order=display_index,
                    rank_value=ranks.get(uid, float(display_index)),
                    score=score,
                    running_time=int(row.get("runningTime") or 0),
                    is_penalized=score < 0,
                    problem_details=row.get("details") if isinstance(row.get("details"), dict) else {},
                    profile_status="pending",
                )
            )

        # 不计算等级分的比赛只归档排行榜，不产生用户刷新流量。
        if not contest.is_elo_rated:
            contest.status = ContestArchiveStatus.predicted
            contest.predicted_at = utcnow()
        else:
            contest.status = ContestArchiveStatus.refreshing_users
        await session.commit()

    # ``eloThreshold = -1`` 是洛谷对不计等级分比赛使用的哨兵值。
    elo_threshold = raw_contest.get("eloThreshold")
    if (
        raw_contest.get("rated")
        and isinstance(elo_threshold, (int, float))
        and elo_threshold >= 0
    ):
        phase = "official" if bool(raw_contest.get("eloDone")) else "prediction"
        await enqueue_user_refresh(contest_id, phase=phase)


async def enqueue_user_refresh(contest_id: int, *, phase: str) -> int:
    """为一场比赛派发一次全量用户主页刷新。"""

    from app.tasks.actors.contest import refresh_contest_user

    async with db_session() as session:
        participants = (
            await session.execute(
                select(ContestParticipant.uid)
                .where(ContestParticipant.contest_id == contest_id)
                .order_by(ContestParticipant.rank_order)
            )
        ).scalars().all()
    key = f"contest:refresh:{contest_id}:{phase}"
    redis = get_redis()
    await redis.set(key, len(participants), ex=24 * 3600)
    if not participants:
        await _finish_refresh(contest_id, phase)
        return 0
    for index, uid in enumerate(participants):
        refresh_contest_user.send_with_options(
            args=(contest_id, int(uid), phase),
            delay=index * 1_000,
        )
    return len(participants)


async def snapshot_user(contest_id: int, uid: int, *, profile_source: str) -> None:
    """把档案馆中目标比赛前的 Rating 状态固化到排行榜行。"""

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        participant = (
            await session.execute(
                select(ContestParticipant).where(
                    ContestParticipant.contest_id == contest_id,
                    ContestParticipant.uid == uid,
                )
            )
        ).scalar_one_or_none()
        if contest is None or participant is None:
            return
        user = await session.get(LuoguUser, uid)
        all_events = (
            await session.execute(
                select(UserEloHistory)
                .where(UserEloHistory.uid == uid)
                .order_by(UserEloHistory.contest_end_time.asc(), UserEloHistory.time.asc())
            )
        ).scalars().all()
        previous = [
            event for event in all_events
            if event.contest_id != contest_id
            and (event.contest_end_time or event.time) < contest.start_time
        ]
        later_count = sum(
            1 for event in all_events
            if event.contest_id == contest_id
            or (event.contest_end_time or event.time) >= contest.start_time
        )
        total_hint = max(
            [int(event.user_count or 0) for event in all_events] or [0]
        )
        expected_count = max(len(previous), total_hint - later_count)

        if user is None and not previous:
            participant.profile_status = "failed"
            participant.profile_source = None
            participant.warning_reasons = ["用户主页与档案馆缓存均不可用"]
        else:
            old_rating = int(previous[-1].rating) if previous else 0
            participant.old_rating = old_rating
            participant.history_count = expected_count
            participant.profile_status = "success"
            participant.profile_source = profile_source
            participant.profile_refreshed_at = (
                utcnow() if profile_source == "fresh" else user.last_crawled_at if user else None
            )
        await session.commit()


async def refresh_finished(contest_id: int, phase: str) -> None:
    """单个用户任务结束后递减计数，最后一个任务负责收口。"""

    redis = get_redis()
    key = f"contest:refresh:{contest_id}:{phase}"
    remaining = await redis.decr(key)
    if remaining <= 0:
        await redis.delete(key)
        await _finish_refresh(contest_id, phase)


async def _finish_refresh(contest_id: int, phase: str) -> None:
    from app.tasks.actors.contest import calculate_contest_prediction, finalize_contest_official

    if phase == "official":
        finalize_contest_official.send(contest_id)
    else:
        calculate_contest_prediction.send(contest_id)


async def calculate_prediction(contest_id: int, *, cascade: bool = True) -> None:
    """读取赛前快照并生成唯一一版公开预测。"""

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest is None or not contest.is_elo_rated:
            return
        participants = (
            await session.execute(
                select(ContestParticipant)
                .where(ContestParticipant.contest_id == contest_id)
                .order_by(ContestParticipant.rank_order)
            )
        ).scalars().all()
        threshold = int(contest.elo_threshold)
        history_by_uid: dict[int, list[UserEloHistory]] = defaultdict(list)
        predicted_history_by_uid: dict[int, list[ContestParticipant]] = defaultdict(list)
        participant_uids = [row.uid for row in participants]
        if participant_uids:
            history_events = (
                await session.execute(
                    select(UserEloHistory)
                    .where(
                        UserEloHistory.uid.in_(participant_uids),
                        UserEloHistory.contest_id != contest_id,
                    )
                    .order_by(
                        UserEloHistory.uid,
                        UserEloHistory.contest_end_time.asc(),
                        UserEloHistory.time.asc(),
                    )
                )
            ).scalars().all()
            for event in history_events:
                if (event.contest_end_time or event.time) <= contest.start_time:
                    history_by_uid[int(event.uid)].append(event)

            # 前序比赛尚未正式结算时，使用其预测结果组成临时历史。
            previous_predictions = (
                await session.execute(
                    select(ContestParticipant, Contest)
                    .join(Contest, Contest.id == ContestParticipant.contest_id)
                    .where(
                        ContestParticipant.uid.in_(participant_uids),
                        ContestParticipant.contest_id != contest_id,
                        ContestParticipant.is_penalized.is_(False),
                        ContestParticipant.predicted_rating.is_not(None),
                        ContestParticipant.rperf.is_not(None),
                        Contest.status == ContestArchiveStatus.predicted,
                        Contest.rated_type > 0,
                        Contest.elo_threshold >= 0,
                        Contest.elo_threshold.is_not(None),
                        Contest.end_time <= contest.start_time,
                    )
                    .order_by(
                        ContestParticipant.uid,
                        Contest.end_time.asc(),
                        Contest.id.asc(),
                    )
                )
            ).all()
            official_ids_by_uid = {
                uid: {int(event.contest_id) for event in events}
                for uid, events in history_by_uid.items()
            }
            for previous_row, _previous_contest in previous_predictions:
                if previous_row.contest_id in official_ids_by_uid.get(previous_row.uid, set()):
                    continue
                predicted_history_by_uid[int(previous_row.uid)].append(previous_row)

        calculation_by_uid = {}
        for row in participants:
            history_rows = history_by_uid.get(row.uid, [])
            ratings = [int(event.rating) for event in history_rows]
            predicted_rows = predicted_history_by_uid.get(row.uid, [])
            calculation_by_uid[row.uid] = compose_rating_history(
                ratings,
                history_count=int(row.history_count or 0),
                fallback_old_rating=int(row.old_rating or 0),
                predicted_results_oldest_first=[
                    (int(previous.predicted_rating), float(previous.rperf))
                    for previous in predicted_rows
                ],
            )

        eligible = [
            row for row in participants
            if not row.is_penalized
            and calculation_by_uid[row.uid].old_rating < threshold
        ]
        # 只在实际参与等级分计算的池内重新计算并列平均名次。
        eligible_rank: dict[int, float] = {}
        index = 0
        while index < len(eligible):
            end = index + 1
            while end < len(eligible) and eligible[end].score == eligible[index].score:
                end += 1
            average = ((index + 1) + end) / 2
            for row in eligible[index:end]:
                eligible_rank[row.uid] = average
            index = end

        inputs: list[RatingParticipant] = []
        for row in eligible:
            calculation = calculation_by_uid[row.uid]
            inputs.append(
                RatingParticipant(
                    uid=row.uid,
                    rank=eligible_rank[row.uid],
                    old_rating=calculation.old_rating,
                    historical_perfs=calculation.historical_perfs,
                    historical_rating_rperfs=calculation.historical_rating_rperfs,
                    historical_event_count=calculation.count,
                )
            )

        center = infer_contest_center(contest.name, threshold)
        predictions = {
            item.uid: item
            for item in predict_contest(inputs, rated_bound=threshold, center=center)
        }
        for row in participants:
            calculation = calculation_by_uid[row.uid]
            old_rating = calculation.old_rating
            history_count = calculation.count
            warnings: list[str] = []
            if row.is_penalized:
                row.predicted_rating = None
                row.predicted_delta = None
                row.performance = None
                row.rperf = None
                row.warning_reasons = ["该参赛记录已被处罚，不参与等级分预测"]
                continue
            if old_rating >= threshold:
                row.predicted_rating = old_rating
                row.predicted_delta = 0
                row.performance = None
                row.rperf = None
                row.warning_reasons = ["赛前等级分不低于本场等级分阈值"]
                continue
            prediction = predictions.get(row.uid)
            if row.profile_status != "success" or prediction is None:
                row.predicted_rating = None
                row.predicted_delta = None
                row.performance = None
                row.rperf = None
                row.warning_reasons = row.warning_reasons or ["用户等级分数据不可用"]
                continue
            if history_count <= 5:
                warnings.append("参赛场次不超过 5 场，预测误差可能较大")
            if old_rating == 0:
                warnings.append("赛前公开等级分为 0，内部实力无法唯一反推")
            if history_count > calculation.known_count:
                warnings.append("部分早期等级分历史未公开，使用等效历史近似")
            if calculation.predicted_count:
                warnings.append(
                    "\u8d5b\u524d\u7b49\u7ea7\u5206\u5305\u542b\u524d\u5e8f\u6bd4\u8d5b\u9884\u6d4b\uff0c"
                    "\u524d\u5e8f\u6bd4\u8d5b\u6b63\u5f0f\u7ed3\u7b97\u540e\u5c06\u81ea\u52a8\u8c03\u6574"
                )
            if row.profile_source == "cache":
                warnings.append("用户主页刷新失败，本结果使用档案馆缓存")
            row.predicted_rating = prediction.new_rating
            row.predicted_delta = prediction.delta
            row.performance = prediction.performance
            row.rperf = prediction.rperf
            row.warning_reasons = warnings or None

        contest.status = ContestArchiveStatus.predicted
        contest.predicted_at = utcnow()
        contest.error_message = None
        await session.commit()

    if cascade:
        await recalculate_following_predictions(contest_id)


async def recalculate_following_predictions(contest_id: int) -> int:
    """前序预测或正式结果变化后，按时间顺序重算后续比赛。"""

    async with db_session() as session:
        anchor = await session.get(Contest, contest_id)
        if anchor is None:
            return 0
        following_ids = list(
            (
                await session.execute(
                    select(Contest.id)
                    .where(
                        Contest.id != contest_id,
                        Contest.status == ContestArchiveStatus.predicted,
                        Contest.rated_type > 0,
                        Contest.elo_threshold >= 0,
                        Contest.elo_threshold.is_not(None),
                        Contest.start_time >= anchor.end_time,
                    )
                    .order_by(Contest.start_time.asc(), Contest.end_time.asc(), Contest.id.asc())
                )
            ).scalars().all()
        )

    for following_id in following_ids:
        await calculate_prediction(int(following_id), cascade=False)
    return len(following_ids)


async def detect_official_from_user(contest_id: int, uid: int) -> bool:
    """检查某个用户历史中是否已经出现目标比赛。"""

    async with db_session() as session:
        count = await session.scalar(
            select(func.count(UserEloHistory.id)).where(
                UserEloHistory.uid == uid,
                UserEloHistory.contest_id == contest_id,
            )
        )
        return bool(count)


async def official_probe_uids(contest_id: int) -> list[int]:
    """返回阈值内排名最前的 20 名，供每小时结算探测。"""

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest is None or not contest.is_elo_rated:
            return []
        return list(
            (
                await session.execute(
                    select(ContestParticipant.uid)
                    .where(
                        ContestParticipant.contest_id == contest_id,
                        ContestParticipant.is_penalized.is_(False),
                        ContestParticipant.old_rating.is_not(None),
                        ContestParticipant.old_rating < contest.elo_threshold,
                    )
                    .order_by(ContestParticipant.rank_order)
                    .limit(20)
                )
            ).scalars().all()
        )


async def begin_official_refresh(contest_id: int) -> None:
    """正式结算被探测到后派发最后一次全量用户刷新。"""

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if (
            contest is None
            or not contest.is_elo_rated
            or contest.status == ContestArchiveStatus.official
        ):
            return
        contest.elo_done = True
        contest.status = ContestArchiveStatus.refreshing_users
        await session.commit()
    await enqueue_user_refresh(contest_id, phase="official")


async def finalize_official(contest_id: int) -> None:
    """使用正式历史替换公开预测结果。"""

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest is None or not contest.is_elo_rated:
            return
        participants = (
            await session.execute(
                select(ContestParticipant).where(ContestParticipant.contest_id == contest_id)
            )
        ).scalars().all()
        event_by_uid: dict[int, UserEloHistory] = {}
        if participants:
            official_events = (
                await session.execute(
                    select(UserEloHistory).where(
                        UserEloHistory.contest_id == contest_id,
                        UserEloHistory.uid.in_([row.uid for row in participants]),
                    )
                )
            ).scalars().all()
            event_by_uid = {int(event.uid): event for event in official_events}
        for row in participants:
            event = event_by_uid.get(row.uid)
            old_rating = int(row.old_rating or 0)
            if event is None:
                row.official_rating = old_rating
                row.official_delta = 0
            else:
                row.official_rating = int(event.rating)
                if event.previous_rating is not None:
                    old_rating = int(event.previous_rating)
                    row.old_rating = old_rating
                elif event.prev_diff is not None:
                    old_rating = int(event.rating) - int(event.prev_diff)
                    row.old_rating = old_rating
                row.official_delta = int(event.rating) - old_rating
        contest.status = ContestArchiveStatus.official
        contest.elo_done = True
        contest.official_at = utcnow()
        contest.error_message = None
        await session.commit()

    await recalculate_following_predictions(contest_id)


async def mark_failed(contest_id: int, error: Exception) -> None:
    """记录比赛任务失败，管理员可从后台重新派发。"""

    async with db_session() as session:
        contest = await session.get(Contest, contest_id)
        if contest:
            contest.status = ContestArchiveStatus.failed
            contest.error_message = str(error)[:512]
            await session.commit()
