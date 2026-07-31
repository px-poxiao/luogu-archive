"""站点概览 API。"""
from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.admin import SiteAnnouncement
from app.models.luogu_content import Article, Feed, Judgement, Paste
from app.models.task import CrawlTask
from app.tasks.broker import get_broker

router = APIRouter(prefix="/site", tags=["site"])


class PublicAnnouncement(BaseModel):
    id: int
    title: str
    summary: str
    content: str
    published_at: datetime


@router.get("/announcements", response_model=list[PublicAnnouncement])
async def list_public_announcements(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[PublicAnnouncement]:
    q = (
        select(SiteAnnouncement)
        .where(SiteAnnouncement.is_published.is_(True))
        .order_by(desc(SiteAnnouncement.published_at), desc(SiteAnnouncement.id))
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        PublicAnnouncement(
            id=row.id,
            title=row.title,
            summary=row.summary,
            content=row.content,
            published_at=row.published_at,
        )
        for row in rows
        if row.published_at is not None
    ]


class SiteTotals(BaseModel):
    crawl_tasks: int
    articles: int
    pastes: int
    feeds: int
    judgements: int


class QueueInfo(BaseModel):
    key: str
    label: str
    size: int


class RecentTaskItem(BaseModel):
    id: int
    task_type: str
    target: str
    trigger: str
    status: str
    started_at: datetime


class SiteOverviewResp(BaseModel):
    generated_at: datetime
    totals: SiteTotals
    queues: list[QueueInfo]
    recent_tasks: list[RecentTaskItem]


async def _count(session: AsyncSession, model: type) -> int:
    value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def _queue_len(name: str) -> int:
    """读取资源队列的 pending 与 inflight 总数。"""

    try:
        return await asyncio.to_thread(get_broker().queue_size, name)
    except Exception:
        return 0


def _task_target(task_type: str, url: str) -> str:
    parsed = urlparse(url)
    path_tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    query = parse_qs(parsed.query)

    if task_type == "feed":
        user = query.get("user", [""])[0]
        page = query.get("page", [""])[0]
        if user and page:
            return f"user={user}, page={page}"
        if user:
            return f"user={user}"

    if task_type == "problem_list":
        page = query.get("page", [""])[0]
        if page:
            return f"page={page}"

    if task_type == "judgement":
        return "latest"

    return path_tail or url


@router.get("/overview", response_model=SiteOverviewResp)
async def site_overview(
    recent_limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> SiteOverviewResp:
    queue_defs = [
        ("crawler.hi", "高优先级"),
        ("crawler.mid", "常规爬取"),
        ("crawler.low", "低优先级"),
    ]

    recent_q = (
        select(CrawlTask)
        .order_by(desc(CrawlTask.started_at), desc(CrawlTask.id))
        .limit(recent_limit)
    )
    recent_rows = (await db.execute(recent_q)).scalars().all()

    return SiteOverviewResp(
        generated_at=datetime.now().astimezone(),
        totals=SiteTotals(
            crawl_tasks=await _count(db, CrawlTask),
            articles=await _count(db, Article),
            pastes=await _count(db, Paste),
            feeds=await _count(db, Feed),
            judgements=await _count(db, Judgement),
        ),
        queues=[
            QueueInfo(key=key, label=label, size=await _queue_len(key))
            for key, label in queue_defs
        ],
        recent_tasks=[
            RecentTaskItem(
                id=row.id,
                task_type=row.task_type,
                target=_task_target(row.task_type, row.url),
                trigger=row.triggered_by.value,
                status=row.status.value,
                started_at=row.started_at,
            )
            for row in recent_rows
        ],
    )


