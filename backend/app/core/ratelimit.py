"""基于 Redis 的限流器 —— 滑动窗口与完成冷却门。

用途：
- IP 级：用户点保存按钮的滑动窗口
- 爬虫级：请求完成后才开始计时的串行冷却门

所有实现走 Lua 脚本保证原子性。即使将来加多机，同一 Redis 就能协调。
"""
from __future__ import annotations

import secrets

from redis.asyncio import Redis

# ---------- Lua 脚本：滑动窗口计数器 ----------
# KEYS[1] = 计数器 key（ZSET）
# ARGV[1] = 当前时间戳（秒级浮点，传进来避免各机器时钟漂移）
# ARGV[2] = 窗口长度（秒）
# ARGV[3] = 最大次数
# 返回：{allowed (0/1), current_count}
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local key = KEYS[1]

-- 清理窗口外的旧条目
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

local count = redis.call('ZCARD', key)
if count < limit then
    -- 允许，记录本次调用
    redis.call('ZADD', key, now, now .. ':' .. math.random())
    redis.call('EXPIRE', key, window + 1)
    return {1, count + 1}
else
    return {0, count}
end
"""


# ---------- Lua 脚本：请求完成后冷却 ----------
# 请求期间 key 保存随机 token 并带租约；请求结束后，持有者把同一个 key
# 原子替换为 cooldown 标记。这样下一请求只能在冷却到期后进入。
_COMPLETION_COOLDOWN_ACQUIRE_LUA = """
local key = KEYS[1]
local token = ARGV[1]
local lease_ms = tonumber(ARGV[2])

local acquired = redis.call('SET', key, token, 'NX', 'PX', lease_ms)
if acquired then
    return {1, 0}
end

local ttl = redis.call('PTTL', key)
if ttl < 1 then
    ttl = 1
end
return {0, ttl}
"""

_COMPLETION_COOLDOWN_FINISH_LUA = """
local key = KEYS[1]
local token = ARGV[1]
local cooldown_ms = tonumber(ARGV[2])

if redis.call('GET', key) ~= token then
    return 0
end

redis.call('PSETEX', key, cooldown_ms, 'cooldown')
return 1
"""

_COMPLETION_COOLDOWN_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class SlidingWindowLimiter:
    """滑动窗口计数器。适合"X 秒内最多 N 次"场景。"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_SLIDING_WINDOW_LUA)

    async def acquire(
        self,
        key: str,
        *,
        window_sec: int,
        limit: int,
        now_sec: float | None = None,
    ) -> tuple[bool, int]:
        """尝试获取一次额度。

        返回 (allowed, current_count)。allowed=False 表示超限。
        """
        import time as _t

        if now_sec is None:
            now_sec = _t.time()
        allowed, count = await self._script(
            keys=[key],
            args=[now_sec, window_sec, limit],
        )
        return bool(allowed), int(count)


class CompletionCooldownLimiter:
    """串行请求，并从上一请求完成时开始计算冷却时间。

    请求执行期间使用带 TTL 的所有权 token 占住 key；正常、失败或超时结束后，
    持有者调用 ``finish`` 把 key 切换为冷却状态。若进程在请求期间崩溃，租约
    到期后会自动恢复，不会永久锁死。
    """

    def __init__(self, redis: Redis) -> None:
        self._acquire_script = redis.register_script(_COMPLETION_COOLDOWN_ACQUIRE_LUA)
        self._finish_script = redis.register_script(_COMPLETION_COOLDOWN_FINISH_LUA)
        self._release_script = redis.register_script(_COMPLETION_COOLDOWN_RELEASE_LUA)

    async def acquire(self, key: str, *, lease_sec: float) -> tuple[str | None, int]:
        """尝试占用冷却门，返回 ``(token, retry_after_ms)``。"""
        token = secrets.token_urlsafe(18)
        lease_ms = max(1, int(lease_sec * 1000))
        allowed, retry_after_ms = await self._acquire_script(
            keys=[key],
            args=[token, lease_ms],
        )
        return (token if allowed else None), int(retry_after_ms)

    async def finish(self, key: str, token: str, *, cooldown_sec: float) -> bool:
        """结束当前请求，并从此刻开始冷却。"""
        cooldown_ms = max(1, int(cooldown_sec * 1000))
        result = await self._finish_script(
            keys=[key],
            args=[token, cooldown_ms],
        )
        return bool(result)

    async def release(self, key: str, token: str) -> bool:
        """请求尚未发出时取消占用，不进入冷却。"""
        result = await self._release_script(keys=[key], args=[token])
        return bool(result)


# ---------- Key 生成约定 ----------
def ratelimit_key(scope: str, ident: str) -> str:
    """统一 key 前缀，便于运维按 scope 清理。

    scope: save_ip / crawler_node / crawler_account / captcha_ip ...
    """
    return f"rl:{scope}:{ident}"
