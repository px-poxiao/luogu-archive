"""管理员认证。

与普通用户分开：必带 2FA，发的 token kind=admin。

端点：
  POST /api/v1/admin/login       { username, password, totp_code } → access token
  GET  /api/v1/admin/me          当前管理员信息
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.auth.deps import get_current_admin
from app.auth.jwt import make_access
from app.auth.passwords import verify_password
from app.auth.totp import decrypt_secret, verify as verify_totp
from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import AuthError, RateLimitError
from app.core.ratelimit import SlidingWindowLimiter, ratelimit_key
from app.core.redis_client import get_redis
from app.models._common import utcnow
from app.models.admin import Admin, AdminAuditLog

router = APIRouter(prefix="/admin", tags=["admin-auth"])


class AdminLoginReq(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str
    totp_code: str = Field(..., min_length=6, max_length=6)


class AdminLoginResp(BaseModel):
    access_token: str
    expires_in: int
    username: str
    display_name: str


class AdminMeResp(BaseModel):
    id: int
    username: str
    display_name: str


@router.post("/login", response_model=AdminLoginResp)
async def admin_login(
    req: AdminLoginReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminLoginResp:
    ip = get_client_ip(request)
    # 限流：同 IP 10 分钟内 20 次（管理员人少，限得严一点）
    ok, _ = await SlidingWindowLimiter(get_redis()).acquire(
        ratelimit_key("admin_login_ip", ip),
        window_sec=600,
        limit=20,
    )
    if not ok:
        raise RateLimitError("登录过于频繁", retry_after_sec=600)

    q = select(Admin).where(Admin.username == req.username)
    admin = (await db.execute(q)).scalar_one_or_none()
    if admin is None or admin.is_disabled:
        raise AuthError("用户名或密码错误")

    if not verify_password(req.password, admin.password_hash):
        # 写审计 + 慢失败
        db.add(
            AdminAuditLog(
                admin_id=admin.id,
                admin_username=admin.username,
                action="login_failed",
                ip=ip,
                ua=request.headers.get("user-agent", "")[:500],
                params={"reason": "wrong_password"},
            )
        )
        await db.commit()
        raise AuthError("用户名或密码错误")

    # TOTP
    try:
        secret = decrypt_secret(admin.totp_secret_encrypted)
    except Exception:
        raise AuthError("管理员 TOTP 配置异常")
    if not verify_totp(secret, req.totp_code):
        db.add(
            AdminAuditLog(
                admin_id=admin.id,
                admin_username=admin.username,
                action="login_failed",
                ip=ip,
                ua=request.headers.get("user-agent", "")[:500],
                params={"reason": "bad_totp"},
            )
        )
        await db.commit()
        raise AuthError("2FA 验证码错误")

    # 登录成功
    admin.last_login_at = utcnow()
    admin.last_login_ip = ip
    db.add(
        AdminAuditLog(
            admin_id=admin.id,
            admin_username=admin.username,
            action="login_success",
            ip=ip,
            ua=request.headers.get("user-agent", "")[:500],
        )
    )
    await db.commit()

    access_token, _ = make_access(str(admin.id), "admin")
    return AdminLoginResp(
        access_token=access_token,
        expires_in=settings.JWT_ACCESS_TTL_SEC,
        username=admin.username,
        display_name=admin.display_name,
    )


@router.get("/me", response_model=AdminMeResp)
async def admin_me(admin: Admin = Depends(get_current_admin)) -> AdminMeResp:
    return AdminMeResp(
        id=admin.id,
        username=admin.username,
        display_name=admin.display_name,
    )
