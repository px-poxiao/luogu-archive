"""本站用户（邮箱注册）、关注、session。

与洛谷账号完全独立。普通用户仅能：
1. 关注洛谷用户（仅此一项）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._common import (
    BigPKColumn,
    TimestampMixin,
    utcnow,
)


class SiteUser(Base, TimestampMixin):
    """本站注册用户。"""

    __tablename__ = "site_users"

    id: Mapped[int] = BigPKColumn()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 邮箱验证
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_verification_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email_verification_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 登录追踪
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 管理
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    follows: Mapped[list[SiteUserFollow]] = relationship(
        back_populates="site_user",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list[SiteSession]] = relationship(
        back_populates="site_user",
        cascade="all, delete-orphan",
    )


class SiteUserFollow(Base):
    """关注关系：本站用户 → 某个洛谷 UID。"""

    __tablename__ = "site_user_follows"
    __table_args__ = (
        UniqueConstraint("site_user_id", "target_luogu_uid", name="uq_sf_user_target"),
        Index("ix_sf_target", "target_luogu_uid"),
    )

    id: Mapped[int] = BigPKColumn()
    site_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("site_users.id", ondelete="CASCADE"), nullable=False
    )
    target_luogu_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    site_user: Mapped[SiteUser] = relationship(back_populates="follows")


class SiteSession(Base):
    """站点用户会话（refresh token 记录 + 审计）。"""

    __tablename__ = "site_sessions"
    __table_args__ = (
        Index("ix_ss_user_expires", "site_user_id", "expires_at"),
    )

    id: Mapped[int] = BigPKColumn()
    site_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("site_users.id", ondelete="CASCADE"), nullable=False
    )
    # 存哈希后的 token，防拖库
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ua: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    site_user: Mapped[SiteUser] = relationship(back_populates="sessions")
