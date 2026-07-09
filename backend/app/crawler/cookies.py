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

from app.core.config import settings
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
    """[已废弃] 仅留作历史兼容，新代码应使用 lease_account。

    早期 lease_account 把"选号"和"加锁"分两步做，导致高峰所有 worker 都
    涌向同一个最旧账号 → 锁竞争。现在 lease_account 直接逐个尝试加锁
    + 跳过冲突，本函数无需再独立调用。
    """
    raise RuntimeError("pick_account 已废弃，请使用 lease_account()")


@asynccontextmanager
async def lease_account():
    """上下文管理器：租用一个账号（多账号轮询）。

    注意：已**移除**单账号串行锁，多个 worker 可以并发使用同一账号 cookie。
    全局速率仍由节点级 token bucket（luogu.com 域名桶 1s/req）控制。

    选号策略：用 redis INCR 做全局 round-robin，每次 +1 % len(accounts) 选下一个，
    多 worker 高并发时也能均匀分摊到所有账号上 —— 不再都涌向"最久未用"那一个。

    用法：
        async with lease_account() as cookies:
            if cookies is None:
                return   # 没启用账号
            result = await fetch_authed(url, cookies=cookies.as_cookie_dict(), ...)
    """
    async with db_session() as session:
        q = (
            select(CrawlerAccount)
            .where(CrawlerAccount.enabled.is_(True))
            .order_by(CrawlerAccount.id.asc())  # 稳定顺序，便于 round-robin 索引
        )
        accounts = (await session.execute(q)).scalars().all()
        if not accounts:
            yield None
            return

        # redis 原子自增计数器；多 worker / 多节点都共用一个序列
        redis = get_redis()
        idx = await redis.incr("crawler:account:rr_idx") - 1
        acc = accounts[idx % len(accounts)]

        acc.last_used_at = utcnow()
        await session.commit()
        cookies = AccountCookies(
            account_id=acc.id,
            luogu_uid=acc.luogu_uid,
            label=acc.label,
            uid_value=decrypt_cookie(acc.uid_value_encrypted),
            client_id=decrypt_cookie(acc.client_id_encrypted),
            c3vk=decrypt_cookie(acc.c3vk_encrypted) if acc.c3vk_encrypted else None,
        )
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
