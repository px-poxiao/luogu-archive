"""为本站用户增加洛谷账号绑定信息。

Revision ID: 20260812_0010
Revises: 20260803_0009
Create Date: 2026-08-12
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0010"
down_revision: Union[str, Sequence[str], None] = "20260803_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("site_users", sa.Column("luogu_uid", sa.BigInteger(), nullable=True))
    op.add_column(
        "site_users",
        sa.Column("luogu_bound_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_site_users_luogu_uid", "site_users", ["luogu_uid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_site_users_luogu_uid", table_name="site_users")
    op.drop_column("site_users", "luogu_bound_at")
    op.drop_column("site_users", "luogu_uid")
