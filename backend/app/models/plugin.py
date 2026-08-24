"""插件广场相关模型。

插件以已归档文章为原文，代码和审核流程完全独立于文章版本。
只有审核通过的代码会进入 ``plugin_versions``，待审核内容保存在申请快照中。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._common import BigPKColumn, IntPKColumn, TimestampMixin, utcnow


class Plugin(Base, TimestampMixin):
    """一个文章对应一个插件，公开字段保存在主表以便广场筛选。"""

    __tablename__ = "plugins"
    __table_args__ = (
        UniqueConstraint("article_id", name="uq_plugins_article_id"),
        Index("ix_plugins_public_time", "is_listed", "updated_at"),
        Index("ix_plugins_owner", "owner_user_id", "updated_at"),
    )

    id: Mapped[int] = BigPKColumn()
    article_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("articles.article_id", ondelete="RESTRICT"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("site_users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_listed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    down_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # 插件总体使用计数（可选：将各版本的下载/复制合并到此字段）
    total_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PluginVersion(Base):
    """审核通过的不可变代码版本。管理员修改代码时同样创建新版本。"""

    __tablename__ = "plugin_versions"
    __table_args__ = (
        UniqueConstraint("plugin_id", "version", name="uq_plugin_versions_version"),
        Index("ix_plugin_versions_plugin_time", "plugin_id", "published_at"),
    )

    id: Mapped[int] = BigPKColumn()
    plugin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    code_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    download_filename: Mapped[str] = mapped_column(String(128), nullable=False)


    user_request_level: Mapped[int] = mapped_column(Integer, nullable=False)
    user_request_analysis: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    admin_request_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_request_analysis: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    final_request_level: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    runtime_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    supports_desktop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_mobile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_pages: Mapped[str] = mapped_column(Text, nullable=False)
    last_verified_on: Mapped[date] = mapped_column(Date, nullable=False)
    min_compatible_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    compatibility_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_application_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by_admin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # 计数器：下载与复制次数（每个版本独立累积），默认 0
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    copy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PluginTag(Base, TimestampMixin):
    """管理员维护的固定功能标签。"""

    __tablename__ = "plugin_tags"

    id: Mapped[int] = IntPKColumn()
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PluginTagLink(Base):
    """插件当前公开标签，用独立关系表支持稳定筛选。"""

    __tablename__ = "plugin_tag_links"

    plugin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plugins.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("plugin_tags.id", ondelete="CASCADE"), primary_key=True
    )


class PluginApplication(Base, TimestampMixin):
    """发布、更新、推荐和删除申请；内容快照使用 JSON 字符串完整保存。"""

    __tablename__ = "plugin_applications"
    __table_args__ = (
        Index("ix_plugin_apps_status_time", "status", "created_at"),
        Index("ix_plugin_apps_plugin_type", "plugin_id", "application_type", "status"),
        Index("ix_plugin_apps_applicant", "applicant_user_id", "created_at"),
    )

    id: Mapped[int] = BigPKColumn()
    plugin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("plugins.id", ondelete="RESTRICT"), nullable=True
    )
    article_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("articles.article_id", ondelete="RESTRICT"), nullable=False
    )
    applicant_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("site_users.id", ondelete="RESTRICT"), nullable=False
    )
    application_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_request_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_json: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admins.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PluginReport(Base, TimestampMixin):
    """登录用户提交的插件举报工单。"""

    __tablename__ = "plugin_reports"
    __table_args__ = (
        Index("ix_plugin_reports_status_time", "status", "created_at"),
        Index("ix_plugin_reports_plugin", "plugin_id", "created_at"),
    )

    id: Mapped[int] = BigPKColumn()
    plugin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plugins.id", ondelete="RESTRICT"), nullable=False
    )
    reporter_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("site_users.id", ondelete="RESTRICT"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    handled_by_admin_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admins.id", ondelete="RESTRICT"), nullable=True
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
