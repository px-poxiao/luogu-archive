"""新增讨论区主帖、回复、版本和增量爬取状态。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260824_0014"
down_revision = "20260822_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "discussions" not in tables:
        op.create_table(
            "discussions",
            sa.Column("discussion_id", sa.BigInteger(), nullable=False),
            sa.Column("author_uid", sa.BigInteger(), nullable=True),
            sa.Column("current_version_id", sa.BigInteger(), nullable=True),
            sa.Column("forum_name", sa.String(length=128), nullable=True),
            sa.Column("forum_slug", sa.String(length=64), nullable=True),
            sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("observed_reply_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("archived_reply_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_crawled_page", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_per_page", sa.Integer(), nullable=True),
            sa.Column("auto_crawl_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("auto_crawl_paused_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_crawl_status", sa.String(length=32), nullable=True),
            sa.Column("first_crawled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("discussion_id"),
        )
        op.create_index("ix_discussions_author_uid", "discussions", ["author_uid"])
        op.create_index("ix_discussions_current_version_id", "discussions", ["current_version_id"])

    if "discussion_versions" not in tables:
        op.create_table(
            "discussion_versions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("discussion_id", sa.BigInteger(), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("content_md", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("crawler_node_id", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["discussion_id"], ["discussions.discussion_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("discussion_id", "content_hash", name="uq_dv_discussion_hash"),
        )
        op.create_index("ix_dv_discussion_crawled", "discussion_versions", ["discussion_id", "crawled_at"])

    if "discussion_replies" not in tables:
        op.create_table(
            "discussion_replies",
            sa.Column("reply_id", sa.BigInteger(), autoincrement=False, nullable=False),
            sa.Column("discussion_id", sa.BigInteger(), nullable=False),
            sa.Column("author_uid", sa.BigInteger(), nullable=True),
            sa.Column("current_version_id", sa.BigInteger(), nullable=True),
            sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_crawled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["discussion_id"], ["discussions.discussion_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("reply_id"),
        )
        op.create_index("ix_discussion_replies_author_uid", "discussion_replies", ["author_uid"])
        op.create_index("ix_discussion_replies_current_version_id", "discussion_replies", ["current_version_id"])
        op.create_index("ix_dr_discussion_time", "discussion_replies", ["discussion_id", "source_time"])

    if "discussion_reply_versions" not in tables:
        op.create_table(
            "discussion_reply_versions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("reply_id", sa.BigInteger(), nullable=False),
            sa.Column("content_md", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("crawler_node_id", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["reply_id"], ["discussion_replies.reply_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("reply_id", "content_hash", name="uq_drv_reply_hash"),
        )
        op.create_index("ix_drv_reply_crawled", "discussion_reply_versions", ["reply_id", "crawled_at"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (
        "discussion_reply_versions",
        "discussion_replies",
        "discussion_versions",
        "discussions",
    ):
        if table in tables:
            op.drop_table(table)
