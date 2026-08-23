"""增加删除申请探测与内容软隐藏。"""

from alembic import op
import sqlalchemy as sa

revision = "20260822_0012"
down_revision = "20260812_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 初始迁移会按当前 metadata 建表，因此这里必须兼容“字段已经存在”的新装库。
    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("takedown_requests")}
    additions = {
        "requester_user_id": sa.Column("requester_user_id", sa.BigInteger(), nullable=True),
        "target_url": sa.Column("target_url", sa.String(1024), nullable=True),
        "target_author_uid": sa.Column("target_author_uid", sa.BigInteger(), nullable=True),
        "auto_approved": sa.Column("auto_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        "execution_status": sa.Column("execution_status", sa.String(32), nullable=True),
        "execution_error": sa.Column("execution_error", sa.Text(), nullable=True),
    }
    for name, column in additions.items():
        if name not in existing_columns:
            op.add_column("takedown_requests", column)
    request_indexes = {index["name"] for index in inspector.get_indexes("takedown_requests")}
    if "ix_takedown_requests_requester_user_id" not in request_indexes:
        op.create_index("ix_takedown_requests_requester_user_id", "takedown_requests", ["requester_user_id"])

    tables = set(inspector.get_table_names())
    if "takedown_probes" not in tables:
        op.create_table("takedown_probes",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("requester_user_id", sa.BigInteger(), nullable=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("target_url", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("accessible", sa.Boolean(), nullable=True),
        sa.Column("author_uid", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_takedown_probes_requester_user_id", "takedown_probes", ["requester_user_id"])
    if "content_suppressions" not in tables:
        op.create_table("content_suppressions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("owner_uid", sa.BigInteger(), nullable=True),
        sa.Column("takedown_request_id", sa.BigInteger(), nullable=True),
        sa.Column("public_message", sa.String(256), nullable=False),
        sa.Column("block_crawl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ux_cs_target", "content_suppressions", ["target_type", "target_id"], unique=True)
        op.create_index("ix_cs_owner", "content_suppressions", ["owner_uid", "restored_at"])

    # 奖项已经改为当前快照，清掉旧实现遗留的奖项变化日志。
    if "user_profile_changes" in tables:
        op.execute(sa.text("DELETE FROM user_profile_changes WHERE field_name = 'prize'"))


def downgrade() -> None:
    op.drop_table("content_suppressions")
    op.drop_table("takedown_probes")
    op.drop_index("ix_takedown_requests_requester_user_id", table_name="takedown_requests")
    for name in ("execution_error", "execution_status", "auto_approved", "target_author_uid", "target_url", "requester_user_id"):
        op.drop_column("takedown_requests", name)
