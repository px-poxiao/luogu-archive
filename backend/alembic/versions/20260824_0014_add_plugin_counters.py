"""为插件版本与插件主表添加下载/复制计数列。

Revision ID: 20260824_0014
Revises: 20260812_0011
Create Date: 2026-08-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0014"
down_revision: str | Sequence[str] | None = "20260822_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 为每个正式的插件版本添加下载和复制计数
    op.add_column(
        "plugin_versions",
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "plugin_versions",
        sa.Column("copy_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # 为插件主表添加一个汇总计数（可选）。
    op.add_column(
        "plugins",
        sa.Column("total_usage", sa.Integer(), nullable=False, server_default="0"),
    )

    # 若需要，后续可写数据迁移将旧统计合并到新列中。


def downgrade() -> None:
    op.drop_column("plugins", "total_usage")
    op.drop_column("plugin_versions", "copy_count")
    op.drop_column("plugin_versions", "download_count")
