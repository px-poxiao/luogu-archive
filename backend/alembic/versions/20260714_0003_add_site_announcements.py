"""add site announcements

Revision ID: 20260714_0003
Revises: add_user_profile_changes
Create Date: 2026-07-14
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260714_0003"
down_revision: Union[str, Sequence[str], None] = "add_user_profile_changes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_announcements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["admins.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_site_announcements_publish",
        "site_announcements",
        ["is_published", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_announcements_publish", table_name="site_announcements")
    op.drop_table("site_announcements")
