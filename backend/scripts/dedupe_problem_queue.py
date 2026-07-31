"""清理资源队列中重复的题目任务，并重建生命周期去重键。"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from redis import Redis

from app.core.config import settings

ACTOR_KINDS = {
    "crawl_problem_list_page": "list",
    "crawl_problem_solution": "solution",
}
DEDUP_TTL_SEC = 30 * 24 * 60 * 60

_DELETE_PENDING_LUA = r"""
local task_key = KEYS[1]
if redis.call('HGET', task_key, 'state') ~= 'pending' then
    return 0
end
local queue_name = redis.call('HGET', task_key, 'queue')
local lane = redis.call('HGET', task_key, 'lane')
local task_id = redis.call('HGET', task_key, 'task_id')
local pending_key = 'rq:pending:' .. queue_name .. ':' .. lane
redis.call('ZREM', pending_key, task_id)
if redis.call('ZCARD', pending_key) == 0 then
    redis.call('SREM', 'rq:lanes:' .. queue_name, lane)
end
redis.call('DEL', task_key)
return 1
"""


@dataclass(frozen=True, slots=True)
class QueuedProblemTask:
    task_key: str
    task_id: str
    state: str
    sequence: int
    kind: str
    target: str
    dedup_token: str


def _parse_task(task_key: str, payload: dict[str, str]) -> QueuedProblemTask | None:
    kind = ACTOR_KINDS.get(payload.get("actor", ""))
    if kind is None or payload.get("state") not in {"pending", "inflight"}:
        return None
    try:
        actor_args = json.loads(payload.get("args") or "[]")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(actor_args, list) or not actor_args:
        return None

    target = str(actor_args[0]).upper() if kind == "solution" else str(actor_args[0])
    task_id = payload.get("task_id") or task_key.removeprefix("rq:task:")
    token = str(actor_args[2]) if len(actor_args) > 2 and actor_args[2] else task_id
    return QueuedProblemTask(
        task_key=task_key,
        task_id=task_id,
        state=payload["state"],
        sequence=int(payload.get("sequence") or 0),
        kind=kind,
        target=target,
        dedup_token=token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际删除重复任务并写入去重键；不带时只统计",
    )
    args = parser.parse_args()

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    delete_pending = redis.register_script(_DELETE_PENDING_LUA)
    tasks: list[QueuedProblemTask] = []
    try:
        for task_key in redis.scan_iter(match="rq:task:*", count=1000):
            parsed = _parse_task(task_key, redis.hgetall(task_key))
            if parsed is not None:
                tasks.append(parsed)

        # 正在执行的任务必须优先保留；其余按原始入队序号保留最早一条。
        tasks.sort(key=lambda item: (item.state != "inflight", item.sequence))
        kept: dict[tuple[str, str], QueuedProblemTask] = {}
        duplicates: list[QueuedProblemTask] = []
        for task in tasks:
            identity = (task.kind, task.target)
            if identity in kept:
                duplicates.append(task)
            else:
                kept[identity] = task

        removed = 0
        if args.apply:
            pipe = redis.pipeline(transaction=True)
            for task in kept.values():
                pipe.set(
                    f"queue:problem:{task.kind}:{task.target}",
                    task.dedup_token,
                    ex=DEDUP_TTL_SEC,
                )
            pipe.execute()
            for task in duplicates:
                if task.state == "pending":
                    removed += int(delete_pending(keys=[task.task_key]))

        print(
            f"题目任务={len(tasks)}，保留={len(kept)}，重复={len(duplicates)}"
        )
        if args.apply:
            print(f"已删除待执行重复任务={removed}")
        else:
            print("当前为只读预览；确认后可追加 --apply")
    finally:
        redis.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
