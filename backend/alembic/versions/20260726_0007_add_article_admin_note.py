"""为文章当前快照增加管理员提示。

Revision ID: 20260726_0007
Revises: 20260725_0006
Create Date: 2026-07-26
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260726_0007"
down_revision: Union[str, Sequence[str], None] = "20260725_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 管理员提示可能为空，也可能独立于正文发生变化。
    op.add_column("articles", sa.Column("admin_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "admin_note")
