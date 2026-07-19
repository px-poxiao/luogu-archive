"""公开比赛排行榜 API。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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
from app.models.luogu_user import LuoguUser


router = APIRouter(tags=["contest"])
PUBLIC_STATUSES = {
    ContestArchiveStatus.refreshing_users,
    ContestArchiveStatus.predicted,
    ContestArchiveStatus.official,
}


class RatingPredictionItem(BaseModel):
    contest_id: int
    contest_name: str
    start_time: datetime
    end_time: datetime
    predicted_at: datetime
    rank: int
    score: float
    old_rating: int
    predicted_rating: int
    predicted_delta: int
    elo_threshold: int
    warnings: list[str]


class UserRatingPredictions(BaseModel):
    uid: int
    count: int
    latest_predicted_rating: int | None
    total_predicted_delta: int
    items: list[RatingPredictionItem]


def _status_text(contest: Contest) -> str:
    if not contest.is_elo_rated:
        return "不计等级分"
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


@router.get(
    "/user/{uid}/rating-predictions",
    response_model=UserRatingPredictions,
)
async def user_rating_predictions(
    uid: int,
    db: AsyncSession = Depends(get_db),
) -> UserRatingPredictions:
    """返回用户所有已预测、尚未正式结算的等级分记录。"""

    rows = (
        await db.execute(
            select(ContestParticipant, Contest)
            .join(Contest, Contest.id == ContestParticipant.contest_id)
            .where(
                ContestParticipant.uid == uid,
                ContestParticipant.is_penalized.is_(False),
                ContestParticipant.predicted_rating.is_not(None),
                ContestParticipant.official_rating.is_(None),
                Contest.status == ContestArchiveStatus.predicted,
                Contest.elo_done.is_(False),
                Contest.predicted_at.is_not(None),
                Contest.rated_type > 0,
                Contest.elo_threshold.is_not(None),
                Contest.elo_threshold > 0,
            )
            .order_by(Contest.end_time.asc(), Contest.id.asc())
        )
    ).all()

    items = [
        RatingPredictionItem(
            contest_id=contest.id,
            contest_name=contest.name,
            start_time=contest.start_time,
            end_time=contest.end_time,
            predicted_at=contest.predicted_at,
            rank=participant.rank_order,
            score=participant.score,
            old_rating=int(participant.old_rating or 0),
            predicted_rating=int(participant.predicted_rating),
            predicted_delta=int(participant.predicted_delta or 0),
            elo_threshold=int(contest.elo_threshold),
            warnings=[str(item) for item in (participant.warning_reasons or [])],
        )
        for participant, contest in rows
    ]
    return UserRatingPredictions(
        uid=uid,
        count=len(items),
        latest_predicted_rating=(items[-1].predicted_rating if items else None),
        total_predicted_delta=sum(item.predicted_delta for item in items),
        items=items,
    )


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
                "rated": item.is_elo_rated,
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
    # 复用用户主表中的最新展示资料，保证用户名、称号和认证标记与犇犇页一致。
    participants = (
        await db.execute(
            select(ContestParticipant, LuoguUser)
            .outerjoin(LuoguUser, LuoguUser.uid == ContestParticipant.uid)
            .where(*filters)
            .order_by(ContestParticipant.is_penalized.asc(), ContestParticipant.rank_order.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    problems = (
        await db.execute(
            select(ContestProblem)
            .where(ContestProblem.contest_id == contest_id)
            .order_by(ContestProblem.order_index)
        )
    ).scalars().all()

    rated = contest.is_elo_rated
    official = contest.status == ContestArchiveStatus.official
    show_rating = rated and (contest.predicted_at is not None or official)
    items = []
    for row, user in participants:
        rating = (row.official_rating if official else row.predicted_rating) if rated else None
        delta = (row.official_delta if official else row.predicted_delta) if rated else None
        warnings = row.warning_reasons or []
        if official and not row.is_penalized:
            warnings = []
        items.append(
            {
                "uid": row.uid,
                "name": user.name if user else row.name,
                "color": user.color.value if user else row.color.value,
                "avatar": user.avatar if user else row.avatar,
                "badge": user.badge if user else None,
                "ccf_level": user.ccf_level if user else 0,
                "xcpc_level": user.xcpc_level if user else 0,
                "is_admin": user.is_admin if user else False,
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
            "rating_mode": (
                "unrated"
                if not rated
                else "official"
                if official
                else "prediction"
                if show_rating
                else "loading"
            ),
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
