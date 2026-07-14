"""add last feed crawled timestamp

Revision ID: 20260714_0004
Revises: 20260714_0003
Create Date: 2026-07-14
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260714_0004"
down_revision: Union[str, Sequence[str], None] = "20260714_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "luogu_users",
        sa.Column("last_feed_crawled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 上线前调度器一直用 last_crawled_at 近似犇犇抓取时间。先沿用该基线，
    # 避免部署后所有活跃用户因新列为 NULL 被一次性重新入队。
    op.execute(
        "UPDATE luogu_users "
        "SET last_feed_crawled_at = last_crawled_at "
        "WHERE last_feed_crawled_at IS NULL"
    )
    op.create_index(
        "ix_luogu_users_last_feed_crawled_at",
        "luogu_users",
        ["last_feed_crawled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_luogu_users_last_feed_crawled_at", table_name="luogu_users")
    op.drop_column("luogu_users", "last_feed_crawled_at")
