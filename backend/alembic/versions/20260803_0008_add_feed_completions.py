"""增加犇犇回复补全结果缓存。

Revision ID: 20260803_0008
Revises: 20260726_0007
Create Date: 2026-08-03
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260803_0008"
down_revision: Union[str, Sequence[str], None] = "20260726_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 独立缓存表避免修改 feeds 原始正文，也便于以后整体重算或清空。
    op.create_table(
        "feed_completions",
        sa.Column("feed_id", sa.BigInteger(), nullable=False),
        sa.Column("content_md", mysql.LONGTEXT(), nullable=False),
        sa.Column("merged_suffix_md", mysql.LONGTEXT(), nullable=True),
        sa.Column("merged_from_id", sa.BigInteger(), nullable=True),
        sa.Column("merged_link_md", sa.JSON(), nullable=True),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("algorithm_version", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feed_id"], ["feeds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("feed_id"),
    )
    op.create_index(
        "ix_feed_completion_computed_at",
        "feed_completions",
        ["computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feed_completion_computed_at", table_name="feed_completions")
    op.drop_table("feed_completions")
