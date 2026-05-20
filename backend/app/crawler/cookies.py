"""爬取账号 Cookie 池。

职责：
- 从数据库加载启用的 CrawlerAccount
- 解密 Cookie 字段（Fernet 加密存储）
- 轮换分配（最久未用优先）
- 单账号串行化（通过分布式锁，保号）
- 异常即禁用：403/429/isBanned → 禁用 + 写日志
- 心跳自检：30 分钟扫一次

设计上所有 cookie 不入内存常驻缓存（除非同一个请求上下文内），避免内存泄露老 cookie。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.locks import DistributedLock, lock_key
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.models.admin import CrawlerAccount
from app.models._common import utcnow

log = get_logger(__name__)


@dataclass
class AccountCookies:
    """解密后的 cookie 数据（内存中临时使用，不持久化）。"""

    account_id: int
    luogu_uid: int
    label: str
    uid_value: str
    client_id: str
    c3vk: str | None

    def as_cookie_dict(self) -> dict[str, str]:
        """组装成 httpx cookies 参数。"""
        d = {"_uid": self.uid_value, "__client_id": self.client_id}
        if self.c3vk:
            d["C3VK"] = self.c3vk
        return d


# 加密/解密工具
def _fernet() -> Fernet:
    key = settings.ADMIN_TOTP_ENCRYPTION_KEY.encode()
    # ADMIN_TOTP_ENCRYPTION_KEY 是 Fernet key（url-safe base64 32 bytes）
    return Fernet(key)


def encrypt_cookie(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_cookie(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise CrawlerError("Cookie 解密失败，可能 ADMIN_TOTP_ENCRYPTION_KEY 已换") from e


async def pick_account(session: AsyncSession) -> AccountCookies | None:
    """选取一个可用账号（最久未用优先）。

    节点级速率（CRAWLER_AUTH_RATE_PER_SEC）已经把请求频率压住了，账号级 QPH
    没有再加一层的必要。直接拿最久未用的启用账号。
    """
    q = (
        select(CrawlerAccount)
        .where(CrawlerAccount.enabled.is_(True))
        # MySQL ASC 默认 NULL 在前，刚加的账号 last_used_at=NULL 自然优先选中。
        # 不能用 .nulls_first()，那是 PostgreSQL 方言。
        .order_by(CrawlerAccount.last_used_at.asc())
    )
    result = await session.execute(q)
    accounts = result.scalars().all()

    for acc in accounts:
        # 更新 last_used_at
        acc.last_used_at = utcnow()
        await session.commit()
        return AccountCookies(
            account_id=acc.id,
            luogu_uid=acc.luogu_uid,
            label=acc.label,
            uid_value=decrypt_cookie(acc.uid_value_encrypted),
            client_id=decrypt_cookie(acc.client_id_encrypted),
            c3vk=decrypt_cookie(acc.c3vk_encrypted) if acc.c3vk_encrypted else None,
        )
    return None


@asynccontextmanager
async def lease_account():
    """上下文管理器：租用一个账号，持有期间不许其他 worker 并发使用同一账号。

    用法：
        async with lease_account() as cookies:
            if cookies is None:
                return   # 没可用账号
            result = await fetch_authed(url, cookies=cookies.as_cookie_dict(), ...)
    """
    redis = get_redis()
    lock = DistributedLock(redis)

    async with db_session() as session:
        cookies = await pick_account(session)
        if cookies is None:
            yield None
            return

        # 同一账号串行化
        key = lock_key("account", str(cookies.account_id))
        async with lock.guard(key, ttl_sec=30, wait_sec=15) as got:
            if not got:
                log.warning(
                    "crawler_account.lock_busy",
                    account_id=cookies.account_id,
                )
                yield None
                return
            yield cookies


async def mark_account_failed(
    account_id: int,
    *,
    reason: str,
    disable: bool = False,
) -> None:
    """记录账号失败，必要时禁用。"""
    async with db_session() as session:
        stmt = (
            update(CrawlerAccount)
            .where(CrawlerAccount.id == account_id)
            .values(
                fail_count=CrawlerAccount.fail_count + 1,
                last_status="failed",
                last_checked_at=utcnow(),
                **({"enabled": False, "disabled_reason": reason} if disable else {}),
            )
        )
        await session.execute(stmt)
        await session.commit()
    if disable:
        log.error("crawler_account.disabled", account_id=account_id, reason=reason)
    else:
        log.warning("crawler_account.failed", account_id=account_id, reason=reason)


async def mark_account_ok(account_id: int) -> None:
    """每次请求成功调一下，清除失败计数。"""
    async with db_session() as session:
        stmt = (
            update(CrawlerAccount)
            .where(CrawlerAccount.id == account_id)
            .values(
                fail_count=0,
                last_status="ok",
                last_checked_at=utcnow(),
            )
        )
        await session.execute(stmt)
        await session.commit()
