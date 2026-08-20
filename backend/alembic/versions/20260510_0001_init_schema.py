"""init schema

Revision ID: 20260510_0001
Revises:
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "20260510_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ==========================================================
# 说明：本脚本等价于对所有 SQLAlchemy 模型执行 Base.metadata.create_all。
# 但显式写出来有两个好处：
# 1) 后续 autogenerate 可以基于这个"空基线"产生干净 diff
# 2) 版本演化可回滚，测试可重放
# 为了精简，本文件直接调用 create_all / drop_all，而非逐表手写 op.create_table。
# ==========================================================

def upgrade() -> None:
    from app.core.db import Base
    # 导入触发所有模型注册到 metadata
    from app import models  # noqa: F401

    bind = op.get_bind()
    if hasattr(bind, "engine"):
        bind = bind.engine
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.core.db import Base
    from app import models  # noqa: F401

    bind = op.get_bind()
    if hasattr(bind, "engine"):
        bind = bind.engine
    Base.metadata.drop_all(bind=bind)
