"""为本站用户增加 TOTP 2FA 字段。

Revision ID: 20260828_0016
Revises: 20260824_0015
Create Date: 2026-08-28
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0016"
down_revision: Union[str, None] = "20260824_0015"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("site_users", sa.Column("totp_secret_encrypted", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("site_users", "totp_secret_encrypted")
