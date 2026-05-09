"""基于 Redis 的限流器 —— 滑动窗口 + 令牌桶。

用途：
- IP 级：用户点保存按钮的滑动窗口
- 节点级：爬虫每个 CrawlerNode 的令牌桶（1 req / 3s 或 1 req / 6s）
- 账号级：每账号每小时 QPH

所有实现走 Lua 脚本保证原子性。即使将来加多机，同一 Redis 就能协调。
"""
from __future__ import annotations

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


# ---------- Lua 脚本：令牌桶（平滑限流） ----------
# KEYS[1] = 桶 key（HASH）
# ARGV[1] = 当前时间戳（秒级浮点）
# ARGV[2] = 速率（tokens/sec）
# ARGV[3] = 桶容量
# 返回：{allowed (0/1), retry_after_ms}
_TOKEN_BUCKET_LUA = """
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local key = KEYS[1]

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local last_ts = tonumber(state[2])

if tokens == nil then
    tokens = capacity
    last_ts = now
else
    -- 按时间流逝补充令牌
    local delta = (now - last_ts) * rate
    tokens = math.min(capacity, tokens + delta)
    last_ts = now
end

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'ts', last_ts)
    redis.call('EXPIRE', key, math.ceil(capacity / rate) + 10)
    return {1, 0}
else
    -- 差多少令牌 * 单令牌时间 = 还要等多久
    local need = 1 - tokens
    local wait_ms = math.ceil(need / rate * 1000)
    redis.call('HMSET', key, 'tokens', tokens, 'ts', last_ts)
    redis.call('EXPIRE', key, math.ceil(capacity / rate) + 10)
    return {0, wait_ms}
end
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


class TokenBucketLimiter:
    """令牌桶。适合"平均 X req/sec，允许小突发"场景，用于爬虫节点。"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_TOKEN_BUCKET_LUA)

    async def acquire(
        self,
        key: str,
        *,
        rate_per_sec: float,
        capacity: int = 1,
        now_sec: float | None = None,
    ) -> tuple[bool, int]:
        """尝试取一个令牌。

        返回 (allowed, retry_after_ms)。若 allowed=False，稍后 retry_after_ms 再试。
        """
        import time as _t

        if now_sec is None:
            now_sec = _t.time()
        allowed, wait_ms = await self._script(
            keys=[key],
            args=[now_sec, rate_per_sec, capacity],
        )
        return bool(allowed), int(wait_ms)


# ---------- Key 生成约定 ----------
def ratelimit_key(scope: str, ident: str) -> str:
    """统一 key 前缀，便于运维按 scope 清理。

    scope: save_ip / crawler_node / crawler_account / captcha_ip ...
    """
    return f"rl:{scope}:{ident}"
