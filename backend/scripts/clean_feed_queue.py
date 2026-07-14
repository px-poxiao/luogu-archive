"""Inspect or remove queued feed crawl messages without touching other actors."""
from __future__ import annotations

import argparse
import json

from redis import Redis

from app.core.config import settings


QUEUE_KEYS = (
    "dramatiq:crawler.mid",
    "dramatiq:crawler.mid.DQ",
)
FEED_ACTORS = {"crawl_user_feeds"}


def _feed_message_ids(redis: Redis, queue_key: str) -> list[str]:
    message_ids = redis.lrange(queue_key, 0, -1)
    if not message_ids:
        return []

    raw_messages = redis.hmget(f"{queue_key}.msgs", message_ids)
    matched: list[str] = []
    for message_id, raw in zip(message_ids, raw_messages, strict=True):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("actor_name") in FEED_ACTORS:
            matched.append(message_id)
    return matched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete the matched messages; without this flag the command is read-only",
    )
    args = parser.parse_args()

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    total = 0
    try:
        for queue_key in QUEUE_KEYS:
            matched = _feed_message_ids(redis, queue_key)
            total += len(matched)
            print(f"{queue_key}: matched={len(matched)}")
            if args.apply and matched:
                pipe = redis.pipeline(transaction=True)
                for message_id in matched:
                    pipe.lrem(queue_key, 0, message_id)
                    pipe.hdel(f"{queue_key}.msgs", message_id)
                pipe.execute()

        dedup_keys = list(redis.scan_iter(match="scheduler:feed:queued:*", count=1000))
        print(f"scheduler feed dedup keys: matched={len(dedup_keys)}")
        if args.apply and dedup_keys:
            redis.delete(*dedup_keys)
    finally:
        redis.close()

    action = "removed" if args.apply else "would remove"
    print(f"{action} {total} queued feed messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
