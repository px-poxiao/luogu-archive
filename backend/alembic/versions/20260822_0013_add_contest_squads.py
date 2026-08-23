"""保存比赛榜单中的组队信息。"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_0013"
down_revision = "20260822_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 新装数据库可能已由 metadata 建出字段，迁移需保持幂等。
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("contest_participants")}
    if "squad" not in columns:
        op.add_column("contest_participants", sa.Column("squad", sa.JSON(), nullable=True))
    if "squad_search_text" not in columns:
        op.add_column(
            "contest_participants",
            sa.Column("squad_search_text", sa.String(length=1024), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("contest_participants")}
    if "squad_search_text" in columns:
        op.drop_column("contest_participants", "squad_search_text")
    if "squad" in columns:
        op.drop_column("contest_participants", "squad")
