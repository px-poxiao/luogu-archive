"""基于 Redis 的分布式锁。

用途：
- 同 URL 爬虫幂等（SETNX + TTL 30s）
- 单账号串行化（同一 Cookie 账号不允许并发）
- 保存按钮请求合并（相同目标的第 2~N 个请求等待第 1 个的结果）
"""
from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager

from redis.asyncio import Redis

# Lua 脚本：只释放自己持有的锁（比较 token 再删），避免误删别人的锁
_UNLOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class DistributedLock:
    """简单的 Redis 分布式锁。

    非可重入。可重入需求极少，且容易造成死锁，故暂不支持。
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._unlock = redis.register_script(_UNLOCK_LUA)

    async def acquire(self, key: str, *, ttl_sec: int) -> str | None:
        """尝试加锁。成功返回 token（用于释放），失败返回 None。"""
        token = secrets.token_urlsafe(16)
        ok = await self._redis.set(key, token, nx=True, ex=ttl_sec)
        return token if ok else None

    async def release(self, key: str, token: str) -> bool:
        """释放自己持有的锁。token 不匹配则不删。"""
        result = await self._unlock(keys=[key], args=[token])
        return bool(result)

    @asynccontextmanager
    async def guard(
        self,
        key: str,
        *,
        ttl_sec: int,
        wait_sec: float = 0,
        poll_interval_sec: float = 0.1,
    ):
        """上下文管理器形式：

        async with lock.guard("crawl:article:123", ttl_sec=30) as ok:
            if not ok:
                return  # 已有别的 worker 在爬
            ...

        wait_sec > 0：尝试等待最多 wait_sec 秒直到拿到锁。
        """
        import time as _t

        deadline = _t.monotonic() + wait_sec if wait_sec > 0 else None
        token: str | None = None
        while True:
            token = await self.acquire(key, ttl_sec=ttl_sec)
            if token is not None:
                break
            if deadline is None or _t.monotonic() >= deadline:
                break
            await asyncio.sleep(poll_interval_sec)

        try:
            yield token is not None
        finally:
            if token is not None:
                await self.release(key, token)


# ---------- Key 生成约定 ----------
def lock_key(scope: str, ident: str) -> str:
    """统一 key 前缀。scope: crawl / account / save_dedup ..."""
    return f"lk:{scope}:{ident}"
