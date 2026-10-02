"""增加插件去重使用事件表。

Revision ID: 20260912_0016
Revises: 20260824_0015
Create Date: 2026-09-12
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260912_0016"
down_revision: str | Sequence[str] | None = "20260824_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 只保存不可逆访客摘要，不保存原始 IP 或 User-Agent。
    op.create_table(
        "plugin_usage_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("visitor_key", sa.String(length=64), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["plugin_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plugin_id",
            "visitor_key",
            "event_date",
            "action",
            name="uq_plugin_usage_visitor_day_action",
        ),
    )
    op.create_index(
        "ix_plugin_usage_date_plugin",
        "plugin_usage_events",
        ["event_date", "plugin_id"],
    )
    op.create_index(
        "ix_plugin_usage_plugin_date",
        "plugin_usage_events",
        ["plugin_id", "event_date"],
    )
    op.create_index(
        "ix_plugin_usage_version_date",
        "plugin_usage_events",
        ["version_id", "event_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_plugin_usage_version_date", table_name="plugin_usage_events")
    op.drop_index("ix_plugin_usage_plugin_date", table_name="plugin_usage_events")
    op.drop_index("ix_plugin_usage_date_plugin", table_name="plugin_usage_events")
    op.drop_table("plugin_usage_events")
