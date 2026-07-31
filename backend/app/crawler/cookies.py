"""爬取账号 Cookie 池。

职责：
- 从数据库加载启用的 CrawlerAccount
- 解密 Cookie 字段（Fernet 加密存储）
- 队列任务按最早可用时间选择账号
- 单账号串行化并执行完成后冷却
- 异常即禁用：403/429/isBanned → 禁用 + 写日志
- 心跳自检：30 分钟扫一次

设计上所有 cookie 不入内存常驻缓存（除非同一个请求上下文内），避免内存泄露老 cookie。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.models._common import utcnow
from app.models.admin import CrawlerAccount
from app.tasks.broker import account_disabled_key
from app.tasks.runtime import current_async_reservation

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
async def lease_account(*, cn: bool = False):
    """上下文管理器：租用一个账号（多账号轮询）。

    同一账号跨 worker 严格串行；调用方退出上下文（包括写库和审计完成）后，
    才开始 CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC 冷却。
    ``cn=True`` 用于访问 luogu.com.cn，并与该域名的匿名请求共享限速门。

    选号策略：Redis INCR 决定轮询起点，再依次原子尝试所有账号的冷却门。
    优先拿当前空闲账号；全部忙时让 actor 延迟重入队，把执行槽让给下一优先级。

    用法：
        async with lease_account() as cookies:
            if cookies is None:
                return   # 没启用账号
            result = await fetch_authed(
                url,
                cookies=cookies.as_cookie_dict(),
                account_id=cookies.account_id,
                ...,
            )
    """
    reservation = current_async_reservation()
    reserved_account_id = reservation.account_id if reservation is not None else None
    candidates: list[AccountCookies] = []
    async with db_session() as session:
        q = (
            select(CrawlerAccount)
            .where(CrawlerAccount.enabled.is_(True))
            .order_by(CrawlerAccount.id.asc())  # 稳定顺序，便于 round-robin 索引
        )
        if reserved_account_id is not None:
            # 账号由队列按最短剩余冷却时间选定，这里只加载对应 Cookie。
            q = q.where(CrawlerAccount.id == reserved_account_id)
        accounts = (await session.execute(q)).scalars().all()
        if not accounts:
            yield None
            return
        for acc in accounts:
            candidates.append(
                AccountCookies(
                    account_id=acc.id,
                    luogu_uid=acc.luogu_uid,
                    label=acc.label,
                    uid_value=decrypt_cookie(acc.uid_value_encrypted),
                    client_id=decrypt_cookie(acc.client_id_encrypted),
                    c3vk=(
                        decrypt_cookie(acc.c3vk_encrypted)
                        if acc.c3vk_encrypted
                        else None
                    ),
                )
            )

    # 延迟导入避免 cookies -> http -> crawler 模块初始化环。
    if reserved_account_id is not None:
        if not candidates:
            raise CrawlerError(f"队列预留的账号 {reserved_account_id} 已被禁用或删除")
        async with db_session() as session:
            await session.execute(
                update(CrawlerAccount)
                .where(CrawlerAccount.id == reserved_account_id)
                .values(last_used_at=utcnow())
            )
            await session.commit()
        # 资源门由 worker 在任务结束时统一转入冷却，避免业务层重复释放。
        yield candidates[0]
        return

    from app.core.exceptions import CrawlerCooldownDeferred
    from app.crawler.http import crawler_task_cooldown, try_acquire_account_slot
    from app.crawler.nodes import NodeKind, get_default_node

    redis = get_redis()
    start = (await redis.incr("crawler:account:rr_idx") - 1) % len(candidates)
    ordered = candidates[start:] + candidates[:start]
    selected: AccountCookies | None = None
    selected_slot: tuple[str, str] | None = None

    retry_after: list[int] = []
    for candidate in ordered:
        slot, retry_after_ms = await try_acquire_account_slot(
            candidate.account_id,
            redis,
        )
        if slot is not None:
            selected = candidate
            selected_slot = slot
            break
        retry_after.append(retry_after_ms)
    if selected is None:
        raise CrawlerCooldownDeferred(min(retry_after or [1000]))

    node = get_default_node(NodeKind.AUTHED, cn=cn)
    async with crawler_task_cooldown(
        node,
        redis,
        account_id=selected.account_id,
        account_slot=selected_slot,
        defer_when_busy=True,
    ):
        async with db_session() as session:
            await session.execute(
                update(CrawlerAccount)
                .where(CrawlerAccount.id == selected.account_id)
                .values(last_used_at=utcnow())
            )
            await session.commit()
        yield selected


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
        # 新队列的账号池位于 Redis；禁用后立即移除，避免同步周期内再次选中。
        try:
            redis = get_redis()
            pipe = redis.pipeline(transaction=True)
            pipe.set(account_disabled_key(account_id), "1")
            pipe.zrem("rq:accounts:available", account_id)
            await pipe.execute()
        except Exception as exc:
            # 数据库是账号启用状态的准确信息源；Redis 恢复后由 worker 定时同步修正。
            log.warning(
                "crawler_account.queue_remove_failed",
                account_id=account_id,
                error=str(exc),
            )
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
