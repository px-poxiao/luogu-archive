"""Dramatiq broker 单例 + 全局中间件。

所有 actor 模块 import 这里，保证 broker 只初始化一次。
"""
from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AgeLimit, Callbacks, Retries, ShutdownNotifications, TimeLimit

from app.core.config import settings
from app.core.logging import setup_logging

# 首次 import 时初始化 logging
setup_logging()

_broker = RedisBroker(url=settings.REDIS_URL)
# Dramatiq 默认加载的中间件已足够：AgeLimit / TimeLimit / Retries / Shutdown / Callbacks
# 不加 Prometheus（后续再接）
for mw in (AgeLimit(), TimeLimit(), ShutdownNotifications(), Callbacks(), Retries()):
    # 这些默认已在 broker.middleware 里；重复 add 是无副作用 no-op
    if not any(isinstance(existing, type(mw)) for existing in _broker.middleware):
        _broker.add_middleware(mw)

dramatiq.set_broker(_broker)


def get_broker() -> RedisBroker:
    return _broker


# 队列常量
QUEUE_CRAWL_HI = "crawler.hi"
QUEUE_CRAWL_MID = "crawler.mid"
QUEUE_CRAWL_LOW = "crawler.low"
QUEUE_CRAWL_FEED = "crawler.feed"
