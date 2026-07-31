"""在同步队列任务里运行 async 代码的桥接。

资源 worker 是同步执行器，我们的爬虫和数据库层是 async。方案：
- 每个 worker 进程启动时创建一个 event loop（驻留）
- actor 被调度时，把 async 协程 `run_coroutine_threadsafe` 到那个 loop
- 等结果返回

比起每次 `asyncio.run()` 好处是：不反复关闭 httpx client、MySQL 连接池等。
"""
from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Coroutine
from typing import TypeVar

from app.tasks.runtime import current_sync_reservation, run_with_reservation

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """懒初始化后台 event loop 线程。"""
    global _loop, _thread
    with _lock:
        if _loop is not None and _loop.is_running():
            return _loop

        _loop = asyncio.new_event_loop()

        def _runner() -> None:
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _thread = threading.Thread(target=_runner, name="async-bridge", daemon=True)
        _thread.start()
        atexit.register(_shutdown)
        return _loop


def _shutdown() -> None:
    """进程退出时关停 loop。"""
    global _loop, _thread
    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_loop.stop)
    if _thread is not None:
        _thread.join(timeout=5)


def run_async(coro: Coroutine[None, None, T], *, timeout: float | None = None) -> T:
    """在后台 loop 上执行协程，并等待它真实结束。

    HTTP 层已有独立超时。这里不能设置较短的总超时：
    ``Future.result`` 超时不会取消后台协程，队列重试后会与原任务重叠执行。
    """
    loop = _ensure_loop()
    # 任务领取时预留的域名门和账号门需要跨越同步 worker 与异步桥线程。
    reservation = current_sync_reservation()
    fut = asyncio.run_coroutine_threadsafe(
        run_with_reservation(coro, reservation),
        loop,
    )
    return fut.result(timeout=timeout)
