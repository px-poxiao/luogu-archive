"""爬虫任务审计 + 保存请求审计 + 删除申请工单。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._common import (
    BigPKColumn,
    CrawlTaskStatus,
    CrawlTrigger,
    TakedownStatus,
    TimestampMixin,
    utcnow,
)


class CrawlTask(Base):
    """每次爬虫调用都记录一条，便于追踪健康度（403 率、耗时、失败原因）。"""

    __tablename__ = "crawl_tasks"
    __table_args__ = (
        Index("ix_ct_type_time", "task_type", "started_at"),
        Index("ix_ct_status_time", "status", "started_at"),
        Index("ix_ct_node_time", "node_id", "started_at"),
    )

    id: Mapped[int] = BigPKColumn
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # "article" / "paste" / "feed" / "user" / "judgement" / "problem_list" / "problem_solution"

    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 若用了 Cookie 账号，记录 id；未用为 NULL

    status: Mapped[CrawlTaskStatus] = mapped_column(
        Enum(CrawlTaskStatus, native_enum=False, length=16),
        nullable=False,
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    triggered_by: Mapped[CrawlTrigger] = mapped_column(
        Enum(CrawlTrigger, native_enum=False, length=16),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SaveRequest(Base):
    """前台"保存"按钮点击审计。用于追踪滥用。"""

    __tablename__ = "save_requests"
    __table_args__ = (
        Index("ix_sr_ip_time", "ip", "created_at"),
        Index("ix_sr_target", "target_type", "target_id"),
    )

    id: Mapped[int] = BigPKColumn
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # "ok" / "rate_limited" / "captcha_required" / "merged" / "failed"
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    # 若发起了爬虫任务，关联 CrawlTask.id
    crawl_task_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class TakedownRequest(Base, TimestampMixin):
    """侵权 / 删除申请工单。匿名或留邮箱都可。"""

    __tablename__ = "takedown_requests"
    __table_args__ = (
        Index("ix_tr_status_time", "status", "created_at"),
    )

    id: Mapped[int] = BigPKColumn
    requester_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requester_contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 支持的目标类型：article/paste/feed/user/judgement/image
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # 可选：证明文件、截图等
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[TakedownStatus] = mapped_column(
        Enum(TakedownStatus, native_enum=False, length=16),
        nullable=False,
        default=TakedownStatus.pending,
    )
    admin_id: Mapped[int | None] = mapped_column(nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
