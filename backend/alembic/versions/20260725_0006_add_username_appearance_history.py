"""为用户名历史增加外显快照字段。

Revision ID: 20260725_0006
Revises: 20260718_0005
Create Date: 2026-07-25
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260725_0006"
down_revision: Union[str, Sequence[str], None] = "20260718_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先允许为空，再用用户当前外显补齐旧记录，避免给历史数据凭空编造多次变化。
    op.add_column(
        "user_name_versions",
        sa.Column("color", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "user_name_versions",
        sa.Column("badge", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "user_name_versions",
        sa.Column("ccf_level", sa.Integer(), nullable=True),
    )
    op.add_column(
        "user_name_versions",
        sa.Column("xcpc_level", sa.Integer(), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE user_name_versions AS history
            INNER JOIN luogu_users AS users ON users.uid = history.uid
            SET
                history.color = users.color,
                history.badge = users.badge,
                history.ccf_level = users.ccf_level,
                history.xcpc_level = users.xcpc_level
            """
        )
    )

    op.alter_column(
        "user_name_versions",
        "color",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="Gray",
    )
    op.alter_column(
        "user_name_versions",
        "ccf_level",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )
    op.alter_column(
        "user_name_versions",
        "xcpc_level",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )


def downgrade() -> None:
    op.drop_column("user_name_versions", "xcpc_level")
    op.drop_column("user_name_versions", "ccf_level")
    op.drop_column("user_name_versions", "badge")
    op.drop_column("user_name_versions", "color")
