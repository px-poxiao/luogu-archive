"""Strict-priority Dramatiq worker supervisor.

Dramatiq can listen to multiple queues in one worker, but that does not provide
a hard scheduling guarantee between queue names.  This supervisor enforces the
project policy by running exactly one single-queue Dramatiq child at a time:

    crawler.hi -> crawler.mid -> crawler.low

When a higher-priority queue becomes non-empty, the current child is asked to
shut down gracefully and a child for the higher queue is started.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from redis import Redis

from app.core.config import settings

QUEUES = ("crawler.hi", "crawler.mid", "crawler.low")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


POLL_SEC = max(1, _env_int("PRIORITY_WORKER_POLL_SEC", 2))
GRACE_SEC = max(1, _env_int("PRIORITY_WORKER_GRACE_SEC", 300))
PROCESSES = max(1, _env_int("PRIORITY_WORKER_PROCESSES", 1))
THREADS = max(1, _env_int("PRIORITY_WORKER_THREADS", 4))

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _dramatiq_bin() -> str:
    configured = os.getenv("DRAMATIQ_BIN")
    if configured:
        return configured

    unix = BACKEND_DIR / ".venv" / "bin" / "dramatiq"
    if unix.exists():
        return str(unix)

    win = BACKEND_DIR / ".venv" / "Scripts" / "dramatiq.exe"
    if win.exists():
        return str(win)

    return "dramatiq"


def _log(message: str) -> None:
    print(f"[priority-worker] {message}", flush=True)


def _redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _key_count(redis: Redis, key: str) -> int:
    try:
        key_type = redis.type(key)
        if key_type == "none":
            return 0
        if key_type == "hash":
            return int(redis.hlen(key))
        if key_type == "list":
            return int(redis.llen(key))
        if key_type == "zset":
            return int(redis.zcard(key))
        if key_type == "set":
            return int(redis.scard(key))
        if key_type == "stream":
            return int(redis.xlen(key))
        return 1
    except Exception as exc:  # pragma: no cover - defensive runtime logging
        _log(f"failed to inspect redis key {key}: {exc}")
        return 0


def _queue_pending(redis: Redis, queue: str) -> int:
    base = f"dramatiq:{queue}"
    keys = (
        base,
        f"{base}.msgs",
        f"{base}.DQ",
        f"{base}.dq",
        f"{base}.XQ",
        f"{base}.xq",
    )
    return max(_key_count(redis, key) for key in keys)


def _choose_queue(redis: Redis) -> tuple[str | None, dict[str, int]]:
    counts = {queue: _queue_pending(redis, queue) for queue in QUEUES}
    for queue in QUEUES:
        if counts[queue] > 0:
            return queue, counts
    return None, counts


def _start_child(queue: str) -> subprocess.Popen:
    cmd = [
        _dramatiq_bin(),
        "app.tasks.actors.crawl",
        "--queues",
        queue,
        "--processes",
        str(PROCESSES),
        "--threads",
        str(THREADS),
    ]
    _log(f"start {queue}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=BACKEND_DIR)


def _stop_child(child: subprocess.Popen, *, reason: str) -> None:
    if child.poll() is not None:
        return

    _log(f"stop child pid={child.pid}: {reason}")
    child.terminate()
    deadline = time.monotonic() + GRACE_SEC
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return
        time.sleep(0.5)

    _log(f"kill child pid={child.pid}: graceful stop timed out")
    child.kill()
    child.wait(timeout=5)


def main() -> int:
    redis = _redis()
    child: subprocess.Popen | None = None
    active_queue: str | None = None
    stopping = False

    def request_stop(signum: int, _frame) -> None:  # noqa: ANN001
        nonlocal stopping
        _log(f"received signal {signum}, shutting down")
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    _log(
        "strict priority enabled: "
        f"{' > '.join(QUEUES)}, processes={PROCESSES}, threads={THREADS}"
    )

    try:
        while not stopping:
            desired_queue, counts = _choose_queue(redis)

            if child is not None and child.poll() is not None:
                code = child.returncode
                _log(f"child for {active_queue} exited with code {code}")
                child = None
                active_queue = None
                if code not in (0, None):
                    time.sleep(min(5, POLL_SEC))

            if desired_queue is None:
                if child is not None:
                    _stop_child(child, reason=f"all queues empty {counts}")
                    child = None
                    active_queue = None
                time.sleep(POLL_SEC)
                continue

            if active_queue != desired_queue:
                if child is not None:
                    _stop_child(
                        child,
                        reason=f"switch {active_queue} -> {desired_queue}, counts={counts}",
                    )
                child = _start_child(desired_queue)
                active_queue = desired_queue

            time.sleep(POLL_SEC)
    finally:
        if child is not None:
            _stop_child(child, reason="supervisor shutdown")
        redis.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
