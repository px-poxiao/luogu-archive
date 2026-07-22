"""Deduplicate queued problem jobs and seed lifecycle deduplication keys."""
from __future__ import annotations

import argparse
import json

from redis import Redis

from app.core.config import settings

QUEUE_KEYS = ("dramatiq:crawler.low", "dramatiq:crawler.low.DQ")
ACTOR_KINDS = {
    "crawl_problem_list_page": "list",
    "crawl_problem_solution": "solution",
}
DEDUP_TTL_SEC = 30 * 24 * 60 * 60


def _target(payload: dict) -> tuple[str, str] | None:
    kind = ACTOR_KINDS.get(payload.get("actor_name"))
    args = payload.get("args")
    if kind is None or not isinstance(args, list) or not args:
        return None
    value = str(args[0]).upper() if kind == "solution" else str(args[0])
    return kind, value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove duplicates and seed dedup keys; otherwise only report",
    )
    args = parser.parse_args()

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    seen: set[tuple[str, str]] = set()
    kept = removed = malformed = 0
    try:
        for queue_key in QUEUE_KEYS:
            message_ids = redis.lrange(queue_key, 0, -1)
            raw_messages = redis.hmget(f"{queue_key}.msgs", message_ids) if message_ids else []
            pipe = redis.pipeline(transaction=True)
            queue_removed = 0

            for message_id, raw in zip(message_ids, raw_messages, strict=True):
                try:
                    payload = json.loads(raw) if raw else None
                except (TypeError, json.JSONDecodeError):
                    payload = None
                if not isinstance(payload, dict):
                    malformed += 1
                    continue

                target = _target(payload)
                if target is None:
                    continue
                if target in seen:
                    removed += 1
                    queue_removed += 1
                    if args.apply:
                        pipe.lrem(queue_key, 0, message_id)
                        pipe.hdel(f"{queue_key}.msgs", message_id)
                    continue

                seen.add(target)
                kept += 1
                if args.apply:
                    actor_args = list(payload.get("args") or [])
                    token = message_id
                    if len(actor_args) < 3:
                        actor_args.append(message_id)
                        payload["args"] = actor_args
                        pipe.hset(f"{queue_key}.msgs", message_id, json.dumps(payload))
                    elif actor_args[2]:
                        token = str(actor_args[2])
                    kind, value = target
                    pipe.set(
                        f"queue:problem:{kind}:{value}",
                        token,
                        ex=DEDUP_TTL_SEC,
                    )

            if args.apply:
                pipe.execute()
            print(f"{queue_key}: total={len(message_ids)} removed={queue_removed}")
    finally:
        redis.close()

    verb = "removed" if args.apply else "would remove"
    print(f"kept={kept} {verb}={removed} malformed={malformed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
