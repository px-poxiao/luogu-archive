"""资源感知型 Redis 任务队列。

这套队列替代 Dramatiq 的“先取消息、再检查限速”模型。任务在依赖满足前始终
留在 pending 集合中；worker 通过 Lua 原子完成依赖检查、账号选择、资源预留和
任务领取，因此可以安全地横向增加多台 worker。
"""
from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from redis import Redis

from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

QUEUE_CRAWL_HI = "crawler.hi"
QUEUE_CRAWL_MID = "crawler.mid"
QUEUE_CRAWL_LOW = "crawler.low"
QUEUE_ORDER = (QUEUE_CRAWL_HI, QUEUE_CRAWL_MID, QUEUE_CRAWL_LOW)

_TASK_PREFIX = "rq:task:"
_PENDING_PREFIX = "rq:pending:"
_LANES_PREFIX = "rq:lanes:"
_INFLIGHT_KEY = "rq:inflight"
_ACCOUNTS_KEY = "rq:accounts:available"
_ACCOUNT_DISABLED_PREFIX = "rq:account:disabled:"
_SEQUENCE_KEY = "rq:sequence"
_WAKEUP_KEY = "rq:wakeup"
_DEAD_KEY = "rq:dead"


class TaskDomain(StrEnum):
    """任务访问的目标域名。``none`` 表示纯计算或纯数据库任务。"""

    NONE = "none"
    COM = "com"
    CN = "cn"


@dataclass(frozen=True, slots=True)
class TaskResources:
    """任务在开始执行前必须预留的共享资源。"""

    domain: TaskDomain = TaskDomain.NONE
    account: bool = False

    def __post_init__(self) -> None:
        if self.account and self.domain == TaskDomain.NONE:
            raise ValueError("账号任务必须同时声明目标域名")

    @property
    def lane(self) -> str:
        identity = "auth" if self.account else "anon"
        return "cpu" if self.domain == TaskDomain.NONE else f"{self.domain.value}:{identity}"

    @property
    def node_kind(self) -> str:
        return "authed" if self.account else "anon"


NO_RESOURCES = TaskResources()
ANON_COM = TaskResources(TaskDomain.COM)
AUTH_COM = TaskResources(TaskDomain.COM, account=True)
ANON_CN = TaskResources(TaskDomain.CN)
AUTH_CN = TaskResources(TaskDomain.CN, account=True)

ResourceResolver = Callable[[tuple[Any, ...], dict[str, Any]], TaskResources]


def account_disabled_key(account_id: int | str) -> str:
    """返回账号禁用标记；异步业务层与同步队列共用同一命名。"""

    return f"{_ACCOUNT_DISABLED_PREFIX}{int(account_id)}"


@dataclass(frozen=True, slots=True)
class TaskMessage:
    """投递结果；保留 ``message_id`` 兼容保存接口的任务编号。"""

    message_id: str


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """worker 已经原子领取并预留资源的一条任务。"""

    task_id: str
    actor_name: str
    queue_name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    attempts: int
    claim_token: str
    domain: TaskDomain
    account_id: int | None
    domain_key: str | None
    account_key: str | None


P = ParamSpec("P")
R = TypeVar("R")


class TaskActor:
    """可调用的任务定义，同时提供与旧 actor 相近的 ``send`` 接口。"""

    def __init__(
        self,
        broker: ResourceQueueBroker,
        fn: Callable[P, R],
        *,
        queue_name: str,
        resources: TaskResources | ResourceResolver,
        max_retries: int,
        min_backoff: int,
        max_backoff: int,
        throws: tuple[type[BaseException], ...],
    ) -> None:
        self.broker = broker
        self.fn = fn
        self.actor_name = fn.__name__
        self.queue_name = queue_name
        self.resources = resources
        self.max_retries = max(0, int(max_retries))
        self.min_backoff = max(0, int(min_backoff))
        self.max_backoff = max(self.min_backoff, int(max_backoff))
        self.throws = throws

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return self.fn(*args, **kwargs)

    def resolve_resources(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> TaskResources:
        if isinstance(self.resources, TaskResources):
            return self.resources
        return self.resources(args, kwargs)

    def send(self, *args: Any, **kwargs: Any) -> TaskMessage:
        return self.broker.enqueue_actor(self, args=args, kwargs=kwargs)

    def send_with_options(
        self,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        delay: int = 0,
        message_id: str | None = None,
    ) -> TaskMessage:
        return self.broker.enqueue_actor(
            self,
            args=args,
            kwargs=kwargs or {},
            delay_ms=max(0, int(delay)),
            message_id=message_id,
        )


# Lua 在一个事务中完成入队，保证 task hash 和 pending 索引不会只写一半。
_ENQUEUE_LUA = r"""
local task_key = KEYS[1]
local pending_key = KEYS[2]
local lanes_key = KEYS[3]
local wakeup_key = KEYS[4]
local sequence_key = KEYS[5]

if redis.call('EXISTS', task_key) == 1 then
    return 0
end

local sequence = redis.call('INCR', sequence_key)
redis.call('HSET', task_key,
    'task_id', ARGV[1],
    'actor', ARGV[2],
    'queue', ARGV[3],
    'lane', ARGV[4],
    'domain', ARGV[5],
    'account', ARGV[6],
    'node_kind', ARGV[7],
    'args', ARGV[8],
    'kwargs', ARGV[9],
    'state', 'pending',
    'attempts', '0',
    'max_retries', ARGV[10],
    'min_backoff', ARGV[11],
    'max_backoff', ARGV[12],
    'sequence', sequence,
    'not_before', ARGV[13],
    'created_at', ARGV[14]
)
redis.call('ZADD', pending_key, ARGV[13], ARGV[1])
redis.call('SADD', lanes_key, ARGV[4])
redis.call('LPUSH', wakeup_key, '1')
redis.call('LTRIM', wakeup_key, 0, 999)
return sequence
"""


# 每次只检查一种优先级。Python 始终按 hi -> mid -> low 调用，因此保持严格优先级。
# 同一优先级按依赖签名拆成通道，阻塞的账号任务不会挡住可运行的匿名任务。
_CLAIM_LUA = r"""
local lanes_key = KEYS[1]
local inflight_key = KEYS[2]
local accounts_key = KEYS[3]
local global_breaker_key = KEYS[4]

local now = tonumber(ARGV[1])
local lease_ms = tonumber(ARGV[2])
local worker_id = ARGV[3]
local token = ARGV[4]
local task_prefix = ARGV[5]
local pending_prefix = ARGV[6]
local queue_name = ARGV[7]
local node_scope = ARGV[8]
local node_tail = ARGV[9]
local account_qph = tonumber(ARGV[10])

local selected_id = nil
local selected_lane = nil
local selected_sequence = nil
local selected_domain_key = nil
local selected_account_key = nil
local selected_account_id = nil
local selected_account_usage_key = nil

local lanes = redis.call('SMEMBERS', lanes_key)
for _, lane in ipairs(lanes) do
    local pending_key = pending_prefix .. queue_name .. ':' .. lane
    local ids = redis.call('ZRANGEBYSCORE', pending_key, '-inf', now, 'LIMIT', 0, 1)
    local task_id = ids[1]
    if task_id then
        local task_key = task_prefix .. task_id
        if redis.call('HGET', task_key, 'state') ~= 'pending' then
            redis.call('ZREM', pending_key, task_id)
        else
            local domain = redis.call('HGET', task_key, 'domain') or 'none'
            local needs_account = redis.call('HGET', task_key, 'account') == '1'
            local node_kind = redis.call('HGET', task_key, 'node_kind') or 'anon'
            local runnable = true
            local domain_key = nil
            local account_key = nil
            local account_id = nil
            local account_usage_key = nil

            if domain ~= 'none' then
                if redis.call('EXISTS', global_breaker_key) == 1 then
                    runnable = false
                end
                local suffix = domain == 'cn' and '-cn' or ''
                local node_id = node_scope .. '-' .. node_kind .. suffix .. node_tail
                if redis.call('EXISTS', 'crawler:breaker:node:' .. node_id) == 1 then
                    runnable = false
                end
                local host = domain == 'cn' and 'luogu.com.cn' or 'luogu.com'
                domain_key = 'rl:crawler_node:' .. node_scope .. ':domain:' .. host
                if redis.call('EXISTS', domain_key) == 1 then
                    runnable = false
                end
            end

            if runnable and needs_account then
                local account_ids = redis.call('ZRANGE', accounts_key, 0, 63)
                for _, candidate_id in ipairs(account_ids) do
                    local estimated_at = tonumber(redis.call('ZSCORE', accounts_key, candidate_id)) or 0
                    local candidate_key = 'rl:crawler_account_request:' .. candidate_id
                    local usage_key = 'rq:account:usage:' .. candidate_id
                    redis.call('ZREMRANGEBYSCORE', usage_key, '-inf', now - 3600000)
                    local usage_count = redis.call('ZCARD', usage_key)
                    if usage_count >= account_qph then
                        local oldest = redis.call('ZRANGE', usage_key, 0, 0)
                        if oldest[1] then
                            local oldest_at = tonumber(redis.call('ZSCORE', usage_key, oldest[1]))
                            redis.call('ZADD', accounts_key, oldest_at + 3600000, candidate_id)
                        end
                    elseif estimated_at <= now and redis.call('EXISTS', candidate_key) == 0 then
                        account_id = candidate_id
                        account_key = candidate_key
                        account_usage_key = usage_key
                        break
                    end
                    if redis.call('EXISTS', candidate_key) == 1 then
                        local ttl = redis.call('PTTL', candidate_key)
                        if ttl > 0 then
                            redis.call('ZADD', accounts_key, now + ttl, candidate_id)
                        end
                    end
                end
                if not account_id then
                    runnable = false
                end
            end

            if runnable then
                local sequence = tonumber(redis.call('HGET', task_key, 'sequence')) or 0
                if not selected_id or sequence < selected_sequence then
                    selected_id = task_id
                    selected_lane = lane
                    selected_sequence = sequence
                    selected_domain_key = domain_key
                    selected_account_key = account_key
                    selected_account_id = account_id
                    selected_account_usage_key = account_usage_key
                end
            end
        end
    end
end

if not selected_id then
    return {}
end

-- Lua 脚本串行执行，检查后到 SET 之前不会有其他 worker 插入，因此这里必定成功。
if selected_domain_key then
    redis.call('PSETEX', selected_domain_key, lease_ms, token)
end
if selected_account_key then
    redis.call('PSETEX', selected_account_key, lease_ms, token)
    redis.call('ZADD', accounts_key, now + lease_ms, selected_account_id)
    redis.call('ZADD', selected_account_usage_key, now, token)
    redis.call('PEXPIRE', selected_account_usage_key, 3601000)
end

local task_key = task_prefix .. selected_id
local pending_key = pending_prefix .. queue_name .. ':' .. selected_lane
redis.call('ZREM', pending_key, selected_id)
if redis.call('ZCARD', pending_key) == 0 then
    redis.call('SREM', lanes_key, selected_lane)
end
redis.call('ZADD', inflight_key, now + lease_ms, selected_id)
redis.call('HSET', task_key,
    'state', 'inflight',
    'worker_id', worker_id,
    'claim_token', token,
    'claimed_at', now,
    'lease_until', now + lease_ms,
    'domain_key', selected_domain_key or '',
    'account_key', selected_account_key or '',
    'account_id', selected_account_id or ''
)

return redis.call('HMGET', task_key,
    'task_id', 'actor', 'queue', 'args', 'kwargs', 'attempts', 'claim_token',
    'domain', 'account_id', 'domain_key', 'account_key'
)
"""


# 完成、重试和死信共用一个原子提交点。只有持有 claim_token 的 worker 才能更新资源，
# 防止旧 worker 在租约过期后覆盖新 worker 的冷却状态。
_FINISH_LUA = r"""
local task_key = KEYS[1]
local inflight_key = KEYS[2]
local accounts_key = KEYS[3]
local dead_key = KEYS[4]
local wakeup_key = KEYS[5]

local task_id = ARGV[1]
local token = ARGV[2]
local outcome = ARGV[3]
local now = tonumber(ARGV[4])
local delay_ms = tonumber(ARGV[5])
local error_text = ARGV[6]
local domain_cooldown_ms = tonumber(ARGV[7])
local account_cooldown_ms = tonumber(ARGV[8])
local increment_attempt = ARGV[9] == '1'
local pending_prefix = ARGV[10]
local lanes_prefix = ARGV[11]
local account_disabled_prefix = ARGV[12]

if redis.call('HGET', task_key, 'state') ~= 'inflight' then
    return 0
end
if redis.call('HGET', task_key, 'claim_token') ~= token then
    return 0
end

local domain_key = redis.call('HGET', task_key, 'domain_key') or ''
local account_key = redis.call('HGET', task_key, 'account_key') or ''
local account_id = redis.call('HGET', task_key, 'account_id') or ''

if domain_key ~= '' and redis.call('GET', domain_key) == token then
    if domain_cooldown_ms > 0 then
        redis.call('PSETEX', domain_key, domain_cooldown_ms, 'cooldown')
    else
        redis.call('DEL', domain_key)
    end
end
if account_key ~= '' and redis.call('GET', account_key) == token then
    -- 账号可能在本任务中刚被判定失效。禁用标记优先于任务收尾，防止账号短暂回池。
    if redis.call('EXISTS', account_disabled_prefix .. account_id) == 1 then
        redis.call('DEL', account_key)
        redis.call('ZREM', accounts_key, account_id)
    elseif account_cooldown_ms > 0 then
        redis.call('PSETEX', account_key, account_cooldown_ms, 'cooldown')
        redis.call('ZADD', accounts_key, now + account_cooldown_ms, account_id)
    else
        redis.call('DEL', account_key)
        redis.call('ZADD', accounts_key, now, account_id)
    end
end

redis.call('ZREM', inflight_key, task_id)
redis.call('HDEL', task_key,
    'worker_id', 'claim_token', 'claimed_at', 'lease_until',
    'domain_key', 'account_key', 'account_id'
)
redis.call('HSET', task_key, 'last_error', error_text, 'updated_at', now)

if increment_attempt then
    redis.call('HINCRBY', task_key, 'attempts', 1)
end

if outcome == 'retry' then
    local queue_name = redis.call('HGET', task_key, 'queue')
    local lane = redis.call('HGET', task_key, 'lane')
    local ready_at = now + delay_ms
    redis.call('HSET', task_key, 'state', 'pending', 'not_before', ready_at)
    redis.call('ZADD', pending_prefix .. queue_name .. ':' .. lane, ready_at, task_id)
    redis.call('SADD', lanes_prefix .. queue_name, lane)
elseif outcome == 'dead' then
    redis.call('HSET', task_key, 'state', 'dead', 'finished_at', now)
    redis.call('ZADD', dead_key, now, task_id)
    redis.call('EXPIRE', task_key, 2592000)
else
    redis.call('HSET', task_key, 'state', 'done', 'finished_at', now)
    redis.call('EXPIRE', task_key, 604800)
end

redis.call('LPUSH', wakeup_key, '1')
redis.call('LTRIM', wakeup_key, 0, 999)
return 1
"""


# 长任务执行期间续签任务、域名门和账号门。续签同样校验 claim_token，已经被回收
# 或重新领取的旧 worker 无权延长新持有者的资源。
_RENEW_LUA = r"""
local task_key = KEYS[1]
local inflight_key = KEYS[2]
local accounts_key = KEYS[3]
local task_id = ARGV[1]
local token = ARGV[2]
local lease_until = tonumber(ARGV[3])
local lease_ms = tonumber(ARGV[4])

if redis.call('HGET', task_key, 'state') ~= 'inflight' then
    return 0
end
if redis.call('HGET', task_key, 'claim_token') ~= token then
    return 0
end

redis.call('HSET', task_key, 'lease_until', lease_until)
redis.call('ZADD', inflight_key, lease_until, task_id)

local domain_key = redis.call('HGET', task_key, 'domain_key') or ''
if domain_key ~= '' and redis.call('GET', domain_key) == token then
    redis.call('PEXPIRE', domain_key, lease_ms)
end

local account_key = redis.call('HGET', task_key, 'account_key') or ''
local account_id = redis.call('HGET', task_key, 'account_id') or ''
if account_key ~= '' and redis.call('GET', account_key) == token then
    redis.call('PEXPIRE', account_key, lease_ms)
    redis.call('ZADD', accounts_key, lease_until, account_id)
end
return 1
"""


# worker 非正常退出后，inflight 租约到期即可重入 pending。资源门使用相同 TTL，
# 因此回收时不需要越权删除可能已经被新任务持有的资源 key。
_RECOVER_LUA = r"""
local inflight_key = KEYS[1]
local wakeup_key = KEYS[2]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local task_prefix = ARGV[3]
local pending_prefix = ARGV[4]
local lanes_prefix = ARGV[5]

local expired = redis.call('ZRANGEBYSCORE', inflight_key, '-inf', now, 'LIMIT', 0, limit)
local recovered = 0
for _, task_id in ipairs(expired) do
    local task_key = task_prefix .. task_id
    if redis.call('HGET', task_key, 'state') == 'inflight' then
        local queue_name = redis.call('HGET', task_key, 'queue')
        local lane = redis.call('HGET', task_key, 'lane')
        redis.call('HSET', task_key,
            'state', 'pending',
            'not_before', now,
            'last_error', 'worker 租约过期，任务已自动恢复'
        )
        redis.call('HDEL', task_key,
            'worker_id', 'claim_token', 'claimed_at', 'lease_until',
            'domain_key', 'account_key', 'account_id'
        )
        redis.call('ZADD', pending_prefix .. queue_name .. ':' .. lane, now, task_id)
        redis.call('SADD', lanes_prefix .. queue_name, lane)
        recovered = recovered + 1
    end
    redis.call('ZREM', inflight_key, task_id)
end
if recovered > 0 then
    redis.call('LPUSH', wakeup_key, '1')
end
return recovered
"""


class ResourceQueueBroker:
    """任务注册、投递和 worker 原子领取的统一入口。"""

    def __init__(self) -> None:
        self.actors: dict[str, TaskActor] = {}
        self._redis: Redis | None = None
        self._enqueue_script: Any = None
        self._claim_script: Any = None
        self._finish_script: Any = None
        self._renew_script: Any = None
        self._recover_script: Any = None

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                health_check_interval=30,
                socket_keepalive=True,
                socket_connect_timeout=5,
                socket_timeout=10,
            )
            self._enqueue_script = self._redis.register_script(_ENQUEUE_LUA)
            self._claim_script = self._redis.register_script(_CLAIM_LUA)
            self._finish_script = self._redis.register_script(_FINISH_LUA)
            self._renew_script = self._redis.register_script(_RENEW_LUA)
            self._recover_script = self._redis.register_script(_RECOVER_LUA)
        return self._redis

    def _ensure_initialized(self) -> None:
        """确保 Redis 客户端和全部 Lua 脚本已经注册。"""

        if self._redis is None:
            _ = self.redis

    def register(self, actor_obj: TaskActor) -> None:
        if actor_obj.actor_name in self.actors:
            raise ValueError(f"任务名称重复: {actor_obj.actor_name}")
        self.actors[actor_obj.actor_name] = actor_obj

    def get_actor(self, actor_name: str) -> TaskActor:
        try:
            return self.actors[actor_name]
        except KeyError as exc:
            raise KeyError(f"未注册任务: {actor_name}") from exc

    def enqueue_actor(
        self,
        actor_obj: TaskActor,
        *,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        delay_ms: int = 0,
        message_id: str | None = None,
    ) -> TaskMessage:
        resources = actor_obj.resolve_resources(args, kwargs)
        task_id = message_id or uuid4().hex
        now_ms = int(time.time() * 1000)
        ready_at = now_ms + max(0, int(delay_ms))
        pending_key = f"{_PENDING_PREFIX}{actor_obj.queue_name}:{resources.lane}"
        task_key = f"{_TASK_PREFIX}{task_id}"
        # 首次入队时先初始化 Redis 和 Lua 脚本。不能直接访问
        # ``_enqueue_script``，否则刚启动的 API 进程会在第一条任务时报 None。
        redis = self.redis
        result = self._enqueue_script(
            keys=[
                task_key,
                pending_key,
                f"{_LANES_PREFIX}{actor_obj.queue_name}",
                _WAKEUP_KEY,
                _SEQUENCE_KEY,
            ],
            args=[
                task_id,
                actor_obj.actor_name,
                actor_obj.queue_name,
                resources.lane,
                resources.domain.value,
                "1" if resources.account else "0",
                resources.node_kind,
                json.dumps(args, ensure_ascii=False, separators=(",", ":")),
                json.dumps(kwargs, ensure_ascii=False, separators=(",", ":")),
                actor_obj.max_retries,
                actor_obj.min_backoff,
                actor_obj.max_backoff,
                ready_at,
                now_ms,
            ],
        )
        if not result and not redis.exists(task_key):
            raise RuntimeError(f"任务入队失败: {actor_obj.actor_name}")
        return TaskMessage(task_id)

    def sync_accounts(self, account_ids: Iterable[int]) -> None:
        """同步启用账号集合；已有账号的冷却分数保持不变。"""

        enabled = {str(int(account_id)) for account_id in account_ids}
        current = set(self.redis.zrange(_ACCOUNTS_KEY, 0, -1))
        pipe = self.redis.pipeline(transaction=True)
        for account_id in enabled - current:
            pipe.zadd(_ACCOUNTS_KEY, {account_id: 0}, nx=True)
        # 管理员重新启用账号后清除禁用标记；正在执行的旧任务随后也可正常完成。
        for account_id in enabled:
            pipe.delete(f"{_ACCOUNT_DISABLED_PREFIX}{account_id}")
        if current - enabled:
            disabled = current - enabled
            pipe.zrem(_ACCOUNTS_KEY, *disabled)
            # 与任务完成脚本配合，堵住“同步移除后，旧任务又把账号加回”的竞态。
            for account_id in disabled:
                pipe.set(f"{_ACCOUNT_DISABLED_PREFIX}{account_id}", "1")
        pipe.execute()

    def claim(self, queue_name: str, *, worker_id: str, lease_ms: int) -> ClaimedTask | None:
        # worker 可能在本进程没有投递过任务时直接领取，因此同样要显式初始化。
        self._ensure_initialized()
        token = secrets.token_urlsafe(24)
        now_ms = int(time.time() * 1000)
        node_scope = settings.NODE_ID.strip() or "local"
        # 未配置 NODE_ID 时，LocalNode 为兼容旧部署会在节点名末尾加 ``-01``。
        node_tail = "" if settings.NODE_ID.strip() else "-01"
        raw = self._claim_script(
            keys=[
                f"{_LANES_PREFIX}{queue_name}",
                _INFLIGHT_KEY,
                _ACCOUNTS_KEY,
                "crawler:breaker:global",
            ],
            args=[
                now_ms,
                lease_ms,
                worker_id,
                token,
                _TASK_PREFIX,
                _PENDING_PREFIX,
                queue_name,
                node_scope,
                node_tail,
                max(1, int(settings.CRAWLER_AUTH_QPH_PER_ACCOUNT)),
            ],
        )
        if not raw:
            return None
        account_id = int(raw[8]) if raw[8] else None
        return ClaimedTask(
            task_id=raw[0],
            actor_name=raw[1],
            queue_name=raw[2],
            args=tuple(json.loads(raw[3])),
            kwargs=dict(json.loads(raw[4])),
            attempts=int(raw[5]),
            claim_token=raw[6],
            domain=TaskDomain(raw[7]),
            account_id=account_id,
            domain_key=raw[9] or None,
            account_key=raw[10] or None,
        )

    def finish(
        self,
        task: ClaimedTask,
        *,
        outcome: str,
        delay_ms: int = 0,
        error: str = "",
        increment_attempt: bool = False,
    ) -> bool:
        self._ensure_initialized()
        if outcome not in {"done", "retry", "dead"}:
            raise ValueError(f"未知任务结果: {outcome}")
        domain_cooldown_ms = {
            TaskDomain.NONE: 0,
            TaskDomain.COM: 1_000,
            TaskDomain.CN: 10_000,
        }[task.domain]
        account_cooldown_ms = (
            max(1, int(float(settings.CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC) * 1000))
            if task.account_id is not None
            else 0
        )
        result = self._finish_script(
            keys=[
                f"{_TASK_PREFIX}{task.task_id}",
                _INFLIGHT_KEY,
                _ACCOUNTS_KEY,
                _DEAD_KEY,
                _WAKEUP_KEY,
            ],
            args=[
                task.task_id,
                task.claim_token,
                outcome,
                int(time.time() * 1000),
                max(0, int(delay_ms)),
                error[:4000],
                domain_cooldown_ms,
                account_cooldown_ms,
                "1" if increment_attempt else "0",
                _PENDING_PREFIX,
                _LANES_PREFIX,
                _ACCOUNT_DISABLED_PREFIX,
            ],
        )
        return bool(result)

    def recover_expired(self, *, limit: int = 200) -> int:
        self._ensure_initialized()
        return int(
            self._recover_script(
                keys=[_INFLIGHT_KEY, _WAKEUP_KEY],
                args=[
                    int(time.time() * 1000),
                    max(1, int(limit)),
                    _TASK_PREFIX,
                    _PENDING_PREFIX,
                    _LANES_PREFIX,
                ],
            )
        )

    def renew(self, task: ClaimedTask, *, lease_ms: int) -> bool:
        """续签运行中的任务；返回 False 表示租约所有权已经丢失。"""

        self._ensure_initialized()
        now_ms = int(time.time() * 1000)
        return bool(
            self._renew_script(
                keys=[
                    f"{_TASK_PREFIX}{task.task_id}",
                    _INFLIGHT_KEY,
                    _ACCOUNTS_KEY,
                ],
                args=[
                    task.task_id,
                    task.claim_token,
                    now_ms + max(1, int(lease_ms)),
                    max(1, int(lease_ms)),
                ],
            )
        )

    def wait_for_work(self, timeout_sec: int = 1) -> None:
        """无可运行任务时阻塞等待；超时用于唤醒检查自然到期的冷却门。"""

        self.redis.brpop(_WAKEUP_KEY, timeout=max(1, int(timeout_sec)))

    def queue_size(self, queue_name: str, *, include_inflight: bool = True) -> int:
        total = 0
        for lane in self.redis.smembers(f"{_LANES_PREFIX}{queue_name}"):
            total += int(self.redis.zcard(f"{_PENDING_PREFIX}{queue_name}:{lane}"))
        if include_inflight:
            # inflight 数量通常很小，逐条检查队列归属可避免再维护易漂移的计数器。
            for task_id in self.redis.zrange(_INFLIGHT_KEY, 0, -1):
                if self.redis.hget(f"{_TASK_PREFIX}{task_id}", "queue") == queue_name:
                    total += 1
        return total

    def retry_delay_ms(self, actor_obj: TaskActor, attempts: int) -> int:
        """指数退避；``attempts`` 是本次失败前已经发生的失败次数。"""

        delay = actor_obj.min_backoff * (2 ** max(0, attempts))
        return min(delay, actor_obj.max_backoff)

    def migrate_legacy_dramatiq(self) -> int:
        """迁移停机前遗留的 Dramatiq ready/DQ 消息。

        部署时应先停止旧 worker。迁移只处理仍在 Redis 列表中的消息，已完成消息和
        死信不动；同一 message_id 已存在于新队列时只清理旧索引，不会重复投递。
        """

        migrated = 0
        now_ms = int(time.time() * 1000)
        for queue_name in QUEUE_ORDER:
            for suffix in ("", ".DQ"):
                list_key = f"dramatiq:{queue_name}{suffix}"
                messages_key = f"{list_key}.msgs"
                for message_id in list(self.redis.lrange(list_key, 0, -1)):
                    raw = self.redis.hget(messages_key, message_id)
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                        actor_obj = self.get_actor(str(payload["actor_name"]))
                        options = payload.get("options") or {}
                        eta = int(options.get("eta") or now_ms)
                        self.enqueue_actor(
                            actor_obj,
                            args=tuple(payload.get("args") or ()),
                            kwargs=dict(payload.get("kwargs") or {}),
                            delay_ms=max(0, eta - now_ms),
                            message_id=str(payload.get("message_id") or message_id),
                        )
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        continue
                    pipe = self.redis.pipeline(transaction=True)
                    pipe.lrem(list_key, 0, message_id)
                    pipe.hdel(messages_key, message_id)
                    pipe.execute()
                    migrated += 1
        return migrated

    def close(self) -> None:
        if self._redis is not None:
            self._redis.close()
            self._redis = None


_broker = ResourceQueueBroker()


def actor(
    *,
    queue_name: str,
    resources: TaskResources | ResourceResolver = NO_RESOURCES,
    max_retries: int = 3,
    min_backoff: int = 5_000,
    max_backoff: int = 60_000,
    throws: tuple[type[BaseException], ...] = (),
) -> Callable[[Callable[P, R]], TaskActor]:
    """注册一个资源队列任务。参数名称沿用旧 actor，减少业务层改动。"""

    def decorator(fn: Callable[P, R]) -> TaskActor:
        actor_obj = TaskActor(
            _broker,
            fn,
            queue_name=queue_name,
            resources=resources,
            max_retries=max_retries,
            min_backoff=min_backoff,
            max_backoff=max_backoff,
            throws=throws,
        )
        _broker.register(actor_obj)
        return actor_obj

    return decorator


def get_broker() -> ResourceQueueBroker:
    return _broker
