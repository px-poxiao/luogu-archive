"""用户聚合主页 API + 活动流（犇犇 / 文章 / 剪贴板 / 讨论 / 陶片）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.crawler.revalidate import is_stale, schedule_refresh_user
from app.models.luogu_content import (
    Article,
    ArticleVersion,
    Discussion,
    DiscussionReply,
    DiscussionReplyVersion,
    DiscussionVersion,
    Feed,
    Judgement,
    Paste,
    PasteVersion,
)
from app.models.luogu_user import (
    LuoguUser,
    UserEloHistory,
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


class UserRatingHistoryItem(BaseModel):
    """已缓存的官方等级分结果；缺失的旧分或变化值保持为空。"""

    contest_id: int
    contest_name: str
    time: datetime
    contest_start_time: datetime | None
    contest_end_time: datetime | None
    rating: int
    previous_rating: int | None
    rating_change: int | None


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
    kind: str  # "feed" | "article" | "paste" | "discussion" | "discussion_reply" | "judgement"
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
    discussion_id: int | None = None
    discussion_title: str | None = None
    discussion_excerpt: str | None = None
    discussion_reply_count: int | None = None
    discussion_reply_id: int | None = None
    discussion_reply_page: int | None = None
    discussion_reply_excerpt: str | None = None
    judgement_reason: str | None = None
    judgement_revoked: int | None = None
    judgement_added: int | None = None


# ============================================================
# Endpoints
# ============================================================

def _discussion_excerpt(content: str, *, limit: int) -> str:
    """有限长度的 Markdown 转为纯文本摘要，不向活动列表输出 HTML 或链接语法。"""
    parts: list[str] = []
    # 查询最多读取 1201 字；最后一个字只用于判断原文是否还有后续。
    for token in MarkdownIt("commonmark", {"html": True}).parse(content[:1200]):
        if token.type == "inline":
            for child in token.children or []:
                if child.type in {"text", "code_inline", "image"}:
                    parts.append(child.content)
                elif child.type in {"softbreak", "hardbreak"}:
                    parts.append(" ")
            parts.append(" ")
        elif token.type in {"fence", "code_block"}:
            parts.extend([token.content, " "])
    text = " ".join("".join(parts).split())
    if not text:
        return "（暂无正文摘要）"
    if len(text) > limit or len(content) > 1200:
        return text[:limit].rstrip() + "…"
    return text


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


@router.get("/{uid}/rating-history", response_model=list[UserRatingHistoryItem])
async def user_rating_history(
    uid: int,
    db: AsyncSession = Depends(get_db),
) -> list[UserRatingHistoryItem]:
    """按比赛时间从旧到新返回官方缓存历史，不触发首次爬取或过期刷新。"""
    await ensure_content_visible(db, "user", str(uid))
    if await db.get(LuoguUser, uid) is None:
        raise NotFoundError("用户未被本站收录")

    # 只查询官方历史表，不读取本站比赛预测；结束时间缺失时使用结果时间排序。
    query = (
        select(UserEloHistory)
        .where(UserEloHistory.uid == uid)
        .order_by(
            func.coalesce(UserEloHistory.contest_end_time, UserEloHistory.time),
            UserEloHistory.time,
            UserEloHistory.contest_id,
        )
    )
    rows = (await db.execute(query)).scalars().all()
    history: list[UserRatingHistoryItem] = []
    for row in rows:
        # 与正式比赛结果保持同一口径；不能用相邻缓存记录猜旧分，历史可能不完整。
        previous_rating = row.previous_rating
        if previous_rating is None and row.prev_diff is not None:
            previous_rating = row.rating - row.prev_diff
        history.append(UserRatingHistoryItem(
            contest_id=row.contest_id,
            contest_name=row.contest_name,
            time=row.time,
            contest_start_time=row.contest_start_time,
            contest_end_time=row.contest_end_time,
            rating=row.rating,
            previous_rating=previous_rating,
            rating_change=(row.rating - previous_rating) if previous_rating is not None else None,
        ))
    return history


@router.get("/{uid}/activity", response_model=list[ActivityItem])
async def user_activity(
    uid: int,
    include_feed: bool = Query(True, description="是否包含犇犇（用户可折叠）"),
    include_discussion: bool = Query(True, description="是否包含讨论主帖和回复"),
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = Query(
        None, description="分页锚点：拿严格早于此时间的活动，时间倒序游标分页"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityItem]:
    """聚合用户的已归档活动：犇犇 + 文章 + 剪贴板 + 讨论及回复 + 陶片。

    分页：传 before（最后一条的 time）拿更老的；不传从最新开始。
    每种活动各取 limit 条，合并按时间倒序排列后再裁 limit。
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

    if include_discussion:
        # 讨论只读取已有归档，避免访问个人主页时扫描用户在源站的发帖记录。
        # 优先使用源站发布时间；旧记录缺失该时间时回退到首次归档时间。
        discussion_time = func.coalesce(Discussion.source_time, Discussion.first_crawled_at)
        dq = (
            select(
                Discussion,
                DiscussionVersion.title,
                func.substr(DiscussionVersion.content_md, 1, 1201).label("excerpt"),
                discussion_time.label("activity_time"),
            )
            .join(DiscussionVersion, DiscussionVersion.id == Discussion.current_version_id)
            .where(Discussion.author_uid == uid)
        )
        if before is not None:
            dq = dq.where(discussion_time < before)
        dq = dq.order_by(desc(discussion_time), desc(Discussion.discussion_id)).limit(limit)
        for discussion, title, excerpt, activity_time in (await db.execute(dq)).all():
            items.append(
                ActivityItem(
                    kind="discussion",
                    time=activity_time,
                    discussion_id=discussion.discussion_id,
                    discussion_title=title,
                    discussion_excerpt=_discussion_excerpt(excerpt, limit=160),
                    discussion_reply_count=discussion.observed_reply_count,
                )
            )

        # 回复使用最新正文，空白占位记录不展示；数据库只返回短摘要，避免传输长帖。
        reply_time = func.coalesce(DiscussionReply.source_time, DiscussionReply.first_crawled_at)
        rq = (
            select(
                DiscussionReply,
                DiscussionVersion.title,
                func.substr(DiscussionReplyVersion.content_md, 1, 1201).label("excerpt"),
                reply_time.label("activity_time"),
            )
            .join(DiscussionReplyVersion, DiscussionReplyVersion.id == DiscussionReply.current_version_id)
            .join(Discussion, Discussion.discussion_id == DiscussionReply.discussion_id)
            .join(DiscussionVersion, DiscussionVersion.id == Discussion.current_version_id)
            .where(
                DiscussionReply.author_uid == uid,
                func.length(func.trim(DiscussionReplyVersion.content_md)) > 0,
            )
        )
        if before is not None:
            rq = rq.where(reply_time < before)
        rq = rq.order_by(desc(reply_time), desc(DiscussionReply.reply_id)).limit(limit)
        reply_rows = (await db.execute(rq)).all()
        reply_pages: dict[int, int] = {}
        if reply_rows:
            # 在帖子全部有效回复中计算位置，不能只数该用户自己的回复。
            # 批量窗口查询避免每条活动各查一次；排序和过滤与讨论详情页保持一致。
            positions = (
                select(
                    DiscussionReply.reply_id,
                    func.row_number().over(
                        partition_by=DiscussionReply.discussion_id,
                        order_by=(DiscussionReply.source_time.asc(), DiscussionReply.reply_id.asc()),
                    ).label("position"),
                )
                .join(DiscussionReplyVersion, DiscussionReplyVersion.id == DiscussionReply.current_version_id)
                .where(
                    DiscussionReply.discussion_id.in_({row[0].discussion_id for row in reply_rows}),
                    func.length(func.trim(DiscussionReplyVersion.content_md)) > 0,
                )
                .subquery()
            )
            page_rows = (await db.execute(
                select(positions.c.reply_id, positions.c.position)
                .where(positions.c.reply_id.in_([row[0].reply_id for row in reply_rows]))
            )).all()
            # 前端讨论页固定每页十条；先算完整帖子位置，再筛选目标回复。
            reply_pages = {reply_id: (position - 1) // 10 + 1 for reply_id, position in page_rows}
        for reply, title, excerpt, activity_time in reply_rows:
            items.append(
                ActivityItem(
                    kind="discussion_reply",
                    time=activity_time,
                    discussion_id=reply.discussion_id,
                    discussion_title=title,
                    discussion_reply_id=reply.reply_id,
                    discussion_reply_page=reply_pages.get(reply.reply_id),
                    discussion_reply_excerpt=_discussion_excerpt(excerpt, limit=300),
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
