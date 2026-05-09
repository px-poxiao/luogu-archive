"""结构化日志 —— 贯穿 Web / 爬虫 / 任务队列的统一日志入口。

用 structlog 而非标准 logging 的原因：
1. 原生支持键值对结构化日志，方便接入 ELK/Grafana Loki
2. 开发期可输出彩色易读格式，生产期输出 JSON
3. 上下文绑定（request_id、node_id）透传更方便
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings


def setup_logging() -> None:
    """应用启动时调用一次。配置 structlog + 标准 logging 的桥接。"""
    level = getattr(logging, settings.APP_LOG_LEVEL.upper(), logging.INFO)

    # 1) 标准库 logging 配置（第三方库通过它输出）
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )

    # 2) 共享处理器：注入时间戳、日志级别、调用位置
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # 3) 开发期输出彩色易读；生产期输出 JSON 便于采集
    if settings.APP_ENV == "development":
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = shared_processors + [
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """取一个 logger。name 一般传 `__name__`。"""
    return structlog.get_logger(name)
