"""管理员后台 API。

全部要求 get_current_admin 依赖。所有写操作写 AdminAuditLog。

端点（全部 /api/v1/admin 前缀）：
  内容管理
    DELETE /article/{id}           软删除
    DELETE /paste/{id}
    DELETE /feed/{id}
    DELETE /user/{uid}/hide_all    隐藏某用户所有历史名
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

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.auth.deps import get_current_admin
from app.core.db import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.redis_client import get_redis
from app.crawler.cookies import encrypt_cookie
from app.models._common import (
    CrawlTaskStatus,
    NameViolationSource,
    TakedownStatus,
    utcnow,
)
from app.models.admin import Admin, AdminAuditLog, CrawlerAccount
from app.models.luogu_content import Article, Feed, Paste
from app.models.luogu_user import UserNameVersion, UserNameViolation
from app.models.task import CrawlTask, TakedownRequest

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
            "requester_name": r.requester_name,
            "requester_contact": r.requester_contact,
            "reason": r.reason,
            "status": r.status.value,
            "created_at": r.created_at.isoformat(),
            "handled_at": r.handled_at.isoformat() if r.handled_at else None,
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
    await _audit(
        db, admin, request, "takedown_approve",
        target_type="takedown", target_id=str(tid),
    )
    await db.commit()
    return {"message": "已批准，请手动执行对应的删除操作"}


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

    # 队列长度（Redis）
    redis = get_redis()
    queues = ["crawler.hi", "crawler.mid", "crawler.low", "crawler.feed"]
    queue_lens = {}
    for q_name in queues:
        # Dramatiq Redis broker 用 list 存队列，key 格式 dramatiq:<queue>.msgs
        ln = await redis.llen(f"dramatiq:{q_name}.msgs")
        queue_lens[q_name] = int(ln or 0)

    return {
        "window_hours": 24,
        "by_status": status_counts,
        "by_task_type": by_type,
        "queue_lengths": queue_lens,
        "now": now.isoformat(),
    }


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
