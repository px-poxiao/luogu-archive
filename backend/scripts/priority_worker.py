"""严格优先级 Dramatiq worker 监督进程。

Dramatiq 可以让一个 worker 同时监听多条队列，但这不能保证队列之间的严格调度顺序。
这里一次只运行一个单队列 Dramatiq 子进程，并按下面的顺序选择队列：

    crawler.hi -> crawler.mid -> crawler.low

注意：Dramatiq 的延迟队列 ``<queue>.DQ`` 里可能有未来才重试的消息。未来消息不能
阻塞低优先级队列，否则一个高优先级重试任务就会让普通队列长期饿死。
"""
from __future__ import annotations

import json
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
# 严格优先级和“任务完成后冷却”都要求同一时刻只执行一个 actor。
# 不允许环境变量误把并发重新调高；横向扩容仍由 Redis 限流门兜底。
PROCESSES = 1
THREADS = 1
DELAY_SCAN_LIMIT = max(1, _env_int("PRIORITY_WORKER_DELAY_SCAN_LIMIT", 500))

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
    except Exception as exc:  # pragma: no cover - 运行时兜底日志
        _log(f"failed to inspect redis key {key}: {exc}")
        return 0


def _message_eta_ms(raw: str | bytes | None) -> int | None:
    """从 Dramatiq 消息体里读取 eta；没有 eta 的延迟消息按已到期处理。"""
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        options = payload.get("options") if isinstance(payload, dict) else None
        eta = options.get("eta") if isinstance(options, dict) else None
        return int(eta) if eta is not None else None
    except Exception:
        return None


def _due_delayed_count(redis: Redis, queue: str, now_ms: int) -> int:
    """统计已经到期的延迟消息，避免未来重试消息长期压住普通队列。"""
    delayed_queue = f"dramatiq:{queue}.DQ"
    messages_key = f"{delayed_queue}.msgs"
    try:
        if redis.type(delayed_queue) != "list":
            return 0

        message_ids = redis.lrange(delayed_queue, 0, DELAY_SCAN_LIMIT - 1)
        if not message_ids:
            return 0

        raw_messages = redis.hmget(messages_key, message_ids)
        due = 0
        for raw in raw_messages:
            eta = _message_eta_ms(raw)
            if eta is None or eta <= now_ms:
                due += 1
        return due
    except Exception as exc:  # pragma: no cover - 运行时兜底日志
        _log(f"failed to inspect delayed queue {queue}: {exc}")
        return 0


def _queue_pending(redis: Redis, queue: str) -> int:
    # RedisBroker 结构：
    #   dramatiq:<queue>      ready message id list
    #   dramatiq:<queue>.msgs message body hash
    #   dramatiq:<queue>.DQ   delayed message id list
    # 不能把 .msgs / .DQ / .XQ 总量当作 pending，否则未来重试和死信会阻塞低优先级。
    now_ms = int(time.time() * 1000)
    ready = _key_count(redis, f"dramatiq:{queue}")
    due_delayed = _due_delayed_count(redis, queue, now_ms)
    return ready + due_delayed


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
        # 比赛使用独立队列，旧 worker 不会误取尚未注册的新 actor。
        "app.tasks.actors.contest",
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
