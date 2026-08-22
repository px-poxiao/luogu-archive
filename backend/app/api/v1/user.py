"""用户聚合主页 API + 活动流（犇犇 / 文章 / 剪贴板 / 陶片）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.crawler.revalidate import is_stale, schedule_refresh_user
from app.models.luogu_content import (
    Article,
    ArticleVersion,
    Feed,
    Judgement,
    Paste,
    PasteVersion,
)
from app.models.luogu_user import (
    LuoguUser,
    UserNameVersion,
    UserPrize,
)
from app.services.content_suppression import ensure_content_visible, visible_content_clause
from app.services.feed_merge import merge_feed_rows

router = APIRouter(prefix="/user", tags=["user"])


# ============================================================
# Schemas
# ============================================================

class UserNameHistoryItem(BaseModel):
    name: str
    color: str
    badge: str | None
    ccf_level: int
    xcpc_level: int
    first_seen_at: datetime
    last_seen_at: datetime
    is_hidden: bool  # 前台若为 True 会显示成 UID xxx


class PrizeItem(BaseModel):
    year: int
    contest: str
    event: str | None
    prize: str
    score: float | None = None
    rank: int | None = None


class UserProfile(BaseModel):
    uid: int
    name: str
    avatar: str | None
    background: str | None
    slogan: str | None
    badge: str | None
    color: str
    is_admin: bool
    is_banned: bool
    ccf_level: int
    xcpc_level: int
    following_count: int
    follower_count: int
    ranking: int | None
    passed_problem_count: int | None
    submitted_problem_count: int | None
    register_time: datetime | None
    introduction_md: str | None
    last_crawled_at: datetime | None

    # 历史
    name_history: list[UserNameHistoryItem]
    prizes: list[PrizeItem]
    # 违规隐藏（当前名也会被脱敏时，前端显示 UID）
    name_hidden: bool


class ActivityItem(BaseModel):
    kind: str  # "feed" | "article" | "paste" | "judgement"
    time: datetime
    # 任一类型的关键字段，前端分别渲染
    feed_id: int | None = None
    feed_content: str | None = None
    feed_merged_suffix_md: str | None = None
    feed_merged_from_id: int | None = None
    feed_merged_link_md: list[str] = Field(default_factory=list)
    feed_merged_image_md: list[str] = Field(default_factory=list)
    article_id: str | None = None
    article_title: str | None = None
    paste_id: str | None = None
    judgement_reason: str | None = None
    judgement_revoked: int | None = None
    judgement_added: int | None = None


# ============================================================
# Endpoints
# ============================================================

@router.get("/{uid}", response_model=UserProfile)
async def get_user(
    uid: int,
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    await ensure_content_visible(db, "user", str(uid))
    user = await db.get(LuoguUser, uid)
    if user is None:
        # 未收录 → 高优先级拉一次
        from app.tasks.actors.crawl import crawl_user
        crawl_user.send(uid, "first_time")
        raise NotFoundError("用户未被本站收录，已触发爬取")

    if is_stale(user.last_crawled_at):
        await schedule_refresh_user(uid)

    current_name_hidden = False
    current_name_resolved = False

    # 用户名外显历史：最新记录优先，最多返回最近 120 次变化。
    nv_q = (
        select(UserNameVersion)
        .where(UserNameVersion.uid == uid)
        .order_by(
            UserNameVersion.first_seen_at.desc(),
            UserNameVersion.id.desc(),
        )
        .limit(120)
    )
    nvs = (await db.execute(nv_q)).scalars().all()
    history: list[UserNameHistoryItem] = []
    for nv in nvs:
        # 被隐藏的历史不把原用户名及其外显特征下发到浏览器。
        history_name = f"UID {uid}" if nv.is_hidden else nv.name
        history.append(
            UserNameHistoryItem(
                name=history_name,
                color="Gray" if nv.is_hidden else nv.color.value,
                badge=None if nv.is_hidden else nv.badge,
                ccf_level=0 if nv.is_hidden else nv.ccf_level,
                xcpc_level=0 if nv.is_hidden else nv.xcpc_level,
                first_seen_at=nv.first_seen_at,
                last_seen_at=nv.last_seen_at,
                is_hidden=nv.is_hidden,
            )
        )
        if nv.name == user.name and not current_name_resolved:
            current_name_hidden = nv.is_hidden
            current_name_resolved = True

    # 奖项
    p_q = select(UserPrize).where(UserPrize.uid == uid).order_by(UserPrize.year)
    prizes = (await db.execute(p_q)).scalars().all()

    return UserProfile(
        uid=user.uid,
        name=user.name,
        avatar=user.avatar,
        background=user.background,
        slogan=user.slogan,
        badge=user.badge,
        color=user.color.value,
        is_admin=user.is_admin,
        is_banned=user.is_banned,
        ccf_level=user.ccf_level,
        xcpc_level=user.xcpc_level,
        following_count=user.following_count,
        follower_count=user.follower_count,
        ranking=user.ranking,
        passed_problem_count=user.passed_problem_count,
        submitted_problem_count=user.submitted_problem_count,
        register_time=user.register_time,
        introduction_md=user.introduction,
        last_crawled_at=user.last_crawled_at,
        name_history=history,
        prizes=[
            PrizeItem(
                year=p.year,
                contest=p.contest,
                event=p.event,
                prize=p.prize,
                score=p.score,
                rank=p.rank,
            )
            for p in prizes
        ],
        name_hidden=current_name_hidden,
    )


@router.get("/{uid}/activity", response_model=list[ActivityItem])
async def user_activity(
    uid: int,
    include_feed: bool = Query(True, description="是否包含犇犇（用户可折叠）"),
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = Query(
        None, description="分页锚点：拿严格早于此时间的活动，时间倒序游标分页"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityItem]:
    """聚合用户的所有活动：犇犇 + 文章 + 剪贴板 + 陶片，按时间倒序。

    分页：传 before（最后一条的 time）拿更老的；不传从最新开始。
    每路（feed/article/paste/judgement）各取 limit 条，合并排序后再裁 limit。
    所以总返回 ≤ limit 条；前端判断"返回 0 条"即认为没有更早的了。
    """
    await ensure_content_visible(db, "user", str(uid))
    items: list[ActivityItem] = []

    if include_feed:
        fq = select(Feed).where(
            Feed.author_uid == uid,
            visible_content_clause("feed", Feed.id, Feed.author_uid),
        )
        if before is not None:
            fq = fq.where(Feed.time < before)
        fq = fq.order_by(desc(Feed.time)).limit(limit)
        feed_rows = list((await db.execute(fq)).scalars().all())
        merged_feeds = await merge_feed_rows(db, feed_rows)
        for f in feed_rows:
            display = merged_feeds[int(f.id)]
            items.append(
                ActivityItem(
                    kind="feed",
                    time=f.time,
                    feed_id=f.id,
                    feed_content=display.content_md,
                    feed_merged_suffix_md=display.merged_suffix_md,
                    feed_merged_from_id=display.merged_from_id,
                    feed_merged_link_md=list(display.merged_link_md),
                    feed_merged_image_md=list(display.merged_image_md),
                )
            )

    # 排序按"产生新版本的时间"，即 current_version 的 crawled_at —— 这是真正
    # 反映"上次有变化"的时间。Article.last_crawled_at 每次扫描都会被更新，
    # 哪怕内容没变；用它排会把"刚被定时扫了但内容未变"的文章顶上来，误导用户。
    aq = (
        select(Article, ArticleVersion.crawled_at.label("changed_at"))
        .join(ArticleVersion, ArticleVersion.id == Article.current_version_id)
        .where(Article.author_uid == uid, visible_content_clause("article", Article.article_id, Article.author_uid))
    )
    if before is not None:
        aq = aq.where(ArticleVersion.crawled_at < before)
    aq = aq.order_by(desc(ArticleVersion.crawled_at)).limit(limit)
    for a, changed_at in (await db.execute(aq)).all():
        items.append(
            ActivityItem(
                kind="article",
                time=changed_at,
                article_id=a.article_id,
                article_title=a.title,
            )
        )

    pq = (
        select(Paste, PasteVersion.crawled_at.label("changed_at"))
        .join(PasteVersion, PasteVersion.id == Paste.current_version_id)
        .where(Paste.author_uid == uid, visible_content_clause("paste", Paste.paste_id, Paste.author_uid))
    )
    if before is not None:
        pq = pq.where(PasteVersion.crawled_at < before)
    pq = pq.order_by(desc(PasteVersion.crawled_at)).limit(limit)
    for p, changed_at in (await db.execute(pq)).all():
        items.append(
            ActivityItem(
                kind="paste",
                time=changed_at,
                paste_id=p.paste_id,
            )
        )

    jq = select(Judgement).where(Judgement.uid == uid)
    if before is not None:
        jq = jq.where(Judgement.time < before)
    jq = jq.order_by(desc(Judgement.time)).limit(limit)
    for j in (await db.execute(jq)).scalars().all():
        items.append(
            ActivityItem(
                kind="judgement",
                time=j.time,
                judgement_reason=j.reason,
                judgement_revoked=j.revoked_permission,
                judgement_added=j.added_permission,
            )
        )

    items.sort(key=lambda x: x.time, reverse=True)
    return items[:limit]
