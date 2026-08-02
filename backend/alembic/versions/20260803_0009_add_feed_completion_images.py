"""为犇犇补全缓存增加图片标记。

Revision ID: 20260803_0009
Revises: 20260803_0008
Create Date: 2026-08-03
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0009"
down_revision: Union[str, Sequence[str], None] = "20260803_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feed_completions",
        sa.Column("merged_image_md", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("feed_completions", "merged_image_md")
