"""Queue-wide deduplication for problem crawler jobs."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.locks import DistributedLock
from app.core.redis_client import get_redis
from app.tasks.broker import get_broker

# Covers long delayed full-refresh batches and temporary worker outages.
_DEDUP_TTL_SEC = 30 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ProblemEnqueueResult:
    message_id: str
    enqueued: bool


def problem_queue_key(kind: str, target: str | int) -> str:
    return f"queue:problem:{kind}:{target}"


async def _enqueue(actor_name: str, key: str, args: tuple, *, delay_ms: int = 0) -> ProblemEnqueueResult:
    # Scheduler and API processes do not otherwise import actor modules.
    from app.tasks.actors import crawl as _crawl_actors  # noqa: F401

    broker = get_broker()
    actor = broker.get_actor(actor_name)
    message = actor.message(*args, None)
    token = message.message_id
    message = message.copy(args=(*args, token))

    redis = get_redis()
    existing = await redis.get(key)
    if existing:
        return ProblemEnqueueResult(existing, False)
    if not await redis.set(key, token, nx=True, ex=_DEDUP_TTL_SEC):
        return ProblemEnqueueResult(str(await redis.get(key) or token), False)

    try:
        if delay_ms > 0:
            broker.enqueue(message, delay=int(delay_ms))
        else:
            broker.enqueue(message)
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
