"""比赛归档、用户赛前快照、等级分预测与正式结算服务。"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select

from app.core.contest_problem_mapping import align_problem_ids, scoreboard_problem_ids
from app.core.db import db_session
from app.core.locks import DistributedLock
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

# 比赛结束后排行榜仍可能有少量结算延迟，统一等待五分钟再开始归档。
_CONTEST_ARCHIVE_GRACE = timedelta(minutes=5)
_CONTEST_DISPATCH_DEDUP_SEC = 15 * 60


def _to_datetime(value: int | float | None) -> datetime:
    if not value:
        return utcnow()
    return datetime.fromtimestamp(int(value), tz=UTC)


def _utc_datetime(value: datetime) -> datetime:
    """MySQL 可能返回无时区 datetime，统一按 UTC 补齐后再在 Python 中比较。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _safe_color(value: Any) -> LuoguColor:
    try:
        return LuoguColor(str(value))
    except ValueError:
        return LuoguColor.Gray


def _scoreboard_user_snapshot(user: dict[str, Any]) -> dict[str, Any] | None:
    """提取榜单展示需要的用户字段，过滤无效成员与无关主页数据。"""

    uid = user.get("uid")
    if not isinstance(uid, int):
        return None
    return {
        "uid": uid,
        "name": str(user.get("name") or uid),
        "color": _safe_color(user.get("color")).value,
        "avatar": user.get("avatar"),
        "badge": user.get("badge"),
        "ccf_level": int(user.get("ccfLevel") or 0),
        "xcpc_level": int(user.get("xcpcLevel") or 0),
        "is_admin": bool(user.get("isAdmin")),
    }


def normalize_scoreboard_squad(
    row: dict[str, Any],
    fallback_user: dict[str, Any],
) -> dict[str, Any] | None:
    """把洛谷 squad 统一为“队名 + 含队长的成员列表”。"""

    raw_squad = row.get("squad")
    if not isinstance(raw_squad, dict):
        return None

    leader = raw_squad.get("leader")
    if not isinstance(leader, dict):
        leader = fallback_user
    raw_members = raw_squad.get("members")
    candidates = [leader, *(raw_members if isinstance(raw_members, list) else [])]

    members: list[dict[str, Any]] = []
    seen_uids: set[int] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        member = _scoreboard_user_snapshot(candidate)
        if member is None or member["uid"] in seen_uids:
            continue
        seen_uids.add(member["uid"])
        members.append(member)
    if not members:
        return None

    raw_name = raw_squad.get("name")
    name = str(raw_name).strip() if raw_name is not None else ""
    if not name:
        name = f'{members[0]["name"]} 的小队'
    return {"name": name, "members": members}


def squad_search_text(squad: dict[str, Any] | None) -> str | None:
    """生成队伍搜索文本，使队名、成员名和成员 UID 都可直接搜索。"""

    if not squad:
        return None
    parts = [str(squad.get("name") or "")]
    for member in squad.get("members") or []:
        if isinstance(member, dict):
            parts.extend((str(member.get("name") or ""), str(member.get("uid") or "")))
    return " ".join(part for part in parts if part)[:1024]


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
    """保存比赛列表第一页，并尝试派发已超过等待期的比赛。"""

    from app.crawler.sources.contest import fetch_first_page

    rows = await fetch_first_page()
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
        await session.commit()

    return await dispatch_ready_contests()


async def dispatch_ready_contests() -> int:
    """按数据库中的截止时间派发比赛归档，不额外请求洛谷。

    每分钟运行一次，只处理结束至少五分钟的比赛。分布式锁用于避免比赛发现任务
    与定时到期检查在同一时刻重复派发。
    """

    from app.tasks.actors.contest import archive_contest

    redis = get_redis()
    lock = DistributedLock(redis)
    async with lock.guard("contest:archive_due_dispatch", ttl_sec=50) as got:
        if not got:
            return 0

        now = utcnow()
        archive_before = now - _CONTEST_ARCHIVE_GRACE
        # Broker 重启可能丢失消息但数据库仍是 queued；一并恢复已经失去进展的比赛，
        # 包括早已离开比赛列表第一页的记录。
        stale_queued_before = now - timedelta(minutes=15)
        stale_crawling_before = now - timedelta(hours=6)
        async with db_session() as session:
            archive_candidates = (
                await session.execute(
                    select(Contest).where(
                        Contest.end_time <= archive_before,
                        or_(
                            Contest.status.in_(
                                {
                                    ContestArchiveStatus.discovered,
                                    ContestArchiveStatus.failed,
                                }
                            ),
                            and_(
                                Contest.status == ContestArchiveStatus.queued,
                                Contest.updated_at <= stale_queued_before,
                            ),
                            and_(
                                Contest.status == ContestArchiveStatus.crawling,
                                Contest.updated_at <= stale_crawling_before,
                            ),
                        ),
                    )
                )
            ).scalars().all()
            ended_ids = []
            for contest in archive_candidates:
                if (
                    contest.status == ContestArchiveStatus.crawling
                    and await redis.exists(_scoreboard_heartbeat_key(contest.id))
                ):
                    continue
                ended_ids.append(contest.id)

        dispatched = 0
        for index, contest_id in enumerate(ended_ids):
            # 失败比赛只允许每十五分钟重新投递一次，避免 403 等错误每分钟制造死信。
            dispatch_key = f"contest:archive:dispatch:{contest_id}"
            if not await redis.set(
                dispatch_key,
                "1",
                ex=_CONTEST_DISPATCH_DEDUP_SEC,
                nx=True,
            ):
                continue
            # 归档任务自身受 cn 域名门限制；这里只做短暂错峰，不创建长延迟任务。
            try:
                if index == 0:
                    archive_contest.send(contest_id, "scheduled")
                else:
                    archive_contest.send_with_options(
                        args=(contest_id, "scheduled"),
                        delay=index * 1_000,
                    )
            except Exception as exc:
                # 保留原状态，让下一分钟的到期检查继续尝试派发。
                await redis.delete(dispatch_key)
                log.error(
                    "contest.archive_dispatch_failed",
                    contest_id=contest_id,
                    error=str(exc),
                )
                continue

            # 只有 broker 已接受消息后才写 queued；失败时保留原状态供下轮重试。
            async with db_session() as session:
                contest = await session.get(Contest, contest_id)
                if contest and contest.status in {
                    ContestArchiveStatus.discovered,
                    ContestArchiveStatus.failed,
                    ContestArchiveStatus.queued,
                }:
                    contest.status = ContestArchiveStatus.queued
                    await session.commit()
            dispatched += 1
        return dispatched


_CONTEST_PIPELINE_TTL_SEC = 7 * 24 * 3600
_SCOREBOARD_HEARTBEAT_TTL_SEC = 6 * 3600
_REFRESH_PROGRESS_TTL_SEC = 30 * 60


def _scoreboard_expected_key(contest_id: int) -> str:
    return f"contest:scoreboard:{contest_id}:expected"


def _scoreboard_done_key(contest_id: int) -> str:
    return f"contest:scoreboard:{contest_id}:done"


def _scoreboard_finalize_key(contest_id: int) -> str:
    return f"contest:scoreboard:{contest_id}:finalize"


def _scoreboard_heartbeat_key(contest_id: int) -> str:
    return f"contest:scoreboard:{contest_id}:heartbeat"


def _scoreboard_run_key(contest_id: int) -> str:
    return f"contest:scoreboard:{contest_id}:run"


def _refresh_counter_key(contest_id: int, phase: str) -> str:
    return f"contest:refresh:{contest_id}:{phase}"


def _refresh_done_key(contest_id: int, phase: str) -> str:
    return f"contest:refresh_done:{contest_id}:{phase}"


def _refresh_expected_key(contest_id: int, phase: str) -> str:
    return f"contest:refresh_expected:{contest_id}:{phase}"


def _refresh_heartbeat_key(contest_id: int, phase: str) -> str:
    return f"contest:refresh_heartbeat:{contest_id}:{phase}"


def _refresh_finalize_key(contest_id: int, phase: str) -> str:
    return f"contest:refresh_finalize:{contest_id}:{phase}"


async def _scoreboard_run_is_current(contest_id: int, run_id: str) -> bool:
    current = await get_redis().get(_scoreboard_run_key(contest_id))
    if isinstance(current, bytes):
        current = current.decode()
    return current == run_id


async def archive_one(
    contest_id: int,
    *,
    trigger: str = "scheduled",
    force: bool = False,
) -> None:
    """只抓比赛详情，然后派发第一页榜单任务。"""

    from app.crawler.sources.contest import fetch_detail
    from app.tasks.actors.contest import archive_contest_scoreboard_page

    async with db_session() as session:
        existing = await session.get(Contest, contest_id)
        if existing and not force:
            if existing.status == ContestArchiveStatus.crawling:
                if await get_redis().exists(_scoreboard_heartbeat_key(contest_id)):
                    return
            elif existing.status in {
                ContestArchiveStatus.refreshing_users,
                ContestArchiveStatus.predicted,
                ContestArchiveStatus.official,
            }:
                return
        if existing:
            existing.status = ContestArchiveStatus.crawling
            existing.error_message = None
            await session.commit()

    raw_contest, raw_problems = await fetch_detail(contest_id)
    end_time = _to_datetime(raw_contest.get("endTime"))
    if end_time + _CONTEST_ARCHIVE_GRACE > utcnow() and not force:
        async with db_session() as session:
            contest = await session.get(Contest, contest_id)
            if contest:
                contest.status = ContestArchiveStatus.discovered
                await session.commit()
        return

    run_id = uuid4().hex
    redis = get_redis()

    async with db_session() as session:
        contest = (
            await session.execute(
                select(Contest).where(Contest.id == contest_id).with_for_update()
            )
        ).scalar_one_or_none()
        await redis.set(
            _scoreboard_run_key(contest_id),
            run_id,
            ex=_CONTEST_PIPELINE_TTL_SEC,
        )
        await redis.set(
            _scoreboard_heartbeat_key(contest_id),
            run_id,
            ex=_SCOREBOARD_HEARTBEAT_TTL_SEC,
        )
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
        contest.participant_count = 0
        contest.raw_data = raw_contest
        contest.status = ContestArchiveStatus.crawling
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

        await session.commit()

    await redis.delete(
        _scoreboard_expected_key(contest_id),
        _scoreboard_done_key(contest_id),
        _scoreboard_finalize_key(contest_id),
    )
    archive_contest_scoreboard_page.send(contest_id, 1, trigger, run_id)


async def archive_scoreboard_page(
    contest_id: int,
    page: int,
    *,
    trigger: str,
    run_id: str,
) -> None:
    """抓取并幂等保存一页排行榜。"""

    from app.crawler.sources.contest import SCOREBOARD_PAGE_SIZE, fetch_scoreboard_page
    from app.tasks.actors.contest import archive_contest_scoreboard_page

    redis = get_redis()
    if not await _scoreboard_run_is_current(contest_id, run_id):
        return
    done_key = _scoreboard_done_key(contest_id)
    if await redis.sismember(done_key, page):
        return

    rows, meta = await fetch_scoreboard_page(contest_id, page)
    if not await _scoreboard_run_is_current(contest_id, run_id):
        return
    total = max(0, int(meta.get("count") or len(rows)))
    page_count = max(1, ceil(total / SCOREBOARD_PAGE_SIZE))
    offset = (page - 1) * SCOREBOARD_PAGE_SIZE
    scoreboard_pids = scoreboard_problem_ids(rows) if page == 1 else []
    valid_rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, row in enumerate(rows, start=1):
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        uid = user.get("uid")
        if isinstance(uid, int):
            valid_rows.append((offset + index, row, user))

    async with db_session() as session:
        contest = (
            await session.execute(
                select(Contest).where(Contest.id == contest_id).with_for_update()
            )
        ).scalar_one_or_none()
        if contest is None:
            raise ValueError(f"比赛 {contest_id} 尚未保存详情")
        if not await _scoreboard_run_is_current(contest_id, run_id):
            return
        uids = [int(user["uid"]) for _, _, user in valid_rows]
        existing_by_uid: dict[int, ContestParticipant] = {}
        if uids:
            existing = (
                await session.execute(
                    select(ContestParticipant).where(
                        ContestParticipant.contest_id == contest_id,
                        ContestParticipant.uid.in_(uids),
                    )
                )
            ).scalars().all()
            existing_by_uid = {int(item.uid): item for item in existing}

        for rank_order, row, user in valid_rows:
            uid = int(user["uid"])
            score = float(row.get("score") or 0)
            participant = existing_by_uid.get(uid)
            if participant is None:
                participant = ContestParticipant(contest_id=contest_id, uid=uid)
                session.add(participant)
            participant.name = str(user.get("name") or uid)
            participant.color = _safe_color(user.get("color"))
            participant.avatar = user.get("avatar")
            participant.rank_order = rank_order
            participant.rank_value = float(rank_order)
            participant.score = score
            participant.running_time = int(row.get("runningTime") or 0)
            participant.is_penalized = score < 0
            participant.problem_details = (
                row.get("details") if isinstance(row.get("details"), dict) else {}
            )
            participant.squad = normalize_scoreboard_squad(row, user)
            participant.squad_search_text = squad_search_text(participant.squad)
            participant.profile_status = "pending"
            participant.profile_source = None
            participant.profile_refreshed_at = None

        if page == 1:
            contest_problems = list(
                (
                    await session.execute(
                        select(ContestProblem)
                        .where(ContestProblem.contest_id == contest_id)
                        .order_by(ContestProblem.order_index)
                    )
                ).scalars().all()
            )
            # 只有题目数量完全一致时才按列持久化，避免缺题榜单产生错位映射。
            if len(scoreboard_pids) == len(contest_problems):
                problem_ids = [str(problem.pid) for problem in contest_problems]
                # details 的键顺序可能是参赛者的提交顺序。先锁定相同题号，
                # 再把临时题号对应的剩余正式题号按自然顺序补齐。
                scoreboard_pids = align_problem_ids(problem_ids, scoreboard_pids)
                for problem, scoreboard_pid in zip(
                    contest_problems,
                    scoreboard_pids,
                    strict=True,
                ):
                    raw_data = dict(problem.raw_data or {})
                    raw_data["scoreboardPid"] = scoreboard_pid
                    problem.raw_data = raw_data
            contest.participant_count = total
            raw_data = dict(contest.raw_data or {})
            raw_data["scoreboardMeta"] = meta
            contest.raw_data = raw_data
        contest.updated_at = utcnow()
        await session.commit()

    await redis.set(
        _scoreboard_heartbeat_key(contest_id),
        run_id,
        ex=_SCOREBOARD_HEARTBEAT_TTL_SEC,
    )

    if page == 1:
        expected_key = _scoreboard_expected_key(contest_id)
        await redis.set(expected_key, page_count, ex=_CONTEST_PIPELINE_TTL_SEC)
        for next_page in range(2, page_count + 1):
            archive_contest_scoreboard_page.send(
                contest_id,
                next_page,
                trigger,
                run_id,
            )

    await scoreboard_page_finished(contest_id, page, run_id)


async def scoreboard_page_finished(contest_id: int, page: int, run_id: str) -> None:
    """记录分页完成，并且只派发一次汇总任务。"""

    from app.tasks.actors.contest import finalize_contest_scoreboard

    redis = get_redis()
    if not await _scoreboard_run_is_current(contest_id, run_id):
        return
    done_key = _scoreboard_done_key(contest_id)
    added = await redis.sadd(done_key, page)
    await redis.expire(done_key, _CONTEST_PIPELINE_TTL_SEC)
    if not added:
        return
    expected_raw = await redis.get(_scoreboard_expected_key(contest_id))
    if expected_raw is None or await redis.scard(done_key) < int(expected_raw):
        return
    finalize_key = _scoreboard_finalize_key(contest_id)
    if await redis.set(finalize_key, "1", nx=True, ex=_CONTEST_PIPELINE_TTL_SEC):
        try:
            finalize_contest_scoreboard.send(contest_id, run_id)
        except Exception:
            await redis.delete(finalize_key)
            raise


async def finalize_scoreboard(contest_id: int, run_id: str) -> None:
    """全部榜单页落库后统一计算名次，并派发用户主页任务。"""

    if not await _scoreboard_run_is_current(contest_id, run_id):
        return

    async with db_session() as session:
        contest = (
            await session.execute(
                select(Contest).where(Contest.id == contest_id).with_for_update()
            )
        ).scalar_one_or_none()
        if contest is None:
            return
        if not await _scoreboard_run_is_current(contest_id, run_id):
            return
        participants = list(
            (
                await session.execute(
                    select(ContestParticipant)
                    .where(ContestParticipant.contest_id == contest_id)
                    .order_by(ContestParticipant.rank_order)
                )
            ).scalars().all()
        )
        rank_rows = [
            {"score": row.score, "user": {"uid": int(row.uid)}}
            for row in participants
        ]
        rank_values = _rank_values(rank_rows)
        participants.sort(key=lambda row: (row.is_penalized, row.rank_order))
        for display_index, participant in enumerate(participants, start=1):
            participant.rank_order = display_index
            participant.rank_value = rank_values.get(participant.uid, float(display_index))

        problem_count = await session.scalar(
            select(func.count(ContestProblem.id)).where(
                ContestProblem.contest_id == contest_id
            )
        )
        if not problem_count and participants:
            details = participants[0].problem_details or {}
            if isinstance(details, dict):
                for index, pid in enumerate(details):
                    session.add(
                        ContestProblem(
                            contest_id=contest_id,
                            pid=str(pid),
                            label=chr(ord("A") + index),
                            title="",
                            order_index=index,
                            raw_data={"pid": pid},
                        )
                    )

        contest.participant_count = len(participants)
        if contest.is_elo_rated:
            contest.status = ContestArchiveStatus.refreshing_users
        else:
            contest.status = ContestArchiveStatus.predicted
            contest.predicted_at = utcnow()
        contest.error_message = None
        is_elo_rated = contest.is_elo_rated
        phase = "official" if contest.elo_done else "prediction"
        await session.commit()

    if is_elo_rated:
        await enqueue_user_refresh(contest_id, phase=phase)
    if await _scoreboard_run_is_current(contest_id, run_id):
        await get_redis().delete(_scoreboard_heartbeat_key(contest_id))


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
    participant_uids = [int(uid) for uid in participants]
    key = _refresh_counter_key(contest_id, phase)
    done_key = _refresh_done_key(contest_id, phase)
    expected_key = _refresh_expected_key(contest_id, phase)
    heartbeat_key = _refresh_heartbeat_key(contest_id, phase)
    finalize_key = _refresh_finalize_key(contest_id, phase)
    redis = get_redis()
    await redis.delete(done_key, expected_key, finalize_key)
    if participant_uids:
        await redis.sadd(expected_key, *participant_uids)
        await redis.expire(expected_key, _CONTEST_PIPELINE_TTL_SEC)
    await redis.set(key, len(participant_uids), ex=_CONTEST_PIPELINE_TTL_SEC)
    await redis.set(heartbeat_key, "1", ex=_REFRESH_PROGRESS_TTL_SEC)
    if not participant_uids:
        await _finish_refresh_once(contest_id, phase)
        return 0
    dispatched = 0
    for uid in participant_uids:
        try:
            refresh_contest_user.send(contest_id, uid, phase)
            dispatched += 1
        except Exception as exc:
            log.error(
                "contest.user_refresh_dispatch_failed",
                contest_id=contest_id,
                uid=uid,
                phase=phase,
                error=str(exc),
            )
            await refresh_finished(contest_id, uid, phase)
    return dispatched


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


async def refresh_finished(contest_id: int, uid: int, phase: str) -> None:
    """记录单个用户完成，并按目标 UID 集合判断是否可以收口。"""

    redis = get_redis()
    key = _refresh_counter_key(contest_id, phase)
    done_key = _refresh_done_key(contest_id, phase)
    expected_key = _refresh_expected_key(contest_id, phase)
    heartbeat_key = _refresh_heartbeat_key(contest_id, phase)

    # 兼容部署前已经运行中的旧流水线；恢复任务会在无进展后把它升级为集合模式。
    if not await redis.exists(expected_key):
        if not await redis.exists(key):
            return
        if not await redis.sadd(done_key, uid):
            return
        await redis.expire(done_key, _CONTEST_PIPELINE_TTL_SEC)
        await redis.set(heartbeat_key, "1", ex=_REFRESH_PROGRESS_TTL_SEC)
        remaining = await redis.decr(key)
        if remaining <= 0:
            await _finish_refresh_once(contest_id, phase)
        return

    # 已被新一轮恢复移出目标集合的旧消息不应影响当前批次。
    if not await redis.sismember(expected_key, uid):
        return
    if not await redis.sadd(done_key, uid):
        return
    await redis.expire(done_key, _CONTEST_PIPELINE_TTL_SEC)
    await redis.set(heartbeat_key, "1", ex=_REFRESH_PROGRESS_TTL_SEC)
    expected_count = await redis.scard(expected_key)
    done_count = await redis.scard(done_key)
    remaining = max(0, expected_count - done_count)
    await redis.set(key, remaining, ex=_CONTEST_PIPELINE_TTL_SEC)
    if remaining <= 0:
        await _finish_refresh_once(contest_id, phase)


async def refresh_user_pending(contest_id: int, uid: int, phase: str) -> bool:
    """重复补发时，已经完成或不再属于当前目标集合的用户直接跳过。"""

    redis = get_redis()
    expected_key = _refresh_expected_key(contest_id, phase)
    if not await redis.exists(expected_key):
        return True
    return bool(
        await redis.sismember(expected_key, uid)
        and not await redis.sismember(_refresh_done_key(contest_id, phase), uid)
    )


async def recover_stalled_user_refresh(contest_id: int, phase: str) -> int:
    """无进展超时后重建目标集合，并且只补发尚未完成的用户。"""

    from app.tasks.actors.contest import refresh_contest_user

    redis = get_redis()
    heartbeat_key = _refresh_heartbeat_key(contest_id, phase)
    if await redis.exists(heartbeat_key):
        return 0

    lock_key = f"contest:refresh_recover:{contest_id}:{phase}"
    if not await redis.set(lock_key, "1", nx=True, ex=5 * 60):
        return 0
    try:
        async with db_session() as session:
            contest = await session.get(Contest, contest_id)
            if (
                contest is None
                or contest.status != ContestArchiveStatus.refreshing_users
                or ("official" if contest.elo_done else "prediction") != phase
            ):
                return 0
            participants = list(
                (
                    await session.execute(
                        select(ContestParticipant.uid).where(
                            ContestParticipant.contest_id == contest_id
                        )
                    )
                ).scalars().all()
            )

        await redis.set(heartbeat_key, "1", ex=_REFRESH_PROGRESS_TTL_SEC)
        expected_key = _refresh_expected_key(contest_id, phase)
        done_key = _refresh_done_key(contest_id, phase)
        temp_expected_key = f"{expected_key}:recover:{uuid4().hex}"
        participant_uids = [int(uid) for uid in participants]
        if participant_uids:
            await redis.sadd(temp_expected_key, *participant_uids)
            await redis.expire(temp_expected_key, _CONTEST_PIPELINE_TTL_SEC)
            await redis.rename(temp_expected_key, expected_key)
            if await redis.exists(done_key):
                await redis.sinterstore(done_key, done_key, expected_key)
                await redis.expire(done_key, _CONTEST_PIPELINE_TTL_SEC)
            missing = {int(uid) for uid in await redis.sdiff(expected_key, done_key)}
        else:
            await redis.delete(expected_key, done_key)
            missing = set()

        await redis.delete(_refresh_finalize_key(contest_id, phase))
        await redis.set(
            _refresh_counter_key(contest_id, phase),
            len(missing),
            ex=_CONTEST_PIPELINE_TTL_SEC,
        )
        if not missing:
            await _finish_refresh_once(contest_id, phase)
            return 0

        dispatched = 0
        for uid in missing:
            try:
                refresh_contest_user.send(contest_id, uid, phase)
                dispatched += 1
            except Exception as exc:
                log.error(
                    "contest.user_refresh_recovery_dispatch_failed",
                    contest_id=contest_id,
                    uid=uid,
                    phase=phase,
                    error=str(exc),
                )
                await refresh_finished(contest_id, uid, phase)
        log.warning(
            "contest.user_refresh_recovered",
            contest_id=contest_id,
            phase=phase,
            missing=len(missing),
            dispatched=dispatched,
        )
        return dispatched
    finally:
        await redis.delete(lock_key)


async def _finish_refresh_once(contest_id: int, phase: str) -> None:
    redis = get_redis()
    finalize_key = _refresh_finalize_key(contest_id, phase)
    if not await redis.set(finalize_key, "1", nx=True, ex=_CONTEST_PIPELINE_TTL_SEC):
        return
    try:
        await _finish_refresh(contest_id, phase)
    except Exception:
        await redis.delete(finalize_key)
        raise


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
                        Contest.elo_threshold > 0,
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
                        Contest.elo_threshold > 0,
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
