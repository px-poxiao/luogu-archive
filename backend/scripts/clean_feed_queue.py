"""查看或删除资源队列中的犇犇任务，不影响其他任务。"""
from __future__ import annotations

import argparse

from redis import Redis

from app.core.config import settings

FEED_ACTORS = {"crawl_user_feeds"}

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际删除匹配任务；不带该参数时只统计",
    )
    args = parser.parse_args()

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    delete_pending = redis.register_script(_DELETE_PENDING_LUA)
    matched: list[str] = []
    removed = 0
    try:
        for task_key in redis.scan_iter(match="rq:task:*", count=1000):
            actor_name, state = redis.hmget(task_key, "actor", "state")
            if actor_name in FEED_ACTORS and state == "pending":
                matched.append(task_key)

        print(f"匹配到待执行犇犇任务：{len(matched)}")
        if args.apply:
            for task_key in matched:
                removed += int(delete_pending(keys=[task_key]))

            dedup_keys = list(
                redis.scan_iter(match="scheduler:feed:queued:*", count=1000)
            )
            if dedup_keys:
                redis.delete(*dedup_keys)
            print(f"已清理调度去重键：{len(dedup_keys)}")
    finally:
        redis.close()

    if args.apply:
        print(f"已删除犇犇任务：{removed}")
    else:
        print("当前为只读预览；确认后可追加 --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
