"""补全用户 Elo 历史字段

Revision ID: 20260606_0002
Revises: 20260510_0001
Create Date: 2026-06-06
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260606_0002"
down_revision: Union[str, Sequence[str], None] = "20260510_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "user_elo_history"


def _existing_columns() -> set[str]:
    """读取当前表字段；新库由首个迁移 create_all 时可能已经带齐字段。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE_NAME)}


def _add_column_if_missing(existing: set[str], column: sa.Column) -> None:
    if column.name not in existing:
        op.add_column(TABLE_NAME, column)


def _drop_column_if_exists(existing: set[str], column_name: str) -> None:
    if column_name in existing:
        op.drop_column(TABLE_NAME, column_name)


def upgrade() -> None:
    existing = _existing_columns()
    if not existing:
        return

    _add_column_if_missing(
        existing,
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(existing, sa.Column("user_count", sa.Integer(), nullable=True))
    _add_column_if_missing(
        existing,
        sa.Column("contest_start_time", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        existing,
        sa.Column("contest_end_time", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(existing, sa.Column("previous_rating", sa.Integer(), nullable=True))
    _add_column_if_missing(
        existing,
        sa.Column("previous_time", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(existing, sa.Column("previous_is_latest", sa.Boolean(), nullable=True))
    _add_column_if_missing(existing, sa.Column("previous_contest_id", sa.Integer(), nullable=True))
    _add_column_if_missing(
        existing,
        sa.Column("previous_contest_name", sa.String(length=256), nullable=True),
    )
    _add_column_if_missing(
        existing,
        sa.Column("previous_contest_start_time", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        existing,
        sa.Column("previous_contest_end_time", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(existing, sa.Column("previous_user_count", sa.Integer(), nullable=True))
    _add_column_if_missing(existing, sa.Column("previous_diff", sa.Integer(), nullable=True))
    _add_column_if_missing(existing, sa.Column("raw_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns()
    for column_name in [
        "raw_data",
        "previous_diff",
        "previous_user_count",
        "previous_contest_end_time",
        "previous_contest_start_time",
        "previous_contest_name",
        "previous_contest_id",
        "previous_is_latest",
        "previous_time",
        "previous_rating",
        "contest_end_time",
        "contest_start_time",
        "user_count",
        "is_latest",
    ]:
        _drop_column_if_exists(existing, column_name)
