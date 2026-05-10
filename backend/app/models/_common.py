"""跨模型复用的 SQLAlchemy 类型、枚举、辅助列。"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


# ============================================================
# 枚举
# ============================================================

class LuoguColor(str, enum.Enum):
    """洛谷用户名颜色枚举（实测字符串值，非 hex）。"""

    Gray = "Gray"
    Blue = "Blue"
    Green = "Green"
    Orange = "Orange"
    Red = "Red"
    Purple = "Purple"
    Cyan = "Cyan"
    Black = "Black"
    Cheater = "Cheater"  # 棕名


class CrawlTaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"      # 去重跳过
    rate_limited = "rate_limited"


class CrawlTrigger(str, enum.Enum):
    """爬虫触发源，用于审计分析。"""

    manual = "manual"        # 保存按钮
    scheduled = "scheduled"  # 定时任务
    passive = "passive"      # 访问触发
    realtime = "realtime"    # 实时监听
    discovery = "discovery"  # 入口页发现
    internal = "internal"    # 内部调度（如补数）


class TakedownStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class NameViolationSource(str, enum.Enum):
    JUDGEMENT = "JUDGEMENT"                # 陶片 reason 关键词
    SYSTEM_NAME_PATTERN = "SYSTEM_NAME_PATTERN"  # 用户名匹配系统格式
    MANUAL = "MANUAL"                      # 管理员手动标记


# ============================================================
# 时间工具
# ============================================================

def utcnow() -> datetime:
    """库内统一使用 UTC，展示时再按用户时区转换。"""
    return datetime.now(timezone.utc)


# ============================================================
# 常用列（TimestampMixin）
# ============================================================

class TimestampMixin:
    """带 created_at / updated_at 的 mixin。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


# 全站 id 主键统一用 BIGINT，避免超 21 亿。
# 注意：必须是**工厂函数**而不是模块级单例，否则同一个 mapped_column
# 对象会被多个 model 共用，SQLAlchemy 会抛 "Column already assigned to Table"。
def BigPKColumn() -> Mapped[int]:  # type: ignore[misc]
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


def IntPKColumn() -> Mapped[int]:  # type: ignore[misc]
    return mapped_column(Integer, primary_key=True, autoincrement=True)
