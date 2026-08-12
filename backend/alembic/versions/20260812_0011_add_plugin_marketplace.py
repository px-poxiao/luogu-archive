"""新增插件广场、审核流程与管理员通知邮箱。

Revision ID: 20260812_0011
Revises: 20260812_0010
Create Date: 2026-08-12
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260812_0011"
down_revision: str | Sequence[str] | None = "20260812_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_TAGS = [
    "界面美化", "题目工具", "比赛工具", "讨论增强", "专栏增强",
    "犇犇工具", "数据统计", "效率工具", "无障碍", "开发工具",
]


def upgrade() -> None:
    op.add_column("admins", sa.Column("notification_email", sa.String(254), nullable=True))
    op.add_column(
        "admins",
        sa.Column("notification_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "admins", sa.Column("notification_email_token_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "admins", sa.Column("notification_email_expires", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "plugins",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.String(16), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_listed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("down_reason", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["site_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", name="uq_plugins_article_id"),
    )
    op.create_index("ix_plugins_current_version_id", "plugins", ["current_version_id"])
    op.create_index("ix_plugins_public_time", "plugins", ["is_listed", "updated_at"])
    op.create_index("ix_plugins_owner", "plugins", ["owner_user_id", "updated_at"])

    op.create_table(
        "plugin_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "plugin_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("code", mysql.LONGTEXT(), nullable=False),
        sa.Column("code_sha256", sa.String(64), nullable=False),
        sa.Column("download_filename", sa.String(128), nullable=False),
        sa.Column("user_request_level", sa.Integer(), nullable=False),
        sa.Column("user_request_analysis", mysql.LONGTEXT(), nullable=False),
        sa.Column("admin_request_level", sa.Integer(), nullable=True),
        sa.Column("admin_request_analysis", mysql.LONGTEXT(), nullable=True),
        sa.Column("final_request_level", sa.Integer(), nullable=False),
        sa.Column("runtime_mode", sa.String(32), nullable=False),
        sa.Column("supports_desktop", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supports_mobile", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("target_pages", sa.Text(), nullable=False),
        sa.Column("last_verified_on", sa.Date(), nullable=False),
        sa.Column("min_compatible_date", sa.Date(), nullable=True),
        sa.Column("compatibility_notes", sa.Text(), nullable=True),
        sa.Column("source_application_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_id", "version", name="uq_plugin_versions_version"),
    )
    op.create_index("ix_plugin_versions_final_request_level", "plugin_versions", ["final_request_level"])
    op.create_index("ix_plugin_versions_runtime_mode", "plugin_versions", ["runtime_mode"])
    op.create_index("ix_plugin_versions_plugin_time", "plugin_versions", ["plugin_id", "published_at"])

    op.create_table(
        "plugin_tag_links",
        sa.Column("plugin_id", sa.BigInteger(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["plugin_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plugin_id", "tag_id"),
    )

    op.create_table(
        "plugin_applications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.BigInteger(), nullable=True),
        sa.Column("article_id", sa.String(16), nullable=False),
        sa.Column("applicant_user_id", sa.BigInteger(), nullable=False),
        sa.Column("application_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("user_request_level", sa.Integer(), nullable=True),
        sa.Column("snapshot_json", mysql.LONGTEXT(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["applicant_user_id"], ["site_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plugin_apps_status_time", "plugin_applications", ["status", "created_at"])
    op.create_index("ix_plugin_apps_plugin_type", "plugin_applications", ["plugin_id", "application_type", "status"])
    op.create_index("ix_plugin_apps_applicant", "plugin_applications", ["applicant_user_id", "created_at"])
    op.create_index("ix_plugin_applications_application_type", "plugin_applications", ["application_type"])
    op.create_index("ix_plugin_applications_status", "plugin_applications", ["status"])

    op.create_table(
        "plugin_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_user_id", sa.BigInteger(), nullable=False),
        sa.Column("report_type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("handled_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["site_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["handled_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plugin_reports_status_time", "plugin_reports", ["status", "created_at"])
    op.create_index("ix_plugin_reports_plugin", "plugin_reports", ["plugin_id", "created_at"])
    op.create_index("ix_plugin_reports_status", "plugin_reports", ["status"])

    tags = sa.table(
        "plugin_tags",
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    # bulk_insert 需要真实值，不能把 SQL 函数对象当作绑定参数写入。
    now = datetime.now(timezone.utc)
    op.bulk_insert(tags, [
        {"name": name, "is_active": True, "sort_order": index, "created_at": now, "updated_at": now}
        for index, name in enumerate(DEFAULT_TAGS, start=1)
    ])


def downgrade() -> None:
    op.drop_table("plugin_reports")
    op.drop_table("plugin_applications")
    op.drop_table("plugin_tag_links")
    op.drop_table("plugin_versions")
    op.drop_table("plugin_tags")
    op.drop_table("plugins")
    op.drop_column("admins", "notification_email_expires")
    op.drop_column("admins", "notification_email_token_hash")
    op.drop_column("admins", "notification_email_verified")
    op.drop_column("admins", "notification_email")
