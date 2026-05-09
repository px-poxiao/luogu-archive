"""内容查询 API —— 文章、剪贴板、陶片、伪全网犇、题目列表。

所有 GET 端点都做 stale-while-revalidate（数据过期时异步重爬，不阻塞）。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.crawler.revalidate import (
    is_stale,
    schedule_refresh_article,
    schedule_refresh_paste,
)
from app.models.luogu_content import (
    Article,
    ArticleVersion,
    Feed,
    Judgement,
    Paste,
    PasteVersion,
    Problem,
)
from app.models.luogu_user import LuoguUser

router = APIRouter(tags=["content"])


# ============================================================
# Schemas
# ============================================================

class _UserBrief(BaseModel):
    uid: int
    name: str
    color: str
    badge: str | None
    avatar: str | None


class ArticleDetail(BaseModel):
    article_id: str
    title: str
    content_md: str
    author: _UserBrief | None
    crawled_at: datetime
    version_count: int


class PasteDetail(BaseModel):
    paste_id: str
    content_md: str
    author: _UserBrief | None
    crawled_at: datetime
    version_count: int


class FeedItem(BaseModel):
    id: int
    type: int
    time: datetime
    content_md: str
    user: _UserBrief | None


class JudgementGroup(BaseModel):
    group_key: str
    reason: str
    revoked_permission: int
    added_permission: int
    time_start: datetime
    time_end: datetime
    users: list[_UserBrief]
    count: int


class ProblemItem(BaseModel):
    pid: str
    title: str
    difficulty: str | None
    solution_open: bool


# ============================================================
# Helpers
# ============================================================

async def _user_brief(session: AsyncSession, uid: int | None) -> _UserBrief | None:
    if uid is None:
        return None
    u = await session.get(LuoguUser, uid)
    if u is None:
        return None
    return _UserBrief(
        uid=u.uid,
        name=u.name,
        color=u.color.value,
        badge=u.badge,
        avatar=u.avatar,
    )


# ============================================================
# Article
# ============================================================

@router.get("/article/{article_id}", response_model=ArticleDetail)
async def get_article(
    article_id: str,
    db: AsyncSession = Depends(get_db),
) -> ArticleDetail:
    art = await db.get(Article, article_id)
    if art is None:
        # 未爬过 → 立即派发一次高优先级爬取，并返回 404
        from app.tasks.actors.crawl import crawl_article
        crawl_article.send(article_id, "passive")
        raise NotFoundError("文章未被本站收录，已触发爬取，请稍后刷新")

    v: ArticleVersion | None = None
    if art.current_version_id:
        v = await db.get(ArticleVersion, art.current_version_id)
    if v is None:
        raise NotFoundError("文章版本缺失")

    # 计数版本
    count_q = select(ArticleVersion).where(ArticleVersion.article_id == article_id)
    versions_count = len((await db.execute(count_q)).all())

    # 被动刷新
    if is_stale(art.last_crawled_at):
        await schedule_refresh_article(article_id)

    return ArticleDetail(
        article_id=article_id,
        title=v.title,
        content_md=v.content_md,
        author=await _user_brief(db, art.author_uid),
        crawled_at=v.crawled_at,
        version_count=versions_count,
    )


# ============================================================
# Paste
# ============================================================

@router.get("/paste/{paste_id}", response_model=PasteDetail)
async def get_paste(
    paste_id: str,
    db: AsyncSession = Depends(get_db),
) -> PasteDetail:
    p = await db.get(Paste, paste_id)
    if p is None:
        from app.tasks.actors.crawl import crawl_paste
        crawl_paste.send(paste_id, "passive")
        raise NotFoundError("剪贴板未被本站收录，已触发爬取")

    v: PasteVersion | None = None
    if p.current_version_id:
        v = await db.get(PasteVersion, p.current_version_id)
    if v is None:
        raise NotFoundError("剪贴板版本缺失")

    count_q = select(PasteVersion).where(PasteVersion.paste_id == paste_id)
    versions_count = len((await db.execute(count_q)).all())

    if is_stale(p.last_crawled_at):
        await schedule_refresh_paste(paste_id)

    return PasteDetail(
        paste_id=paste_id,
        content_md=v.content_md,
        author=await _user_brief(db, p.author_uid),
        crawled_at=v.crawled_at,
        version_count=versions_count,
    )


# ============================================================
# 伪全网犇（按时间倒序）
# ============================================================

@router.get("/feed", response_model=list[FeedItem])
async def global_feed(
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = Query(None, description="分页锚点：拿早于此时间的"),
    db: AsyncSession = Depends(get_db),
) -> list[FeedItem]:
    q = select(Feed).order_by(desc(Feed.time)).limit(limit)
    if before is not None:
        q = q.where(Feed.time < before)
    rows = (await db.execute(q)).scalars().all()

    items: list[FeedItem] = []
    for r in rows:
        user = await _user_brief(db, r.author_uid)
        items.append(
            FeedItem(
                id=r.id,
                type=r.type,
                time=r.time,
                content_md=r.content_md,
                user=user,
            )
        )
    return items


# ============================================================
# 陶片放逐（带同项合并）
# ============================================================

@router.get("/judgement", response_model=list[JudgementGroup])
async def list_judgement(
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[JudgementGroup]:
    q = select(Judgement).order_by(desc(Judgement.time)).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    # 分组：reason + 权限位图 + 时间窗
    groups = await _group_judgements(db, rows)
    return groups


async def _group_judgements(
    session: AsyncSession, rows: list[Judgement]
) -> list[JudgementGroup]:
    """按 3.md 4.4.1 的合并规则生成分组。

    规则：三者同时满足才合并 —— reason 相同、两个 permission 相同、相邻时间 ≤ 30 min。
    """
    window_sec = settings.JUDGEMENT_GROUP_TIME_WINDOW_SEC

    # 先把 rows 按 (reason, revoked, added) 分桶
    buckets: dict[tuple, list[Judgement]] = defaultdict(list)
    for r in rows:
        buckets[(r.reason, r.revoked_permission, r.added_permission)].append(r)

    # 每桶内按时间排序再按 30min 切分为子组
    groups: list[JudgementGroup] = []
    for (reason, revoked, added), items in buckets.items():
        items.sort(key=lambda x: x.time)
        current: list[Judgement] = []
        prev_time: datetime | None = None

        async def _flush(bucket: list[Judgement]) -> None:
            if not bucket:
                return
            users_info: list[_UserBrief] = []
            for jt in bucket:
                u = await _user_brief(session, jt.uid)
                if u is None:
                    u = _UserBrief(
                        uid=jt.uid,
                        name=jt.username_snapshot,
                        color="Gray",
                        badge=None,
                        avatar=None,
                    )
                users_info.append(u)
            groups.append(
                JudgementGroup(
                    group_key=f"{hash((reason, revoked, added, int(bucket[0].time.timestamp()))):x}",
                    reason=reason,
                    revoked_permission=revoked,
                    added_permission=added,
                    time_start=bucket[0].time,
                    time_end=bucket[-1].time,
                    users=users_info,
                    count=len(bucket),
                )
            )

        for it in items:
            if prev_time is None or (it.time - prev_time).total_seconds() <= window_sec:
                current.append(it)
            else:
                await _flush(current)
                current = [it]
            prev_time = it.time
        await _flush(current)

    # 按 time_end 倒序
    groups.sort(key=lambda g: g.time_end, reverse=True)
    return groups


# ============================================================
# 题目列表（按难度分组，仅开放题解的）
# ============================================================

@router.get("/problem/list", response_model=dict[str, list[ProblemItem]])
async def problem_list_by_difficulty(
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[ProblemItem]]:
    """按难度分桶返回"允许提交题解"的题目。"""
    q = (
        select(Problem)
        .where(Problem.solution_open.is_(True))
        .order_by(Problem.difficulty, Problem.pid)
    )
    rows = (await db.execute(q)).scalars().all()
    out: dict[str, list[ProblemItem]] = defaultdict(list)
    for p in rows:
        out[p.difficulty or "暂无评定"].append(
            ProblemItem(
                pid=p.pid,
                title=p.title,
                difficulty=p.difficulty,
                solution_open=p.solution_open,
            )
        )
    return dict(out)
