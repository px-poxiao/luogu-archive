"""JWT 签发与校验。

两种 token：
- access：15 分钟，放在 Authorization 头（Bearer）
- refresh：7 天，HttpOnly cookie（本应用不在这文件里直接操作 cookie，
  由 FastAPI 路由决定怎么存）

payload 约定：
{
  "sub": str,        # 用户 id（site_user.id 或 admin.id）
  "kind": "site" | "admin" | "refresh",
  "jti": str,        # 吊销用
  "exp": int,
}
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt

from app.core.config import settings

_ALGO = "HS256"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGO)


def make_access(sub: str, kind: Literal["site", "admin"]) -> tuple[str, str]:
    """返回 (token, jti)。"""
    jti = secrets.token_urlsafe(12)
    payload = {
        "sub": sub,
        "kind": kind,
        "jti": jti,
        "exp": int((_now() + timedelta(seconds=settings.JWT_ACCESS_TTL_SEC)).timestamp()),
    }
    return _encode(payload), jti


def make_refresh(sub: str) -> tuple[str, str]:
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": sub,
        "kind": "refresh",
        "jti": jti,
        "exp": int((_now() + timedelta(seconds=settings.JWT_REFRESH_TTL_SEC)).timestamp()),
    }
    return _encode(payload), jti


def decode(token: str) -> dict[str, Any]:
    """校验并返回 payload，失败抛 JWTError。"""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGO])


def safe_decode(token: str) -> dict[str, Any] | None:
    try:
        return decode(token)
    except JWTError:
        return None
