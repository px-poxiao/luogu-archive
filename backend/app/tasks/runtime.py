"""当前 worker 任务的资源预留上下文。

资源由队列在领取任务时预留。业务代码仍会经过原有 HTTP 和账号上下文，因此这里
把预留信息传入异步桥，让底层识别“当前任务已经持有该门”，避免二次抢锁。
"""
from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskReservation:
    task_id: str
    claim_token: str
    domain_key: str | None = None
    account_key: str | None = None
    account_id: int | None = None

    @property
    def resource_keys(self) -> frozenset[str]:
        return frozenset(
            key for key in (self.domain_key, self.account_key) if key
        )


# worker 的同步执行线程和 async-bridge 线程不同：线程本地变量用于捕获同步侧任务，
# ContextVar 用于异步协程树，避免后续代码意外创建并行协程时相互污染。
_sync_state = threading.local()
_async_reservation: contextvars.ContextVar[TaskReservation | None] = (
    contextvars.ContextVar("task_reservation", default=None)
)


@contextmanager
def activate_sync_reservation(reservation: TaskReservation) -> Iterator[None]:
    previous = getattr(_sync_state, "reservation", None)
    _sync_state.reservation = reservation
    try:
        yield
    finally:
        _sync_state.reservation = previous


def current_sync_reservation() -> TaskReservation | None:
    return getattr(_sync_state, "reservation", None)


def current_async_reservation() -> TaskReservation | None:
    return _async_reservation.get()


async def run_with_reservation(coro, reservation: TaskReservation | None):  # noqa: ANN001
    """在异步桥线程中恢复领取任务时保存的资源上下文。"""

    token = _async_reservation.set(reservation)
    try:
        return await coro
    finally:
        _async_reservation.reset(token)
