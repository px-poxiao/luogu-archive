"""公开比赛排行榜 API。"""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.models._common import utcnow
from app.models.contest import (
    Contest,
    ContestArchiveStatus,
    ContestParticipant,
    ContestProblem,
)


router = APIRouter(tags=["contest"])
PUBLIC_STATUSES = {
    ContestArchiveStatus.refreshing_users,
    ContestArchiveStatus.predicted,
    ContestArchiveStatus.official,
}


def _status_text(contest: Contest) -> str:
    if contest.status == ContestArchiveStatus.official:
        return "正式结果"
    if contest.predicted_at is not None:
        return "预测完成"
    return "计算中"


def _has_ended(contest: Contest) -> bool:
    """兼容 MySQL 返回的无时区 UTC 时间。"""

    end_time = contest.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    return end_time <= utcnow()


@router.get("/contests")
async def list_contests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    q: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按结束时间倒序返回已结束且已进入归档流程的比赛。"""

    filters = [Contest.end_time <= utcnow(), Contest.status.in_(PUBLIC_STATUSES)]
    if q and q.strip():
        keyword = q.strip()
        if keyword.isdigit():
            filters.append(or_(Contest.id == int(keyword), Contest.name.contains(keyword)))
        else:
            filters.append(Contest.name.contains(keyword))
    total = int(await db.scalar(select(func.count(Contest.id)).where(*filters)) or 0)
    contests = (
        await db.execute(
            select(Contest)
            .where(*filters)
            .order_by(Contest.end_time.desc(), Contest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "problem_count": item.problem_count,
                "participant_count": item.participant_count,
                "rated": item.rated_type > 0 and item.elo_threshold is not None,
                "status": _status_text(item),
            }
            for item in contests
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/contest/{contest_id}")
async def contest_scoreboard(
    contest_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    q: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回一场比赛的公开排行榜，搜索范围覆盖整场。"""

    contest = await db.get(Contest, contest_id)
    if (
        contest is None
        or not _has_ended(contest)
        or contest.status not in PUBLIC_STATUSES
    ):
        raise NotFoundError("比赛尚未归档或不存在")

    filters = [ContestParticipant.contest_id == contest_id]
    if q and q.strip():
        keyword = q.strip()
        if keyword.isdigit():
            filters.append(
                or_(
                    ContestParticipant.uid == int(keyword),
                    ContestParticipant.name.contains(keyword),
                )
            )
        else:
            filters.append(ContestParticipant.name.contains(keyword))
    total = int(
        await db.scalar(select(func.count(ContestParticipant.id)).where(*filters)) or 0
    )
    participants = (
        await db.execute(
            select(ContestParticipant)
            .where(*filters)
            .order_by(ContestParticipant.is_penalized.asc(), ContestParticipant.rank_order.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    problems = (
        await db.execute(
            select(ContestProblem)
            .where(ContestProblem.contest_id == contest_id)
            .order_by(ContestProblem.order_index)
        )
    ).scalars().all()

    rated = contest.rated_type > 0 and contest.elo_threshold is not None
    official = contest.status == ContestArchiveStatus.official
    show_rating = rated and (contest.predicted_at is not None or official)
    items = []
    for row in participants:
        rating = row.official_rating if official else row.predicted_rating
        delta = row.official_delta if official else row.predicted_delta
        warnings = row.warning_reasons or []
        if official and not row.is_penalized:
            warnings = []
        items.append(
            {
                "uid": row.uid,
                "name": row.name,
                "color": row.color.value,
                "avatar": row.avatar,
                "rank": row.rank_order,
                "score": row.score,
                "running_time": row.running_time,
                "penalized": row.is_penalized,
                "problem_details": row.problem_details or {},
                "rating": rating if show_rating else None,
                "delta": delta if show_rating else None,
                "rating_pending": rated and not show_rating,
                "warnings": warnings,
            }
        )
    return {
        "contest": {
            "id": contest.id,
            "name": contest.name,
            "start_time": contest.start_time,
            "end_time": contest.end_time,
            "problem_count": contest.problem_count or len(problems),
            "participant_count": contest.participant_count,
            "rated": rated,
            "rating_mode": "official" if official else ("prediction" if show_rating else "loading"),
            "status": _status_text(contest),
        },
        "problems": [
            {"pid": item.pid, "label": item.label, "title": item.title}
            for item in problems
        ],
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
