"""内容删除申请：地址探测、本人直通和软隐藏。"""
from __future__ import annotations

import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_client_ip
from app.auth.deps import get_optional_site_user
from app.core.db import get_db
from app.core.exceptions import ConflictError, RateLimitError, ValidationError
from app.core.ratelimit import SlidingWindowLimiter, ratelimit_key
from app.core.redis_client import get_redis
from app.models._common import TakedownStatus, utcnow
from app.models.luogu_content import Article, Feed, Paste
from app.models.site_user import SiteUser
from app.models.task import TakedownProbe, TakedownRequest
from app.services.content_suppression import apply_takedown, detect_target_url, find_active_suppression

router = APIRouter(tags=["takedown"])


class ProbeReq(BaseModel):
    target_url: str = Field(..., min_length=1, max_length=1024)


class SubmitReq(BaseModel):
    probe_token: str = Field(..., min_length=16, max_length=64)
    requester_name: str | None = Field(None, max_length=128)
    requester_email: EmailStr | None = None
    reason: str | None = Field(None, max_length=5000)


@router.post("/takedown/probe")
async def probe_takedown(body: ProbeReq, request: Request,
    user: SiteUser | None = Depends(get_optional_site_user), db: AsyncSession = Depends(get_db)) -> dict:
    ok, _ = await SlidingWindowLimiter(get_redis()).acquire(
        ratelimit_key("takedown_probe_ip", get_client_ip(request)), window_sec=3600, limit=20)
    if not ok:
        raise RateLimitError("地址检查过于频繁，请稍后再试", retry_after_sec=1800)
    target_type, target_url, target_id = detect_target_url(body.target_url)
    archived = None
    if target_type == "article":
        archived = await db.get(Article, target_id)
    elif target_type == "paste":
        archived = await db.get(Paste, target_id)
    elif target_type == "feed":
        archived = await db.get(Feed, int(target_id))
    owner_uid = int(target_id) if target_type == "user" else (
        archived.author_uid if archived is not None else None
    )
    if await find_active_suppression(db, target_type, target_id, owner_uid):
        raise ConflictError("该内容已经停止公开展示")
    row = TakedownProbe(token=secrets.token_urlsafe(32), requester_user_id=user.id if user else None,
        target_type=target_type, target_id=target_id, target_url=target_url,
        status="pending", expires_at=utcnow() + timedelta(minutes=10))
    if target_type == "user":
        row.status = "completed"
        row.author_uid = int(target_id)
        row.completed_at = utcnow()
    db.add(row)
    await db.commit()
    if row.status == "completed":
        is_owner = bool(user and user.luogu_uid and user.luogu_uid == row.author_uid)
        return {"token": row.token, "status": row.status, "target_type": row.target_type,
            "target_id": row.target_id, "accessible": None,
            "can_submit": True, "is_owner": is_owner, "expires_at": row.expires_at.isoformat()}
    from app.tasks.actors.crawl import probe_takedown_target
    probe_takedown_target.send(row.token, row.target_type)
    return {"token": row.token, "status": "pending", "target_type": row.target_type,
        "target_id": row.target_id,
        "expires_at": row.expires_at.isoformat()}


@router.get("/takedown/probe/{token}")
async def takedown_probe_status(token: str,
    user: SiteUser | None = Depends(get_optional_site_user), db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(TakedownProbe, token)
    if row is None:
        raise ValidationError("探测任务不存在或已失效")
    is_owner = bool(user and user.luogu_uid and user.luogu_uid == row.author_uid)
    return {"token": row.token, "status": row.status, "target_type": row.target_type,
        "target_id": row.target_id,
        "accessible": row.accessible,
        "can_submit": row.status == "completed" and row.accessible is not True,
        "is_owner": is_owner, "expires_at": row.expires_at.isoformat()}


@router.post("/takedown")
async def submit_takedown(body: SubmitReq, request: Request,
    user: SiteUser | None = Depends(get_optional_site_user), db: AsyncSession = Depends(get_db)) -> dict:
    ok, _ = await SlidingWindowLimiter(get_redis()).acquire(
        ratelimit_key("takedown_ip", get_client_ip(request)), window_sec=3600, limit=5)
    if not ok:
        raise RateLimitError("申请过于频繁，请稍后再试", retry_after_sec=1800)
    probe = await db.get(TakedownProbe, body.probe_token)
    expires_at = probe.expires_at if probe is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if probe is None or expires_at is None or expires_at < utcnow() or probe.status != "completed":
        raise ValidationError("探测结果已失效，请重新检查地址")
    if probe.accessible is True:
        raise ConflictError("该内容目前仍可访问，不能提交删除申请")
    is_owner = bool(user and user.luogu_uid and user.luogu_uid == probe.author_uid)
    reason = "绑定账号本人申请隐藏" if is_owner else (body.reason or "").strip()
    if not is_owner and len(reason) < 10:
        raise ValidationError("请填写至少 10 个字的申请理由")
    duplicate = await db.scalar(select(TakedownRequest.id).where(
        TakedownRequest.target_type == probe.target_type,
        TakedownRequest.target_id == probe.target_id,
        TakedownRequest.status == TakedownStatus.pending,
    ))
    if duplicate is not None:
        raise ConflictError("该内容已有待处理申请")
    # 登录用户未另填邮箱时使用注册邮箱，填写后则以表单中的联系邮箱为准。
    requester_email = (
        str(body.requester_email).lower()
        if body.requester_email
        else (user.email if user else None)
    )
    row = TakedownRequest(requester_user_id=user.id if user else None,
        requester_name=body.requester_name, requester_email=requester_email,
        target_type=probe.target_type, target_id=probe.target_id, target_url=probe.target_url,
        target_author_uid=probe.author_uid, reason=reason,
        status=TakedownStatus.approved if is_owner else TakedownStatus.pending,
        auto_approved=is_owner, handled_at=utcnow() if is_owner else None)
    db.add(row)
    await db.flush()
    if is_owner:
        await apply_takedown(db, row)
    await db.commit()
    return {"id": row.id, "status": row.status.value, "auto_approved": is_owner}
