"""FastAPI 依赖：当前登录用户 / 当前管理员。"""
from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import safe_decode
from app.core.db import get_db
from app.core.exceptions import AuthError
from app.models.admin import Admin
from app.models.site_user import SiteUser


async def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    return authorization[len(prefix):].strip()


async def get_current_site_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> SiteUser:
    token = await _extract_bearer(authorization)
    if not token:
        raise AuthError("未登录")
    payload = safe_decode(token)
    if payload is None or payload.get("kind") != "site":
        raise AuthError("无效凭证")
    try:
        uid = int(payload["sub"])
    except (KeyError, ValueError):
        raise AuthError("无效凭证")
    u = await db.get(SiteUser, uid)
    if u is None or u.is_banned:
        raise AuthError("账号不存在或已停用")
    return u


async def get_current_admin(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Admin:
    token = await _extract_bearer(authorization)
    if not token:
        raise AuthError("未登录")
    payload = safe_decode(token)
    if payload is None or payload.get("kind") != "admin":
        raise AuthError("无效凭证")
    try:
        aid = int(payload["sub"])
    except (KeyError, ValueError):
        raise AuthError("无效凭证")
    a = await db.get(Admin, aid)
    if a is None or a.is_disabled:
        raise AuthError("管理员账号不存在或已停用")
    return a


async def get_optional_site_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> SiteUser | None:
    """允许匿名，登录了就返回用户，否则 None。"""
    try:
        return await get_current_site_user(authorization, db)
    except AuthError:
        return None
