"""内容查询 API —— 文章、剪贴板、陶片、伪全网犇、题目列表。

所有 GET 端点都做 stale-while-revalidate（数据过期时异步重爬，不阻塞）。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, or_, select
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
    # 钩子（OI 认证）等级：0-2 不显示，3-5 绿，6-7 蓝，8+ 金
    ccf_level: int = 0
    # 气球（XCPC 认证）等级：0-2 不显示，3-5 绿，6-7 蓝，8+ 金（与钩子规则相同）
    xcpc_level: int = 0
    # 是否管理员（决定 badge 是否当作管理员标识渲染）
    is_admin: bool = False


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
    tags: list[int] = []
    solution_open: bool


class ProblemDifficultyBucket(BaseModel):
    """每档难度的预览：前 N 条 + 该档总数。前端据此决定是否显示"查看全部"。"""
    items: list[ProblemItem]
    total: int


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
        ccf_level=u.ccf_level or 0,
        xcpc_level=u.xcpc_level or 0,
        is_admin=u.is_admin,
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
    limit: int = Query(50, ge=1, le=500),
    before: datetime | None = Query(
        None, description="分页锚点：拿严格早于此时间的，时间倒序游标分页"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[JudgementGroup]:
    q = select(Judgement).order_by(desc(Judgement.time))
    if before is not None:
        q = q.where(Judgement.time < before)
    q = q.limit(limit)
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

@router.get("/problem/list", response_model=dict[str, ProblemDifficultyBucket])
async def problem_list_by_difficulty(
    preview_limit: int = Query(20, ge=1, le=200,
                                description="每档返回的预览条数，前端默认 20"),
    include_closed: bool = Query(False, description="是否包含'不可提交题解'的题"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, ProblemDifficultyBucket]:
    """按难度分桶返回题目预览：每档前 preview_limit 条 + 该档总数。

    用户点"查看全部"再调 /problem/list/by-difficulty?difficulty=xxx 拉单档全量。
    """
    base_filter = [] if include_closed else [Problem.solution_open.is_(True)]

    # 一次查全量再 group by 内存里切，省去对每个档单独打两遍 SQL
    q = select(Problem).order_by(Problem.difficulty, Problem.pid)
    for f in base_filter:
        q = q.where(f)
    rows = (await db.execute(q)).scalars().all()

    buckets: dict[str, list[ProblemItem]] = defaultdict(list)
    for p in rows:
        buckets[p.difficulty or "暂无评定"].append(
            ProblemItem(
                pid=p.pid,
                title=p.title,
                difficulty=p.difficulty,
                tags=p.tags or [],
                solution_open=p.solution_open,
            )
        )

    return {
        diff: ProblemDifficultyBucket(
            items=items[:preview_limit],
            total=len(items),
        )
        for diff, items in buckets.items()
    }


@router.get("/problem/list/by-difficulty", response_model=list[ProblemItem])
async def problem_list_full_by_difficulty(
    difficulty: str = Query(..., description="难度档名（如 '入门' / '暂无评定'）"),
    include_closed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> list[ProblemItem]:
    """单档全量。'暂无评定' 同时匹配 difficulty IS NULL 和字符串 '暂无评定'
    —— 爬虫对 difficulty=0 的题会存成字符串，老数据可能是 NULL，两种都得包进来。"""
    q = select(Problem).order_by(Problem.pid)
    if difficulty == "暂无评定":
        q = q.where(or_(Problem.difficulty.is_(None), Problem.difficulty == "暂无评定"))
    else:
        q = q.where(Problem.difficulty == difficulty)
    if not include_closed:
        q = q.where(Problem.solution_open.is_(True))
    rows = (await db.execute(q)).scalars().all()
    return [
        ProblemItem(
            pid=p.pid,
            title=p.title,
            difficulty=p.difficulty,
            tags=p.tags or [],
            solution_open=p.solution_open,
        )
        for p in rows
    ]


# ============================================================
# 通用：最近一次成功爬取时间（list 页 OriginBanner 显示"上次更新"）
# ============================================================

@router.get("/last-crawled")
async def last_crawled(
    type: str = Query(..., description="task_type: judgement / problem_list / ..."),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回某类爬取任务最近一次 success 的 started_at（UTC ISO 字符串）。"""
    from app.models._common import CrawlTaskStatus
    from app.models.task import CrawlTask

    q = (
        select(CrawlTask.started_at)
        .where(
            CrawlTask.task_type == type,
            CrawlTask.status == CrawlTaskStatus.success,
        )
        .order_by(CrawlTask.started_at.desc())
        .limit(1)
    )
    row = (await db.execute(q)).scalar_one_or_none()
    return {"last_crawled_at": row.isoformat() if row else None}

