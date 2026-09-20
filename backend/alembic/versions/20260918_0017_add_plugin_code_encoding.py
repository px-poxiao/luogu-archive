"""插件支持二进制文件：为版本表记录内容编码方式。

Revision ID: 20260918_0017
Revises: 20260912_0016
Create Date: 2026-09-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260918_0017"
down_revision: str | Sequence[str] | None = "20260912_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 存量版本全部是文本代码；默认值让老数据无需回填即可继续工作。
    op.add_column(
        "plugin_versions",
        sa.Column(
            "code_encoding",
            sa.String(length=16),
            nullable=False,
            server_default="text",
        ),
    )


def downgrade() -> None:
    op.drop_column("plugin_versions", "code_encoding")
