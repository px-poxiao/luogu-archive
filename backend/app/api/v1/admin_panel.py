"""管理员后台 API。

全部要求 get_current_admin 依赖。所有写操作写 AdminAuditLog。

端点（全部 /api/v1/admin 前缀）：
  内容管理
    DELETE /article/{id}           软删除
    DELETE /paste/{id}
    DELETE /feed/{id}
    DELETE /user/{uid}/hide_all    隐藏某用户所有历史名
  站点公告
    GET    /announcements
    POST   /announcements
    PUT    /announcements/{id}
    POST   /announcements/{id}/publish
    POST   /announcements/{id}/unpublish
    DELETE /announcements/{id}
  删除申请
    GET    /takedowns              列表
    POST   /takedowns/{id}/approve
    POST   /takedowns/{id}/reject
  爬取账号（Cookie 池）
    GET    /crawler-accounts
    POST   /crawler-accounts       录入新账号（明文 cookie → 加密存库）
    POST   /crawler-accounts/{id}/disable
    POST   /crawler-accounts/{id}/enable
  爬虫监控
    GET    /stats                   近 24h 爬虫统计（403 率、队列长度、各类型失败数）
  审计
    GET    /audit-logs              倒序翻页
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.auth.deps import get_current_admin
from app.core.db import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.crawler.cookies import encrypt_cookie
from app.models._common import (
    NameViolationSource,
    TakedownStatus,
    utcnow,
)
from app.models.admin import Admin, AdminAuditLog, CrawlerAccount, SiteAnnouncement
from app.models.contest import Contest, ContestArchiveStatus
from app.models.luogu_content import Article, Feed, Paste
from app.models.luogu_user import UserNameVersion, UserNameViolation
from app.models.task import ContentSuppression, CrawlTask, TakedownRequest
from app.services.content_suppression import apply_takedown
from app.tasks.broker import QUEUE_ORDER, get_broker

router = APIRouter(prefix="/admin", tags=["admin-panel"])


# ============================================================
# 审计工具
# ============================================================

async def _audit(
    db: AsyncSession,
    admin: Admin,
    request: Request,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    params: dict | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            admin_id=admin.id,
            admin_username=admin.username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            params=params,
            ip=get_client_ip(request),
            ua=request.headers.get("user-agent", "")[:500],
        )
    )


# ============================================================
# 内容管理
# ============================================================

@router.delete("/article/{article_id}")
async def delete_article(
    article_id: str,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    art = await db.get(Article, article_id)
    if art is None:
        raise NotFoundError("文章不存在")
    art.is_deleted_on_source = True
    await _audit(db, admin, request, "delete_article", target_type="article", target_id=article_id)
    await db.commit()
    return {"message": "已软删除"}


@router.delete("/paste/{paste_id}")
async def delete_paste(
    paste_id: str,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    p = await db.get(Paste, paste_id)
    if p is None:
        raise NotFoundError("剪贴板不存在")
    p.is_deleted_on_source = True
    await _audit(db, admin, request, "delete_paste", target_type="paste", target_id=paste_id)
    await db.commit()
    return {"message": "已软删除"}


@router.delete("/feed/{feed_id}")
async def delete_feed(
    feed_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    f = await db.get(Feed, feed_id)
    if f is None:
        raise NotFoundError("犇犇不存在")
    await db.delete(f)
    await _audit(db, admin, request, "delete_feed", target_type="feed", target_id=str(feed_id))
    await db.commit()
    return {"message": "已删除"}


class HideAllReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/user/{uid}/hide_all_names")
async def hide_all_names(
    uid: int,
    body: HideAllReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """管理员手动触发用户名违规隐藏。"""
    now = utcnow()
    db.add(
        UserNameViolation(
            uid=uid,
            trigger_source=NameViolationSource.MANUAL,
            source_ref=str(admin.id),
            reason_raw=body.reason,
            matched_keywords={"by_admin": admin.username},
            triggered_at=now,
        )
    )
    await db.execute(
        update(UserNameVersion)
        .where(UserNameVersion.uid == uid, UserNameVersion.first_seen_at <= now)
        .values(is_hidden=True)
    )
    await _audit(
        db, admin, request, "hide_all_names",
        target_type="user", target_id=str(uid),
        params={"reason": body.reason},
    )
    await db.commit()
    return {"message": "已隐藏此用户此刻前所有历史用户名"}


# ============================================================
# 站点公告
# ============================================================

class AnnouncementWriteReq(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=20_000)
    is_published: bool = False

    @field_validator("title", "summary", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


def _announcement_dict(row: SiteAnnouncement) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "summary": row.summary,
        "content": row.content,
        "is_published": row.is_published,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "created_by_admin_id": row.created_by_admin_id,
    }


@router.get("/announcements")
async def list_announcements(
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = select(SiteAnnouncement).order_by(
        desc(SiteAnnouncement.created_at),
        desc(SiteAnnouncement.id),
    )
    rows = (await db.execute(q)).scalars().all()
    return [_announcement_dict(row) for row in rows]


@router.post("/announcements")
async def create_announcement(
    body: AnnouncementWriteReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = SiteAnnouncement(
        title=body.title.strip(),
        summary=body.summary.strip(),
        content=body.content.strip(),
        is_published=body.is_published,
        published_at=utcnow() if body.is_published else None,
        created_by_admin_id=admin.id,
    )
    db.add(row)
    await db.flush()
    await _audit(
        db,
        admin,
        request,
        "announcement_create",
        target_type="announcement",
        target_id=str(row.id),
        params={"title": row.title, "is_published": row.is_published},
    )
    await db.commit()
    return _announcement_dict(row)


@router.put("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    body: AnnouncementWriteReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(SiteAnnouncement, announcement_id)
    if row is None:
        raise NotFoundError("公告不存在")

    was_published = row.is_published
    row.title = body.title.strip()
    row.summary = body.summary.strip()
    row.content = body.content.strip()
    row.is_published = body.is_published
    if body.is_published and not was_published:
        row.published_at = utcnow()
    elif not body.is_published:
        row.published_at = None

    await _audit(
        db,
        admin,
        request,
        "announcement_update",
        target_type="announcement",
        target_id=str(row.id),
        params={"title": row.title, "is_published": row.is_published},
    )
    await db.commit()
    return _announcement_dict(row)


@router.post("/announcements/{announcement_id}/publish")
async def publish_announcement(
    announcement_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(SiteAnnouncement, announcement_id)
    if row is None:
        raise NotFoundError("公告不存在")
    row.is_published = True
    row.published_at = utcnow()
    await _audit(
        db, admin, request, "announcement_publish",
        target_type="announcement", target_id=str(row.id),
    )
    await db.commit()
    return _announcement_dict(row)


@router.post("/announcements/{announcement_id}/unpublish")
async def unpublish_announcement(
    announcement_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(SiteAnnouncement, announcement_id)
    if row is None:
        raise NotFoundError("公告不存在")
    row.is_published = False
    row.published_at = None
    await _audit(
        db, admin, request, "announcement_unpublish",
        target_type="announcement", target_id=str(row.id),
    )
    await db.commit()
    return _announcement_dict(row)


@router.delete("/announcements/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(SiteAnnouncement, announcement_id)
    if row is None:
        raise NotFoundError("公告不存在")
    title = row.title
    await db.delete(row)
    await _audit(
        db, admin, request, "announcement_delete",
        target_type="announcement", target_id=str(announcement_id),
        params={"title": title},
    )
    await db.commit()
    return {"message": "已删除"}


# ============================================================
# 删除申请工单
# ============================================================

@router.get("/takedowns")
async def list_takedowns(
    status: Literal["pending", "approved", "rejected", "all"] = Query("pending"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = select(TakedownRequest).order_by(desc(TakedownRequest.created_at))
    if status != "all":
        q = q.where(TakedownRequest.status == TakedownStatus(status))
    q = q.limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "target_url": r.target_url,
            "target_author_uid": r.target_author_uid,
            "requester_name": r.requester_name,
            "requester_contact": r.requester_contact,
            "reason": r.reason,
            "status": r.status.value,
            "created_at": r.created_at.isoformat(),
            "handled_at": r.handled_at.isoformat() if r.handled_at else None,
            "auto_approved": r.auto_approved,
            "execution_status": r.execution_status,
            "execution_error": r.execution_error,
        }
        for r in rows
    ]


class HandleTakedownReq(BaseModel):
    admin_note: str | None = None


@router.post("/takedowns/{tid}/approve")
async def approve_takedown(
    tid: int,
    body: HandleTakedownReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await db.get(TakedownRequest, tid)
    if t is None:
        raise NotFoundError("工单不存在")
    if t.status != TakedownStatus.pending:
        raise ConflictError("该工单已处理")
    t.status = TakedownStatus.approved
    t.admin_id = admin.id
    t.admin_note = body.admin_note
    t.handled_at = utcnow()
    await apply_takedown(db, t, admin_id=admin.id)
    await _audit(
        db, admin, request, "takedown_approve",
        target_type="takedown", target_id=str(tid),
    )
    await db.commit()
    return {"message": "已批准并停止公开展示"}


@router.post("/takedowns/{tid}/restore")
async def restore_takedown(
    tid: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await db.get(TakedownRequest, tid)
    if t is None:
        raise NotFoundError("工单不存在")
    q = select(ContentSuppression).where(
        ContentSuppression.takedown_request_id == tid,
        ContentSuppression.restored_at.is_(None),
    )
    suppression = (await db.execute(q)).scalars().first()
    if suppression is None:
        raise ConflictError("该申请没有正在生效的隐藏记录")
    suppression.restored_at = utcnow()
    t.execution_status = "restored"
    await _audit(db, admin, request, "takedown_restore",
        target_type=t.target_type, target_id=t.target_id)
    await db.commit()
    return {"message": "已恢复公开展示"}


@router.post("/takedowns/{tid}/reject")
async def reject_takedown(
    tid: int,
    body: HandleTakedownReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await db.get(TakedownRequest, tid)
    if t is None:
        raise NotFoundError("工单不存在")
    if t.status != TakedownStatus.pending:
        raise ConflictError("该工单已处理")
    t.status = TakedownStatus.rejected
    t.admin_id = admin.id
    t.admin_note = body.admin_note
    t.handled_at = utcnow()
    await _audit(
        db, admin, request, "takedown_reject",
        target_type="takedown", target_id=str(tid),
    )
    await db.commit()
    return {"message": "已拒绝"}


# ============================================================
# 爬取账号（Cookie 池）
# ============================================================

class AddAccountReq(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    luogu_uid: int = Field(..., gt=0)
    uid_value: str = Field(..., min_length=1)   # Cookie "_uid" 的值
    client_id: str = Field(..., min_length=1)   # Cookie "__client_id"
    c3vk: str | None = None                     # Cookie "C3VK" 可选


@router.get("/crawler-accounts")
async def list_accounts(
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = select(CrawlerAccount).order_by(CrawlerAccount.id.asc())
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": a.id,
            "label": a.label,
            "luogu_uid": a.luogu_uid,
            "enabled": a.enabled,
            "last_used_at": a.last_used_at.isoformat() if a.last_used_at else None,
            "last_checked_at": a.last_checked_at.isoformat() if a.last_checked_at else None,
            "last_status": a.last_status,
            "fail_count": a.fail_count,
            "disabled_reason": a.disabled_reason,
        }
        for a in rows
    ]


@router.post("/crawler-accounts")
async def add_account(
    body: AddAccountReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    acc = CrawlerAccount(
        label=body.label,
        luogu_uid=body.luogu_uid,
        uid_value_encrypted=encrypt_cookie(body.uid_value),
        client_id_encrypted=encrypt_cookie(body.client_id),
        c3vk_encrypted=encrypt_cookie(body.c3vk) if body.c3vk else None,
        enabled=True,
    )
    db.add(acc)
    await db.flush()
    await _audit(
        db, admin, request, "crawler_account_add",
        target_type="crawler_account", target_id=str(acc.id),
        params={"label": body.label, "luogu_uid": body.luogu_uid},
    )
    await db.commit()
    return {"id": acc.id, "label": acc.label}


@router.post("/crawler-accounts/{aid}/disable")
async def disable_account(
    aid: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    acc = await db.get(CrawlerAccount, aid)
    if acc is None:
        raise NotFoundError("账号不存在")
    acc.enabled = False
    acc.disabled_reason = f"manual by {admin.username}"
    await _audit(db, admin, request, "crawler_account_disable",
                 target_type="crawler_account", target_id=str(aid))
    await db.commit()
    return {"message": "已禁用"}


@router.post("/crawler-accounts/{aid}/enable")
async def enable_account(
    aid: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    acc = await db.get(CrawlerAccount, aid)
    if acc is None:
        raise NotFoundError("账号不存在")
    acc.enabled = True
    acc.disabled_reason = None
    acc.fail_count = 0
    await _audit(db, admin, request, "crawler_account_enable",
                 target_type="crawler_account", target_id=str(aid))
    await db.commit()
    return {"message": "已启用"}


# ============================================================
# 题库全量刷新
# ============================================================

class ProblemRefreshReq(BaseModel):
    """全量刷新题库的范围。两个前缀的范围独立指定。

    - 已知 P 题号范围 1000~目前最大（约 P16500），B 题号 2001~目前最大（约 B4500）
    - 题号区间内不会连续断号超过 10 个，因此 sentinel=10
    - 我们一次性派 (max-min+1) 个任务，错峰 delay 防止节点被打 403
    """

    p_min: int = Field(1000, ge=1)
    p_max: int = Field(16501, ge=1)
    b_min: int = Field(2001, ge=1)
    b_max: int = Field(4528, ge=1)
    delay_ms: int = Field(11000, ge=500, le=30000,
                           description="任务之间的间隔，越小越快但越容易被洛谷拦。"
                                       ".com.cn 节点 0.1 req/s = 10s/req，建议 ≥ 11000")


@router.post("/problems/full-refresh")
async def full_refresh_problems(
    body: ProblemRefreshReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量刷新题库：对 P[p_min..p_max] / B[b_min..b_max] 每个 pid 派一条
    crawl_problem_solution 任务，错峰执行。

    任务自身能识别 404（CrawlerNotFound throws）→ 不重试、不熔断。
    断号在范围内只表现为 404，不影响整体进度。
    """
    from app.tasks.problem_queue import enqueue_problem_solution

    pids: list[str] = []
    pids.extend(f"P{n}" for n in range(body.p_min, body.p_max + 1))
    pids.extend(f"B{n}" for n in range(body.b_min, body.b_max + 1))

    enqueued = 0
    for pid in pids:
        result = await enqueue_problem_solution(
            pid,
            "manual_full_refresh",
            delay_ms=enqueued * body.delay_ms,
        )
        if result.enqueued:
            enqueued += 1

    await _audit(
        db, admin, request, "problem_full_refresh",
        target_type="problem", target_id="all",
        params={
            "p_range": [body.p_min, body.p_max],
            "b_range": [body.b_min, body.b_max],
            "count": enqueued,
            "skipped_duplicate": len(pids) - enqueued,
            "delay_ms": body.delay_ms,
        },
    )
    await db.commit()

    # 估算总耗时
    eta_sec = (enqueued * body.delay_ms) // 1000
    return {
        "message": "已派发",
        "count": enqueued,
        "skipped_duplicate": len(pids) - enqueued,
        "eta_sec": eta_sec,
    }


# ============================================================
# 爬虫监控
# ============================================================

@router.get("/stats")
async def crawler_stats(
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = utcnow()
    since = now - timedelta(hours=24)

    # 近 24h 分状态统计
    q = (
        select(CrawlTask.status, func.count())
        .where(CrawlTask.started_at >= since)
        .group_by(CrawlTask.status)
    )
    status_counts = {
        r[0].value: int(r[1]) for r in (await db.execute(q)).all()
    }

    # 分类型统计
    q = (
        select(CrawlTask.task_type, func.count())
        .where(CrawlTask.started_at >= since)
        .group_by(CrawlTask.task_type)
    )
    by_type = {r[0]: int(r[1]) for r in (await db.execute(q)).all()}

    # 队列长度包含等待依赖的 pending 与正在执行的 inflight。
    queue_lens = {}
    for q_name in QUEUE_ORDER:
        try:
            queue_lens[q_name] = await asyncio.to_thread(
                get_broker().queue_size,
                q_name,
            )
        except Exception:
            queue_lens[q_name] = 0

    return {
        "window_hours": 24,
        "by_status": status_counts,
        "by_task_type": by_type,
        "queue_lengths": queue_lens,
        "now": now.isoformat(),
    }


# ============================================================
# 比赛归档与等级分
# ============================================================

@router.get("/contests")
async def admin_contests(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """管理员查看全部已发现比赛及任务状态。"""

    total = int(await db.scalar(select(func.count(Contest.id))) or 0)
    rows = (
        await db.execute(
            select(Contest)
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
                "status": item.status.value,
                "rated": item.is_elo_rated,
                "participant_count": item.participant_count,
                "error_message": item.error_message,
            }
            for item in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


class ContestArchiveReq(BaseModel):
    contest_id: int = Field(..., ge=1)


@router.post("/contests/discover")
async def admin_discover_contests(
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """立即扫描比赛列表第一页。"""

    from app.tasks.actors.contest import discover_contests

    discover_contests.send()
    await _audit(db, admin, request, "contest_discover", target_type="contest", target_id="page_1")
    await db.commit()
    return {"message": "已派发比赛发现任务"}


@router.post("/contests/archive")
async def admin_archive_contest(
    body: ContestArchiveReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按比赛 ID 补录或重新归档。"""

    from app.tasks.actors.contest import archive_contest

    archive_contest.send(body.contest_id, "admin", True)
    await _audit(
        db,
        admin,
        request,
        "contest_archive",
        target_type="contest",
        target_id=str(body.contest_id),
    )
    await db.commit()
    return {"message": "已派发归档任务"}


@router.post("/contests/{contest_id}/recalculate")
async def admin_recalculate_contest(
    contest_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """使用已保存的榜单和用户赛前快照重新计算，不重新抓取。"""

    from app.tasks.actors.contest import calculate_contest_prediction

    contest = await db.get(Contest, contest_id)
    if contest is None:
        raise NotFoundError("比赛不存在")
    if not contest.is_elo_rated:
        raise ConflictError("该比赛不计等级分")
    calculate_contest_prediction.send(contest_id)
    await _audit(
        db,
        admin,
        request,
        "contest_recalculate",
        target_type="contest",
        target_id=str(contest_id),
    )
    await db.commit()
    return {"message": "已派发重新计算任务"}


@router.post("/contests/{contest_id}/check-official")
async def admin_check_contest_official(
    contest_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """立即用阈值内前 20 名检查正式等级分。"""

    from app.tasks.actors.contest import probe_contest_official

    contest = await db.get(Contest, contest_id)
    if contest is None:
        raise NotFoundError("比赛不存在")
    if not contest.is_elo_rated:
        raise ConflictError("该比赛不计等级分")
    if contest.status == ContestArchiveStatus.official:
        raise ConflictError("该比赛已经保存正式结果")
    probe_contest_official.send(contest_id)
    await _audit(
        db,
        admin,
        request,
        "contest_check_official",
        target_type="contest",
        target_id=str(contest_id),
    )
    await db.commit()
    return {"message": "已派发正式结果检查任务"}


# ============================================================
# 审计日志
# ============================================================

@router.get("/audit-logs")
async def audit_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = (
        select(AdminAuditLog)
        .order_by(desc(AdminAuditLog.happened_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "admin": r.admin_username,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "params": r.params,
            "ip": r.ip,
            "happened_at": r.happened_at.isoformat(),
        }
        for r in rows
    ]
