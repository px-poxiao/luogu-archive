"""资源感知型严格优先级 worker。

领取顺序固定为 ``crawler.hi -> crawler.mid -> crawler.low``。高优先级队列中
暂时不满足域名或账号冷却条件的任务仍留在原位，worker 会继续寻找下一优先级中
可以立即运行的任务。领取、资源预留和状态迁移全部由 Redis Lua 原子完成。
"""
from __future__ import annotations

import os
import signal
import socket
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.config import settings
from app.core.db import db_session
from app.core.exceptions import CrawlerCooldownDeferred
from app.core.logging import get_logger, setup_logging
from app.models.admin import CrawlerAccount

# 导入模块即完成 actor 注册。必须在迁移旧消息和开始领取之前执行。
from app.tasks.actors import contest as _contest_actors  # noqa: F401
from app.tasks.actors import crawl as _crawl_actors  # noqa: F401
from app.tasks.asyncio_runner import run_async
from app.tasks.broker import QUEUE_ORDER, ClaimedTask, ResourceQueueBroker, get_broker
from app.tasks.runtime import TaskReservation, activate_sync_reservation

setup_logging()
log = get_logger(__name__)


# 任务执行时由心跳持续续租，短租约既能覆盖 Redis 短暂抖动，也能在进程崩溃后较快恢复。
LEASE_SEC = max(30.0, float(settings.RESOURCE_WORKER_LEASE_SEC))
ACCOUNT_SYNC_SEC = max(5.0, float(settings.RESOURCE_WORKER_ACCOUNT_SYNC_SEC))
RECOVER_SEC = max(2.0, float(settings.RESOURCE_WORKER_RECOVER_SEC))
IDLE_WAIT_SEC = max(0.2, float(settings.RESOURCE_WORKER_IDLE_WAIT_SEC))


async def _enabled_account_ids() -> list[int]:
    """从中心数据库读取当前启用的爬取账号。"""

    async with db_session() as session:
        result = await session.execute(
            select(CrawlerAccount.id)
            .where(CrawlerAccount.enabled.is_(True))
            .order_by(CrawlerAccount.id.asc())
        )
        return [int(account_id) for account_id in result.scalars().all()]


@dataclass(slots=True)
class _LeaseHeartbeat:
    """后台续签正在运行的任务，避免长任务被其他 worker 回收。"""

    broker: ResourceQueueBroker
    task: ClaimedTask
    lease_ms: int
    _stop: threading.Event = field(init=False, repr=False)
    _lost: threading.Event = field(init=False, repr=False)
    _thread: threading.Thread = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"queue-heartbeat-{self.task.task_id[:8]}",
            daemon=True,
        )

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        interval_sec = max(5.0, self.lease_ms / 3000.0)
        while not self._stop.wait(interval_sec):
            try:
                if not self.broker.renew(self.task, lease_ms=self.lease_ms):
                    self._lost.set()
                    log.error(
                        "queue.lease_lost",
                        task_id=self.task.task_id,
                        actor=self.task.actor_name,
                    )
                    return
            except Exception as exc:
                # 单次 Redis 抖动不立即判定丢租；只要下次在租约到期前成功即可。
                log.warning(
                    "queue.lease_renew_failed",
                    task_id=self.task.task_id,
                    error=str(exc),
                )


class ResourceWorker:
    """单进程执行器；多台机器运行同一实现即可横向扩容。"""

    def __init__(self, broker: ResourceQueueBroker) -> None:
        self.broker = broker
        node_id = settings.NODE_ID.strip() or "local"
        self.worker_id = f"{node_id}:{socket.gethostname()}:{os.getpid()}"
        self.lease_ms = int(LEASE_SEC * 1000)
        self.stopping = False
        self._legacy_migration_pending = True
        self._next_account_sync = 0.0
        self._next_recover = 0.0

    def request_stop(self, signum: int, _frame) -> None:  # noqa: ANN001
        log.info("queue.worker_stop_requested", signal=signum)
        self.stopping = True

    def _sync_accounts_if_due(self) -> None:
        now = time.monotonic()
        if now < self._next_account_sync:
            return
        self._next_account_sync = now + ACCOUNT_SYNC_SEC
        try:
            account_ids = run_async(_enabled_account_ids())
            self.broker.sync_accounts(account_ids)
            log.debug("queue.accounts_synced", count=len(account_ids))
        except Exception as exc:
            # 已同步到 Redis 的账号仍然可用，数据库短暂不可达不会清空账号池。
            log.error("queue.accounts_sync_failed", error=str(exc))

    def _recover_if_due(self) -> None:
        now = time.monotonic()
        if now < self._next_recover:
            return
        self._next_recover = now + RECOVER_SEC
        try:
            recovered = self.broker.recover_expired()
            if recovered:
                log.warning("queue.expired_tasks_recovered", count=recovered)
        except Exception as exc:
            log.error("queue.recover_failed", error=str(exc))

    def _migrate_legacy_if_needed(self) -> None:
        """启动后迁移旧消息；Redis 暂时不可达时留在循环中稍后重试。"""

        if not self._legacy_migration_pending:
            return
        migrated = self.broker.migrate_legacy_dramatiq()
        self._legacy_migration_pending = False
        log.info("queue.legacy_migration_finished", migrated=migrated)

    def _claim_next(self) -> ClaimedTask | None:
        """严格按优先级尝试；不可运行不等于空队列，因此不能删除任务。"""

        for queue_name in QUEUE_ORDER:
            task = self.broker.claim(
                queue_name,
                worker_id=self.worker_id,
                lease_ms=self.lease_ms,
            )
            if task is not None:
                return task
        return None

    def _finish_failure(self, task: ClaimedTask, exc: Exception) -> None:
        actor_obj = self.broker.get_actor(task.actor_name)
        error = f"{type(exc).__name__}: {exc}"

        if isinstance(exc, CrawlerCooldownDeferred):
            # 冷却竞态不算业务失败，不消耗重试次数。
            self.broker.finish(
                task,
                outcome="retry",
                delay_ms=max(1, exc.retry_after_ms + 100),
                error=error,
            )
            log.info(
                "queue.task_cooldown_deferred",
                task_id=task.task_id,
                actor=task.actor_name,
                delay_ms=exc.retry_after_ms + 100,
            )
            return

        if actor_obj.throws and isinstance(exc, actor_obj.throws):
            self.broker.finish(
                task,
                outcome="dead",
                error=error,
                increment_attempt=True,
            )
            log.warning(
                "queue.task_discarded",
                task_id=task.task_id,
                actor=task.actor_name,
                error=error,
            )
            return

        if task.attempts < actor_obj.max_retries:
            delay_ms = self.broker.retry_delay_ms(actor_obj, task.attempts)
            self.broker.finish(
                task,
                outcome="retry",
                delay_ms=delay_ms,
                error=error,
                increment_attempt=True,
            )
            log.warning(
                "queue.task_retry",
                task_id=task.task_id,
                actor=task.actor_name,
                attempt=task.attempts + 1,
                delay_ms=delay_ms,
                error=error,
            )
            return

        self.broker.finish(
            task,
            outcome="dead",
            error=error,
            increment_attempt=True,
        )
        log.error(
            "queue.task_dead",
            task_id=task.task_id,
            actor=task.actor_name,
            attempts=task.attempts + 1,
            error=error,
        )

    def _execute(self, task: ClaimedTask) -> None:
        try:
            actor_obj = self.broker.get_actor(task.actor_name)
        except KeyError as exc:
            self.broker.finish(task, outcome="dead", error=str(exc))
            log.error("queue.actor_missing", task_id=task.task_id, actor=task.actor_name)
            return

        reservation = TaskReservation(
            task_id=task.task_id,
            claim_token=task.claim_token,
            domain_key=task.domain_key,
            account_key=task.account_key,
            account_id=task.account_id,
        )
        heartbeat = _LeaseHeartbeat(self.broker, task, self.lease_ms)
        heartbeat.start()
        started = time.monotonic()
        log.info(
            "queue.task_started",
            task_id=task.task_id,
            actor=task.actor_name,
            queue=task.queue_name,
            account_id=task.account_id,
        )
        failure: Exception | None = None
        try:
            with activate_sync_reservation(reservation):
                actor_obj(*task.args, **task.kwargs)
        except Exception as exc:
            failure = exc
            log.exception(
                "queue.task_failed",
                task_id=task.task_id,
                actor=task.actor_name,
                error=str(exc),
            )
        finally:
            # 先停止续租再提交最终状态，避免心跳恰好在完成后把任务误报为丢租。
            heartbeat.stop()

        if heartbeat.lost:
            log.error(
                "queue.task_completed_after_lease_lost",
                task_id=task.task_id,
                actor=task.actor_name,
            )

        if failure is not None:
            self._finish_failure(task, failure)
        else:
            if self.broker.finish(task, outcome="done"):
                log.info(
                    "queue.task_finished",
                    task_id=task.task_id,
                    actor=task.actor_name,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            else:
                log.error(
                    "queue.task_finish_rejected",
                    task_id=task.task_id,
                    actor=task.actor_name,
                )

    def run(self) -> int:
        log.info(
            "queue.worker_started",
            worker_id=self.worker_id,
            priority_order=list(QUEUE_ORDER),
        )

        while not self.stopping:
            try:
                self._migrate_legacy_if_needed()
                self._sync_accounts_if_due()
                self._recover_if_due()
                task = self._claim_next()
                if task is None:
                    self.broker.wait_for_work(timeout_sec=max(1, int(IDLE_WAIT_SEC)))
                    continue
                self._execute(task)
            except Exception as exc:
                # Redis 或数据库临时不可达时保留进程，避免由启动脚本高速重启刷日志。
                log.exception("queue.worker_loop_failed", error=str(exc))
                time.sleep(min(5.0, IDLE_WAIT_SEC))

        log.info("queue.worker_stopped", worker_id=self.worker_id)
        return 0


def main() -> int:
    worker = ResourceWorker(get_broker())
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    return worker.run()


if __name__ == "__main__":
    raise SystemExit(main())
