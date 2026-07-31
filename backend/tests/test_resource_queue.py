"""资源队列的原子性、优先级和资源依赖回归测试。"""
from __future__ import annotations

import json
import os
import time

import fakeredis

# Settings 在导入时读取必填配置；测试不连接这些外部服务，但仍需提供合法占位值。
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("ADMIN_TOTP_ENCRYPTION_KEY", "test")
os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("NODE_ID", "queue-test")
os.environ.setdefault("CRAWLER_AUTH_QPH_PER_ACCOUNT", "1")
os.environ.setdefault("CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC", "0.001")

from app.tasks import broker as queue_module  # noqa: E402


def _broker(server: fakeredis.FakeServer) -> queue_module.ResourceQueueBroker:
    broker = queue_module.ResourceQueueBroker()
    broker._redis = fakeredis.FakeRedis(server=server, decode_responses=True)
    broker._enqueue_script = broker._redis.register_script(queue_module._ENQUEUE_LUA)
    broker._claim_script = broker._redis.register_script(queue_module._CLAIM_LUA)
    broker._finish_script = broker._redis.register_script(queue_module._FINISH_LUA)
    broker._renew_script = broker._redis.register_script(queue_module._RENEW_LUA)
    broker._recover_script = broker._redis.register_script(queue_module._RECOVER_LUA)
    return broker


def _register(
    broker: queue_module.ResourceQueueBroker,
    name: str,
    queue_name: str,
    resources: queue_module.TaskResources,
) -> queue_module.TaskActor:
    def task() -> None:
        return None

    task.__name__ = name
    actor = queue_module.TaskActor(
        broker,
        task,
        queue_name=queue_name,
        resources=resources,
        max_retries=2,
        min_backoff=10,
        max_backoff=100,
        throws=(),
    )
    broker.register(actor)
    return actor


def test_strict_priority_and_blocked_dependency_fallback() -> None:
    server = fakeredis.FakeServer()
    broker = _broker(server)
    high_cpu = _register(
        broker,
        "high_cpu",
        queue_module.QUEUE_CRAWL_HI,
        queue_module.NO_RESOURCES,
    )
    high_com = _register(
        broker,
        "high_com",
        queue_module.QUEUE_CRAWL_HI,
        queue_module.ANON_COM,
    )
    mid_cpu = _register(
        broker,
        "mid_cpu",
        queue_module.QUEUE_CRAWL_MID,
        queue_module.NO_RESOURCES,
    )

    mid_cpu.send()
    high_cpu.send()
    claimed = broker.claim(queue_module.QUEUE_CRAWL_HI, worker_id="w1", lease_ms=1000)
    assert claimed is not None and claimed.actor_name == "high_cpu"
    assert broker.finish(claimed, outcome="done")

    # 高优先级网络任务在域名冷却时留在原位，中优先级纯计算任务仍可执行。
    high_com.send()
    broker.redis.set(
        "rl:crawler_node:queue-test:domain:luogu.com",
        "cooldown",
        px=1000,
    )
    assert broker.claim(queue_module.QUEUE_CRAWL_HI, worker_id="w1", lease_ms=1000) is None
    claimed = broker.claim(queue_module.QUEUE_CRAWL_MID, worker_id="w1", lease_ms=1000)
    assert claimed is not None and claimed.actor_name == "mid_cpu"
    assert broker.finish(claimed, outcome="done")
    assert broker.queue_size(queue_module.QUEUE_CRAWL_HI) == 1


def test_two_workers_cannot_claim_the_same_task() -> None:
    server = fakeredis.FakeServer()
    first_broker = _broker(server)
    second_broker = _broker(server)
    actor = _register(
        first_broker,
        "atomic_task",
        queue_module.QUEUE_CRAWL_HI,
        queue_module.NO_RESOURCES,
    )
    actor.send()

    first = first_broker.claim(
        queue_module.QUEUE_CRAWL_HI,
        worker_id="w1",
        lease_ms=1000,
    )
    second = second_broker.claim(
        queue_module.QUEUE_CRAWL_HI,
        worker_id="w2",
        lease_ms=1000,
    )
    assert first is not None
    assert second is None


def test_account_selection_and_hourly_quota() -> None:
    server = fakeredis.FakeServer()
    broker = _broker(server)
    actor = _register(
        broker,
        "authenticated_task",
        queue_module.QUEUE_CRAWL_MID,
        queue_module.AUTH_COM,
    )
    broker.sync_accounts([10, 20])

    actor.send()
    first = broker.claim(queue_module.QUEUE_CRAWL_MID, worker_id="w1", lease_ms=1000)
    assert first is not None and first.account_id == 10
    assert broker.finish(first, outcome="done")

    time.sleep(0.01)
    broker.redis.delete("rl:crawler_node:queue-test:domain:luogu.com")
    actor.send()
    second = broker.claim(queue_module.QUEUE_CRAWL_MID, worker_id="w1", lease_ms=1000)
    assert second is not None and second.account_id == 20
    assert broker.finish(second, outcome="done")

    time.sleep(0.01)
    broker.redis.delete("rl:crawler_node:queue-test:domain:luogu.com")
    actor.send()
    assert broker.claim(queue_module.QUEUE_CRAWL_MID, worker_id="w1", lease_ms=1000) is None


def test_disabled_account_is_not_readded_when_task_finishes() -> None:
    server = fakeredis.FakeServer()
    broker = _broker(server)
    actor = _register(
        broker,
        "account_disable_race",
        queue_module.QUEUE_CRAWL_MID,
        queue_module.AUTH_COM,
    )
    broker.sync_accounts([30])

    actor.send()
    claimed = broker.claim(
        queue_module.QUEUE_CRAWL_MID,
        worker_id="w1",
        lease_ms=1000,
    )
    assert claimed is not None and claimed.account_id == 30

    # 模拟任务仍在运行时，账号被后台或管理员禁用。任务收尾不得把它重新加入账号池。
    broker.sync_accounts([])
    assert broker.finish(claimed, outcome="done")
    assert broker.redis.zscore("rq:accounts:available", "30") is None

    # 管理员重新启用后，同步会清除禁用标记并恢复账号。
    broker.sync_accounts([30])
    assert broker.redis.exists(queue_module.account_disabled_key(30)) == 0
    assert broker.redis.zscore("rq:accounts:available", "30") is not None


def test_retry_delay_renew_and_expired_recovery() -> None:
    server = fakeredis.FakeServer()
    broker = _broker(server)
    other = _broker(server)
    actor = _register(
        broker,
        "recoverable_task",
        queue_module.QUEUE_CRAWL_HI,
        queue_module.NO_RESOURCES,
    )

    message = actor.send()
    claimed = broker.claim(queue_module.QUEUE_CRAWL_HI, worker_id="w1", lease_ms=1000)
    assert claimed is not None
    assert broker.finish(
        claimed,
        outcome="retry",
        delay_ms=30,
        increment_attempt=True,
    )
    assert broker.claim(queue_module.QUEUE_CRAWL_HI, worker_id="w1", lease_ms=1000) is None
    time.sleep(0.04)
    claimed = broker.claim(queue_module.QUEUE_CRAWL_HI, worker_id="w1", lease_ms=40)
    assert claimed is not None
    assert claimed.task_id == message.message_id
    assert claimed.attempts == 1

    assert broker.renew(claimed, lease_ms=100)
    time.sleep(0.05)
    assert other.recover_expired() == 0
    time.sleep(0.07)
    assert other.recover_expired() == 1
    reclaimed = other.claim(queue_module.QUEUE_CRAWL_HI, worker_id="w2", lease_ms=1000)
    assert reclaimed is not None and reclaimed.task_id == message.message_id


def test_legacy_dramatiq_message_is_migrated_once() -> None:
    server = fakeredis.FakeServer()
    broker = _broker(server)
    _register(
        broker,
        "legacy_task",
        queue_module.QUEUE_CRAWL_MID,
        queue_module.NO_RESOURCES,
    )
    message_id = "legacy-message-id"
    queue_key = "dramatiq:crawler.mid"
    broker.redis.rpush(queue_key, message_id)
    broker.redis.hset(
        f"{queue_key}.msgs",
        message_id,
        json.dumps(
            {
                "queue_name": queue_module.QUEUE_CRAWL_MID,
                "actor_name": "legacy_task",
                "args": [],
                "kwargs": {},
                "options": {},
                "message_id": message_id,
            }
        ),
    )

    assert broker.migrate_legacy_dramatiq() == 1
    assert broker.migrate_legacy_dramatiq() == 0
    assert broker.redis.llen(queue_key) == 0
    claimed = broker.claim(
        queue_module.QUEUE_CRAWL_MID,
        worker_id="w1",
        lease_ms=1000,
    )
    assert claimed is not None and claimed.task_id == message_id
