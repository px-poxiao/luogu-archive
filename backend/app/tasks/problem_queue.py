"""题目爬取任务的全队列去重。"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.core.locks import DistributedLock
from app.core.redis_client import get_redis
from app.tasks.broker import get_broker

# 覆盖长延迟的全量刷新批次和 worker 临时离线时间。
_DEDUP_TTL_SEC = 30 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ProblemEnqueueResult:
    message_id: str
    enqueued: bool


def problem_queue_key(kind: str, target: str | int) -> str:
    return f"queue:problem:{kind}:{target}"


async def _enqueue(actor_name: str, key: str, args: tuple, *, delay_ms: int = 0) -> ProblemEnqueueResult:
    # scheduler 和 API 进程通常不会主动导入任务模块，这里确保定义已经注册。
    from app.tasks.actors import crawl as _crawl_actors  # noqa: F401

    broker = get_broker()
    actor = broker.get_actor(actor_name)
    # 去重 token 同时作为任务 ID 和任务参数。这样释放锁时能校验所有权，
    # API 重试也不会误删另一条同目标任务的去重键。
    token = uuid4().hex

    redis = get_redis()
    existing = await redis.get(key)
    if existing:
        return ProblemEnqueueResult(existing, False)
    if not await redis.set(key, token, nx=True, ex=_DEDUP_TTL_SEC):
        return ProblemEnqueueResult(str(await redis.get(key) or token), False)

    try:
        actor.send_with_options(
            args=(*args, token),
            delay=max(0, int(delay_ms)),
            message_id=token,
        )
    except BaseException:
        await DistributedLock(redis).release(key, token)
        raise
    return ProblemEnqueueResult(token, True)


async def enqueue_problem_list_page(
    page: int,
    trigger: str = "scheduled",
    *,
    delay_ms: int = 0,
) -> ProblemEnqueueResult:
    return await _enqueue(
        "crawl_problem_list_page",
        problem_queue_key("list", page),
        (page, trigger),
        delay_ms=delay_ms,
    )


async def enqueue_problem_solution(
    pid: str,
    trigger: str = "scheduled",
    *,
    delay_ms: int = 0,
) -> ProblemEnqueueResult:
    normalized = pid.upper()
    return await _enqueue(
        "crawl_problem_solution",
        problem_queue_key("solution", normalized),
        (normalized, trigger),
        delay_ms=delay_ms,
    )


async def release_problem_job(kind: str, target: str | int, token: str | None) -> None:
    if not token:
        return
    await DistributedLock(get_redis()).release(problem_queue_key(kind, target), token)
