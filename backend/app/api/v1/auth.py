"""站内用户（邮箱注册）认证 + 关注。

端点：
  POST /api/v1/auth/register        注册（发验证邮件）
  GET  /api/v1/auth/verify          点邮件链接来这里
  POST /api/v1/auth/login           登录 → 返回 access token + 设置 refresh cookie
  POST /api/v1/auth/refresh         刷新 access
  POST /api/v1/auth/logout          登出
  GET  /api/v1/auth/me              当前用户信息

  POST /api/v1/follows              关注 {uid}
  DELETE /api/v1/follows/{uid}      取消关注
  GET  /api/v1/follows              我的关注列表
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.auth.deps import get_current_site_user
from app.auth.jwt import make_access, make_refresh, safe_decode
from app.auth.passwords import hash_password, verify_password
from app.core.captcha import verify_captcha
from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import (
    AuthError,
    CaptchaRequired,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.mail import send_verification_email
from app.core.ratelimit import SlidingWindowLimiter, ratelimit_key
from app.core.redis_client import get_redis
from app.models._common import utcnow
from app.models.site_user import SiteSession, SiteUser, SiteUserFollow

router = APIRouter(tags=["auth"])
log = get_logger(__name__)

REFRESH_COOKIE_NAME = "la_refresh"


# ============================================================
# Schemas
# ============================================================

class RegisterReq(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=16)
    captcha_token: str | None = None


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class AuthResp(BaseModel):
    access_token: str
    expires_in: int
    display_name: str
    email: EmailStr
    email_verified: bool


class MeResp(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    email_verified: bool
    follow_count: int


# ============================================================
# 密码强度校验
# ============================================================

_PWD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


def _check_password(pw: str) -> None:
    if not _PWD_RE.match(pw):
        raise ValidationError("密码至少 8 位，且包含字母和数字")


# ============================================================
# 注册
# ============================================================

@router.post("/auth/register", response_model=dict)
async def register(
    req: RegisterReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _check_password(req.password)
    ip = get_client_ip(request)

    # 限流：同 IP 每小时最多 5 次注册
    redis = get_redis()
    ok, _ = await SlidingWindowLimiter(redis).acquire(
        ratelimit_key("register_ip", ip),
        window_sec=3600,
        limit=5,
    )
    if not ok:
        raise RateLimitError("注册过于频繁", retry_after_sec=1800)

    # 所有用户注册都必须通过人机验证；provider=none 时跳过，方便本地开发。
    if settings.CAPTCHA_PROVIDER != "none":
        if not req.captcha_token:
            raise CaptchaRequired("请先完成人机验证")
        if not await verify_captcha(req.captcha_token, ip=ip):
            raise CaptchaRequired("人机验证失败，请重试")

    # 检查邮箱已用
    q = select(SiteUser).where(SiteUser.email == req.email.lower())
    if (await db.execute(q)).scalar_one_or_none() is not None:
        raise ConflictError("该邮箱已注册")

    token = secrets.token_urlsafe(32)
    user = SiteUser(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        display_name=req.display_name,
        email_verified=False,
        email_verification_token=token,
        email_verification_expires=utcnow() + timedelta(hours=24),
    )
    db.add(user)
    await db.commit()

    verify_url = f"{settings.WEB_PUBLIC_ORIGIN}/auth/verify?token={token}"
    await send_verification_email(req.email, verify_url)
    return {"message": "已发送验证邮件，请查收"}


class ResendVerifyReq(BaseModel):
    email: EmailStr


@router.post("/auth/resend-verification", response_model=dict)
async def resend_verification(
    req: ResendVerifyReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重发验证邮件。

    - 同一邮箱 60s 冷却（redis NX）
    - 同 IP 每小时最多 5 次（与注册共享额度精神，独立 key）
    - 不泄露邮箱是否存在 / 是否已验证：一律返回同样的成功文案
    """
    redis = get_redis()
    email_lower = req.email.lower()

    # 同 IP 每小时 5 次
    ok, _ = await SlidingWindowLimiter(redis).acquire(
        ratelimit_key("resend_verify_ip", get_client_ip(request)),
        window_sec=3600,
        limit=5,
    )
    if not ok:
        raise RateLimitError("操作过于频繁", retry_after_sec=1800)

    # 同邮箱 60s 冷却
    cd_key = f"auth:resend_verify_cd:{email_lower}"
    if not await redis.set(cd_key, "1", ex=60, nx=True):
        raise RateLimitError("发送过于频繁，请 60 秒后再试", retry_after_sec=60)

    generic_resp = {"message": "若该邮箱待验证，我们已重新发送验证邮件"}

    q = select(SiteUser).where(SiteUser.email == email_lower)
    user = (await db.execute(q)).scalar_one_or_none()
    # 邮箱不存在 / 已验证：静默返回，不泄露状态（冷却已扣）
    if user is None or user.email_verified:
        return generic_resp

    # 重新生成 token + 续期 24h
    token = secrets.token_urlsafe(32)
    user.email_verification_token = token
    user.email_verification_expires = utcnow() + timedelta(hours=24)
    await db.commit()

    verify_url = f"{settings.WEB_PUBLIC_ORIGIN}/auth/verify?token={token}"
    await send_verification_email(user.email, verify_url)
    return generic_resp


@router.get("/auth/verify")
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(SiteUser).where(SiteUser.email_verification_token == token)
    user = (await db.execute(q)).scalar_one_or_none()
    if user is None:
        raise NotFoundError("验证链接无效")
    expires = user.email_verification_expires
    # MySQL DATETIME 读回来是 naive，补 UTC 时区再跟 aware 的 utcnow() 比较，
    # 否则 offset-naive vs offset-aware 比较会抛 TypeError → 500。
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and expires < utcnow():
        raise ValidationError("验证链接已过期，请重新注册")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires = None
    await db.commit()
    return {"message": "邮箱验证成功，请返回登录"}


# ============================================================
# 登录 / 登出 / 刷新
# ============================================================

def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/auth/login", response_model=AuthResp)
async def login(
    req: LoginReq,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResp:
    ip = get_client_ip(request)

    # 限流 + 锁定
    redis = get_redis()
    ok, _ = await SlidingWindowLimiter(redis).acquire(
        ratelimit_key("login_ip", ip),
        window_sec=300,
        limit=20,
    )
    if not ok:
        raise RateLimitError("登录过于频繁", retry_after_sec=300)

    q = select(SiteUser).where(SiteUser.email == req.email.lower())
    user = (await db.execute(q)).scalar_one_or_none()
    if user is None:
        raise AuthError("邮箱或密码错误")
    if user.is_banned:
        raise AuthError("账号已停用")
    locked = user.locked_until
    if locked is not None and locked.tzinfo is None:
        locked = locked.replace(tzinfo=timezone.utc)
    if locked and locked > utcnow():
        raise AuthError(f"账号已锁定，请稍后再试")

    if not verify_password(req.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = utcnow() + timedelta(minutes=15)
            user.failed_login_count = 0
        await db.commit()
        raise AuthError("邮箱或密码错误")

    if not user.email_verified:
        raise AuthError("请先验证邮箱")

    # 登录成功
    user.failed_login_count = 0
    user.last_login_at = utcnow()
    user.last_login_ip = ip

    access_token, _ = make_access(str(user.id), "site")
    refresh_token, refresh_jti = make_refresh(str(user.id))

    db.add(
        SiteSession(
            site_user_id=user.id,
            token_hash=_hash_refresh(refresh_token),
            ip=ip,
            ua=request.headers.get("user-agent", "")[:500],
            expires_at=utcnow() + timedelta(seconds=settings.JWT_REFRESH_TTL_SEC),
        )
    )
    await db.commit()

    # refresh 放 HttpOnly cookie
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.JWT_REFRESH_TTL_SEC,
        httponly=True,
        secure=settings.APP_ENV != "development",
        samesite="strict",
        path="/api/v1/auth",  # 限制只发给 auth 路由
    )

    return AuthResp(
        access_token=access_token,
        expires_in=settings.JWT_ACCESS_TTL_SEC,
        display_name=user.display_name,
        email=user.email,
        email_verified=user.email_verified,
    )


@router.post("/auth/refresh", response_model=AuthResp)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResp:
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise AuthError("无 refresh token")
    payload = safe_decode(raw)
    if payload is None or payload.get("kind") != "refresh":
        raise AuthError("refresh token 无效")

    th = _hash_refresh(raw)
    q = select(SiteSession).where(SiteSession.token_hash == th)
    session_row = (await db.execute(q)).scalar_one_or_none()
    if session_row is None or session_row.revoked_at is not None:
        raise AuthError("session 已失效")

    user = await db.get(SiteUser, session_row.site_user_id)
    if user is None or user.is_banned:
        raise AuthError("账号不存在或已停用")

    access_token, _ = make_access(str(user.id), "site")
    return AuthResp(
        access_token=access_token,
        expires_in=settings.JWT_ACCESS_TTL_SEC,
        display_name=user.display_name,
        email=user.email,
        email_verified=user.email_verified,
    )


@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw:
        th = _hash_refresh(raw)
        q = select(SiteSession).where(SiteSession.token_hash == th)
        row = (await db.execute(q)).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = utcnow()
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")
    return {"message": "已登出"}


@router.get("/auth/me", response_model=MeResp)
async def me(
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> MeResp:
    q = select(func.count()).where(SiteUserFollow.site_user_id == user.id)
    cnt = int((await db.execute(q)).scalar_one())
    return MeResp(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified,
        follow_count=cnt,
    )


# ============================================================
# 关注
# ============================================================

class FollowReq(BaseModel):
    uid: int = Field(..., gt=0)


@router.post("/follows")
async def follow(
    req: FollowReq,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 上限 100
    q = select(func.count()).where(SiteUserFollow.site_user_id == user.id)
    cnt = int((await db.execute(q)).scalar_one())
    if cnt >= 100:
        raise ConflictError("关注数已达上限（100）")

    # 幂等
    q = select(SiteUserFollow).where(
        SiteUserFollow.site_user_id == user.id,
        SiteUserFollow.target_luogu_uid == req.uid,
    )
    if (await db.execute(q)).scalar_one_or_none() is not None:
        return {"message": "已关注"}

    db.add(SiteUserFollow(site_user_id=user.id, target_luogu_uid=req.uid))
    await db.commit()

    # 触发一次用户主页爬取（把目标 uid 拉到本站）
    from app.tasks.actors.crawl import crawl_user
    crawl_user.send(req.uid, "manual")
    return {"message": "已关注"}


@router.delete("/follows/{uid}")
async def unfollow(
    uid: int,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(SiteUserFollow).where(
        SiteUserFollow.site_user_id == user.id,
        SiteUserFollow.target_luogu_uid == uid,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        return {"message": "未关注过"}
    await db.delete(row)
    await db.commit()
    return {"message": "已取消关注"}


@router.get("/follows")
async def list_follows(
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = (
        select(SiteUserFollow)
        .where(SiteUserFollow.site_user_id == user.id)
        .order_by(SiteUserFollow.created_at.desc())
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {"uid": r.target_luogu_uid, "created_at": r.created_at.isoformat()}
        for r in rows
    ]
