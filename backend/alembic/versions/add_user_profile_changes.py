"""add user profile changes

Revision ID: add_user_profile_changes
Revises: add_user_elo_history_fields
Create Date: 2026-06-21
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_user_profile_changes"
down_revision: Union[str, Sequence[str], None] = "20260606_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profile_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["uid"], ["luogu_users.uid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upc_uid_time", "user_profile_changes", ["uid", "changed_at"])


def downgrade() -> None:
    op.drop_index("ix_upc_uid_time", table_name="user_profile_changes")
    op.drop_table("user_profile_changes")
