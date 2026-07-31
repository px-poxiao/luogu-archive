"""Redis 连接管理。

全站共享一个 async redis 客户端池。用途：
- 资源感知型任务队列
- 缓存（HTTP 响应、渲染结果）
- 分布式锁（同 URL 爬虫幂等）
- 限流（滑动窗口、完成冷却门）
- 保存按钮请求合并
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from redis import asyncio as aioredis

from app.core.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

# 模块级单例。首次 get_redis() 时创建。
_redis_client: Redis | None = None


def get_redis() -> Redis:
    """返回进程全局共享的 async Redis 客户端。

    decode_responses=True：所有 bytes 自动解码为 str，避免散落的 decode。
    Lua 脚本传 bytes 的场景目前没有，若以后需要再单独建个 raw client。
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            encoding="utf-8",
            health_check_interval=30,
            socket_keepalive=True,
        )
    return _redis_client


async def close_redis() -> None:
    """应用关停时调用，优雅释放连接。"""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
