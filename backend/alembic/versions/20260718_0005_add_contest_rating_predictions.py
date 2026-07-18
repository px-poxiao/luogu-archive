"""新增比赛排行榜与等级分预测表。

Revision ID: 20260718_0005
Revises: 20260714_0004
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0005"
down_revision: Union[str, Sequence[str], None] = "20260714_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contests",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.Integer(), nullable=True),
        sa.Column("rated_type", sa.Integer(), nullable=False),
        sa.Column("elo_threshold", sa.Integer(), nullable=True),
        sa.Column("elo_done", sa.Boolean(), nullable=False),
        sa.Column("problem_count", sa.Integer(), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "discovered", "queued", "crawling", "refreshing_users",
                "predicted", "official", "failed",
                name="contestarchivestatus",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("official_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_official_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contests_end_time", "contests", ["end_time"])
    op.create_index("ix_contests_status", "contests", ["status"])
    op.create_index("ix_contests_last_official_check_at", "contests", ["last_official_check_at"])

    op.create_table(
        "contest_problems",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("pid", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=12), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "pid", name="uq_contest_problem"),
        sa.UniqueConstraint("contest_id", "label", name="uq_contest_problem_label"),
    )
    op.create_index("ix_contest_problems_contest_id", "contest_problems", ["contest_id"])

    op.create_table(
        "contest_participants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "color",
            sa.Enum(
                "Gray", "Blue", "Green", "Orange", "Red", "Purple",
                "Cyan", "Black", "Cheater", name="luogucolor",
                native_enum=False, length=16,
            ),
            nullable=False,
        ),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column("rank_order", sa.Integer(), nullable=False),
        sa.Column("rank_value", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("running_time", sa.BigInteger(), nullable=False),
        sa.Column("is_penalized", sa.Boolean(), nullable=False),
        sa.Column("problem_details", sa.JSON(), nullable=True),
        sa.Column("profile_status", sa.String(length=16), nullable=False),
        sa.Column("profile_source", sa.String(length=16), nullable=True),
        sa.Column("profile_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("old_rating", sa.Integer(), nullable=True),
        sa.Column("history_count", sa.Integer(), nullable=True),
        sa.Column("predicted_rating", sa.Integer(), nullable=True),
        sa.Column("predicted_delta", sa.Integer(), nullable=True),
        sa.Column("performance", sa.Float(), nullable=True),
        sa.Column("rperf", sa.Float(), nullable=True),
        sa.Column("official_rating", sa.Integer(), nullable=True),
        sa.Column("official_delta", sa.Integer(), nullable=True),
        sa.Column("warning_reasons", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "uid", name="uq_contest_participant"),
    )
    op.create_index(
        "ix_contest_participant_rank",
        "contest_participants",
        ["contest_id", "is_penalized", "rank_order"],
    )
    op.create_index(
        "ix_contest_participant_name", "contest_participants", ["contest_id", "name"]
    )


def downgrade() -> None:
    op.drop_table("contest_participants")
    op.drop_table("contest_problems")
    op.drop_table("contests")
