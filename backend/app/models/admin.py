"""管理员、审计日志、爬取账号（Cookie 池）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._common import BigPKColumn, IntPKColumn, TimestampMixin, utcnow


class Admin(Base, TimestampMixin):
    """管理员账号。必带 2FA。"""

    __tablename__ = "admins"

    id: Mapped[int] = IntPKColumn
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet 加密后的 TOTP secret（不存明文）
    totp_secret_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)

    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AdminAuditLog(Base):
    """管理员操作审计。**只能插入，不能删除**（应用层保证）。"""

    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_aal_admin_time", "admin_id", "happened_at"),
        Index("ix_aal_target", "target_type", "target_id"),
    )

    id: Mapped[int] = BigPKColumn
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_username: Mapped[str] = mapped_column(String(64), nullable=False)

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ua: Mapped[str | None] = mapped_column(String(512), nullable=True)
    happened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class CrawlerAccount(Base, TimestampMixin):
    """管理员录入的洛谷爬取账号。仅用于犇犇。

    保号原则：
    - Cookie 字段存加密后密文
    - 异常即禁用
    - 最久未用优先轮换
    """

    __tablename__ = "crawler_accounts"

    id: Mapped[int] = IntPKColumn
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    luogu_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Fernet 加密后的 cookie 值
    uid_value_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    c3vk_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "403 / 429 / banned / ok"

    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
