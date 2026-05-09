"""CrawlerNode 抽象基类。

一个节点代表一个独立的"爬虫出口身份"，含：
- node_id：唯一标识，用于队列路由、审计、限流 key
- kind：anon（游客）/ authed（需要 Cookie）
- bind_ip：绑定的出口 IP（可选，单机时为 None）
- rate_per_sec：该节点的令牌桶速率
- 限流 / 熔断状态都基于 Redis，单机多机同构

保号原则（详见 3.md 七.6）：
- 游客节点可以高频
- 认证节点 1 req/6s，单账号每小时 ≤ 300
- 任何节点 403/429 → 该节点冷却；连续 3 节点被封 → 全局冷却
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logging import get_logger
from app.core.ratelimit import TokenBucketLimiter, ratelimit_key

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)


class NodeKind(str, enum.Enum):
    ANON = "anon"
    AUTHED = "authed"


# 熔断状态的 Redis key 生成
def _breaker_key(node_id: str) -> str:
    """节点被封时设置 cooldown 标记。"""
    return f"crawler:breaker:node:{node_id}"


def _global_breaker_key() -> str:
    """全局熔断（连续 N 节点被封时触发）。"""
    return "crawler:breaker:global"


@dataclass
class CrawlerNode:
    """爬虫节点。

    构造时 kind=ANON 的节点共享同一限流 key（所有匿名节点按"单机匿名"限流汇总），
    kind=AUTHED 的节点按 node_id + account_id 独立限流。

    bind_ip: 若不为 None，HTTP 客户端发出请求会通过该出口 IP（多机/多 IP 部署时）。
    """

    node_id: str
    kind: NodeKind
    rate_per_sec: float
    # 桶容量：1 = 严格限速，>1 允许突发
    burst_capacity: int = 1
    # 出口 IP：None = 使用系统默认路由
    bind_ip: str | None = None
    # 可选额外 header
    extra_headers: dict[str, str] = field(default_factory=dict)

    async def try_acquire(self, redis: Redis) -> tuple[bool, int]:
        """向节点令牌桶取一个令牌，返回 (allowed, retry_after_ms)。"""
        # 先检查全局熔断
        if await redis.exists(_global_breaker_key()):
            ttl = await redis.ttl(_global_breaker_key())
            return False, max(ttl, 1) * 1000

        # 再检查本节点熔断
        if await redis.exists(_breaker_key(self.node_id)):
            ttl = await redis.ttl(_breaker_key(self.node_id))
            return False, max(ttl, 1) * 1000

        limiter = TokenBucketLimiter(redis)
        key = ratelimit_key("crawler_node", self.node_id)
        return await limiter.acquire(
            key,
            rate_per_sec=self.rate_per_sec,
            capacity=self.burst_capacity,
        )

    async def trip_breaker(
        self,
        redis: Redis,
        *,
        reason: str,
        cooldown_sec: int | None = None,
    ) -> None:
        """触发本节点熔断。

        同时检查"连续 N 节点被封"条件，若满足则触发全局熔断。
        """
        sec = cooldown_sec if cooldown_sec is not None else settings.CRAWLER_BREAKER_COOLDOWN_SEC
        await redis.setex(_breaker_key(self.node_id), sec, reason)
        log.warning("crawler_node.breaker_tripped", node_id=self.node_id, reason=reason, cooldown=sec)

        # 全局熔断探测：统计最近活跃的被封节点
        tripped_set_key = "crawler:breaker:tripped_nodes"
        # 把自己加入过去 10 分钟内的"被封集合"（ZSET，分数=时间戳）
        import time as _t
        now = _t.time()
        await redis.zadd(tripped_set_key, {self.node_id: now})
        # 清理 10 分钟外的历史
        await redis.zremrangebyscore(tripped_set_key, 0, now - 600)
        count = await redis.zcard(tripped_set_key)
        if count >= settings.CRAWLER_GLOBAL_BREAKER_NODE_THRESHOLD:
            # 全局熔断 10 分钟
            await redis.setex(_global_breaker_key(), 600, f"triggered_by:{self.node_id}")
            log.error(
                "crawler.global_breaker_tripped",
                node_count=count,
                triggered_by=self.node_id,
            )

    async def reset_breaker(self, redis: Redis) -> None:
        """管理员后台或自动恢复后清除熔断。"""
        await redis.delete(_breaker_key(self.node_id))
