"""创建 2026-05-10 的初始数据库结构。

Revision ID: 20260510_0001
Revises:
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260510_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column(
    name: str,
    type_: sa.types.TypeEngine,
    *,
    nullable: bool = False,
    primary_key: bool = False,
    autoincrement: bool | str = "auto",
    foreign_key: str | None = None,
    unique: bool = False,
) -> sa.Column:
    """生成冻结基线使用的列，避免重复书写外键参数。"""
    args: list[object] = [name, type_]
    if foreign_key:
        args.append(sa.ForeignKey(foreign_key, ondelete="CASCADE"))
    return sa.Column(
        *args,
        nullable=nullable,
        primary_key=primary_key,
        autoincrement=autoincrement,
        unique=unique,
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    """返回初始模型共用的创建、更新时间列。"""
    return (
        _column("created_at", sa.DateTime(timezone=True)),
        _column("updated_at", sa.DateTime(timezone=True)),
    )


def _add_indexes(
    table: sa.Table,
    indexes: Sequence[tuple[str, Sequence[str], bool]],
) -> None:
    """给冻结表添加命名索引。"""
    for name, columns, unique in indexes:
        sa.Index(name, *(table.c[column] for column in columns), unique=unique)


def _baseline_metadata() -> sa.MetaData:
    """构造 0001 发布时的固定结构，禁止引用会继续变化的 ORM 模型。"""
    metadata = sa.MetaData()

    sa.Table(
        "admins", metadata,
        _column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _column("username", sa.String(64), unique=True),
        _column("password_hash", sa.String(255)),
        _column("totp_secret_encrypted", sa.String(512)),
        _column("display_name", sa.String(64)),
        _column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _column("last_login_ip", sa.String(64), nullable=True),
        _column("is_disabled", sa.Boolean()),
        *_timestamps(),
    )

    table = sa.Table(
        "admin_audit_logs", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("admin_id", sa.Integer(), nullable=True),
        _column("admin_username", sa.String(64)),
        _column("action", sa.String(64)),
        _column("target_type", sa.String(32), nullable=True),
        _column("target_id", sa.String(64), nullable=True),
        _column("params", sa.JSON(), nullable=True),
        _column("ip", sa.String(64), nullable=True),
        _column("ua", sa.String(512), nullable=True),
        _column("happened_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, (
        ("ix_aal_admin_time", ("admin_id", "happened_at"), False),
        ("ix_aal_target", ("target_type", "target_id"), False),
    ))

    table = sa.Table(
        "crawler_accounts", metadata,
        _column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _column("label", sa.String(64)),
        _column("luogu_uid", sa.BigInteger()),
        _column("uid_value_encrypted", sa.String(512)),
        _column("client_id_encrypted", sa.String(512)),
        _column("c3vk_encrypted", sa.String(512), nullable=True),
        _column("enabled", sa.Boolean()),
        _column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        _column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        _column("last_status", sa.String(32), nullable=True),
        _column("fail_count", sa.Integer()),
        _column("disabled_reason", sa.Text(), nullable=True),
        *_timestamps(),
    )
    _add_indexes(table, (("ix_crawler_accounts_last_used_at", ("last_used_at",), False),))

    table = sa.Table(
        "articles", metadata,
        _column("article_id", sa.String(16), primary_key=True),
        _column("author_uid", sa.BigInteger(), nullable=True),
        _column("title", sa.String(512)),
        _column("current_version_id", sa.BigInteger(), nullable=True),
        _column("is_deleted_on_source", sa.Boolean()),
        _column("first_crawled_at", sa.DateTime(timezone=True)),
        _column("last_crawled_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    _add_indexes(table, (
        ("ix_articles_author_uid", ("author_uid",), False),
        ("ix_articles_current_version_id", ("current_version_id",), False),
    ))

    table = sa.Table(
        "article_versions", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("article_id", sa.String(16), foreign_key="articles.article_id"),
        _column("title", sa.String(512)),
        _column("content_md", sa.Text()),
        _column("content_hash", sa.String(64)),
        _column("crawled_at", sa.DateTime(timezone=True)),
        _column("crawler_node_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("article_id", "content_hash", name="uq_av_article_hash"),
    )
    _add_indexes(table, (("ix_av_article_crawled", ("article_id", "crawled_at"), False),))

    table = sa.Table(
        "pastes", metadata,
        _column("paste_id", sa.String(16), primary_key=True),
        _column("author_uid", sa.BigInteger(), nullable=True),
        _column("current_version_id", sa.BigInteger(), nullable=True),
        _column("is_deleted_on_source", sa.Boolean()),
        _column("first_crawled_at", sa.DateTime(timezone=True)),
        _column("last_crawled_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    _add_indexes(table, (
        ("ix_pastes_author_uid", ("author_uid",), False),
        ("ix_pastes_current_version_id", ("current_version_id",), False),
    ))

    table = sa.Table(
        "paste_versions", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("paste_id", sa.String(16), foreign_key="pastes.paste_id"),
        _column("content_md", sa.Text()),
        _column("content_hash", sa.String(64)),
        _column("crawled_at", sa.DateTime(timezone=True)),
        _column("crawler_node_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("paste_id", "content_hash", name="uq_pv_paste_hash"),
    )
    _add_indexes(table, (("ix_pv_paste_crawled", ("paste_id", "crawled_at"), False),))

    table = sa.Table(
        "feeds", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        _column("author_uid", sa.BigInteger(), nullable=True),
        _column("type", sa.Integer()),
        _column("time", sa.DateTime(timezone=True)),
        _column("content_md", sa.Text()),
        _column("crawled_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, (
        ("ix_feed_author_time", ("author_uid", "time"), False),
        ("ix_feed_time", ("time",), False),
    ))

    table = sa.Table(
        "judgements", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger()),
        _column("username_snapshot", sa.String(128)),
        _column("reason", sa.Text()),
        _column("revoked_permission", sa.Integer()),
        _column("added_permission", sa.Integer()),
        _column("time", sa.DateTime(timezone=True)),
        _column("crawled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("uid", "time", "reason", name="uq_judgement_key"),
    )
    _add_indexes(table, (
        ("ix_judgement_time", ("time",), False),
        ("ix_judgement_uid_time", ("uid", "time"), False),
    ))

    table = sa.Table(
        "problems", metadata,
        _column("pid", sa.String(32), primary_key=True),
        _column("title", sa.String(512)),
        _column("difficulty", sa.String(32), nullable=True),
        _column("solution_open", sa.Boolean()),
        _column("last_solution_check_at", sa.DateTime(timezone=True), nullable=True),
        _column("first_seen_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    _add_indexes(table, (
        ("ix_problems_difficulty", ("difficulty",), False),
        ("ix_problems_solution_open", ("solution_open",), False),
    ))

    table = sa.Table(
        "problem_solution_history", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("pid", sa.String(32), foreign_key="problems.pid"),
        _column("solution_open", sa.Boolean()),
        _column("changed_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, (("ix_psh_pid_time", ("pid", "changed_at"), False),))

    table = sa.Table(
        "luogu_users", metadata,
        _column("uid", sa.BigInteger(), primary_key=True, autoincrement=False),
        _column("name", sa.String(128)),
        _column("avatar", sa.String(512), nullable=True),
        _column("background", sa.String(512), nullable=True),
        _column("slogan", sa.String(512), nullable=True),
        _column("badge", sa.String(64), nullable=True),
        _column("introduction", sa.Text(), nullable=True),
        _column("color", sa.String(16)),
        _column("is_admin", sa.Boolean()),
        _column("is_banned", sa.Boolean()),
        _column("ccf_level", sa.Integer()),
        _column("xcpc_level", sa.Integer()),
        _column("following_count", sa.Integer()),
        _column("follower_count", sa.Integer()),
        _column("ranking", sa.Integer(), nullable=True),
        _column("passed_problem_count", sa.Integer(), nullable=True),
        _column("submitted_problem_count", sa.Integer(), nullable=True),
        _column("register_time", sa.DateTime(timezone=True), nullable=True),
        _column("first_crawled_at", sa.DateTime(timezone=True)),
        _column("last_crawled_at", sa.DateTime(timezone=True)),
        _column("last_active_feed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    _add_indexes(table, (
        ("ix_luogu_users_name", ("name",), False),
        ("ix_luogu_users_last_active_feed_at", ("last_active_feed_at",), False),
    ))

    table = sa.Table(
        "user_name_versions", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("name", sa.String(128)),
        _column("first_seen_at", sa.DateTime(timezone=True)),
        _column("last_seen_at", sa.DateTime(timezone=True)),
        _column("is_hidden", sa.Boolean()),
    )
    _add_indexes(table, (
        ("ix_unv_uid_first_seen", ("uid", "first_seen_at"), False),
        ("ix_user_name_versions_is_hidden", ("is_hidden",), False),
    ))

    table = sa.Table(
        "user_intro_versions", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("content", sa.Text()),
        _column("content_hash", sa.String(64)),
        _column("crawled_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, (("ix_uiv_uid_crawled", ("uid", "crawled_at"), False),))

    table = sa.Table(
        "user_prizes", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("year", sa.Integer()),
        _column("contest", sa.String(128)),
        _column("event", sa.String(128), nullable=True),
        _column("prize", sa.String(64)),
        sa.UniqueConstraint("uid", "year", "contest", "event", "prize", name="uq_user_prize"),
    )
    _add_indexes(table, (("ix_up_uid", ("uid",), False),))

    table = sa.Table(
        "user_elo_history", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("rating", sa.Integer()),
        _column("time", sa.DateTime(timezone=True)),
        _column("contest_id", sa.Integer()),
        _column("contest_name", sa.String(256)),
        _column("prev_diff", sa.Integer(), nullable=True),
        sa.UniqueConstraint("uid", "contest_id", name="uq_user_elo_contest"),
    )
    _add_indexes(table, (("ix_ueh_uid_time", ("uid", "time"), False),))

    table = sa.Table(
        "user_gu_history", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("rating", sa.Integer()),
        _column("time", sa.DateTime(timezone=True)),
        _column("social", sa.Integer()),
        _column("basic", sa.Integer()),
        _column("contest", sa.Integer()),
        _column("practice", sa.Integer()),
        _column("prize", sa.Integer()),
    )
    _add_indexes(table, (("ix_ugh_uid_time", ("uid", "time"), False),))

    sa.Table(
        "user_daily_activity", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("date", sa.Date()),
        _column("count", sa.Integer()),
        sa.UniqueConstraint("uid", "date", name="uq_uda_uid_date"),
    )

    table = sa.Table(
        "user_numeric_snapshots", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger()),
        _column("field_name", sa.String(64)),
        _column("value", sa.BigInteger()),
        _column("snapped_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, ((
        "ix_uns_uid_field_time", ("uid", "field_name", "snapped_at"), False,
    ),))

    table = sa.Table(
        "user_name_violations", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("uid", sa.BigInteger(), foreign_key="luogu_users.uid"),
        _column("trigger_source", sa.String(32)),
        _column("source_ref", sa.String(64), nullable=True),
        _column("reason_raw", sa.Text(), nullable=True),
        _column("matched_keywords", sa.JSON(), nullable=True),
        _column("triggered_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, (("ix_unvio_uid_triggered", ("uid", "triggered_at"), False),))

    table = sa.Table(
        "site_users", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("email", sa.String(254)),
        _column("password_hash", sa.String(255)),
        _column("display_name", sa.String(64)),
        _column("avatar_url", sa.String(512), nullable=True),
        _column("email_verified", sa.Boolean()),
        _column("email_verification_token", sa.String(128), nullable=True),
        _column("email_verification_expires", sa.DateTime(timezone=True), nullable=True),
        _column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _column("last_login_ip", sa.String(64), nullable=True),
        _column("failed_login_count", sa.Integer()),
        _column("locked_until", sa.DateTime(timezone=True), nullable=True),
        _column("is_banned", sa.Boolean()),
        *_timestamps(),
    )
    _add_indexes(table, (("ix_site_users_email", ("email",), True),))

    table = sa.Table(
        "site_user_follows", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("site_user_id", sa.BigInteger(), foreign_key="site_users.id"),
        _column("target_luogu_uid", sa.BigInteger()),
        _column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("site_user_id", "target_luogu_uid", name="uq_sf_user_target"),
    )
    _add_indexes(table, (("ix_sf_target", ("target_luogu_uid",), False),))

    table = sa.Table(
        "site_sessions", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("site_user_id", sa.BigInteger(), foreign_key="site_users.id"),
        _column("token_hash", sa.String(128), unique=True),
        _column("ip", sa.String(64), nullable=True),
        _column("ua", sa.String(512), nullable=True),
        _column("expires_at", sa.DateTime(timezone=True)),
        _column("created_at", sa.DateTime(timezone=True)),
        _column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_indexes(table, (("ix_ss_user_expires", ("site_user_id", "expires_at"), False),))

    table = sa.Table(
        "crawl_tasks", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("task_type", sa.String(32)),
        _column("url", sa.String(1024)),
        _column("node_id", sa.String(64), nullable=True),
        _column("account_id", sa.Integer(), nullable=True),
        _column("status", sa.String(16)),
        _column("http_status", sa.Integer(), nullable=True),
        _column("duration_ms", sa.Integer(), nullable=True),
        _column("error_msg", sa.Text(), nullable=True),
        _column("triggered_by", sa.String(16)),
        _column("started_at", sa.DateTime(timezone=True)),
        _column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_indexes(table, (
        ("ix_ct_type_time", ("task_type", "started_at"), False),
        ("ix_ct_status_time", ("status", "started_at"), False),
        ("ix_ct_node_time", ("node_id", "started_at"), False),
    ))

    table = sa.Table(
        "save_requests", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("ip", sa.String(64)),
        _column("user_agent", sa.String(512), nullable=True),
        _column("target_type", sa.String(32)),
        _column("target_id", sa.String(64)),
        _column("result", sa.String(32)),
        _column("crawl_task_id", sa.Integer(), nullable=True),
        _column("created_at", sa.DateTime(timezone=True)),
    )
    _add_indexes(table, (
        ("ix_sr_ip_time", ("ip", "created_at"), False),
        ("ix_sr_target", ("target_type", "target_id"), False),
    ))

    table = sa.Table(
        "takedown_requests", metadata,
        _column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _column("requester_name", sa.String(128), nullable=True),
        _column("requester_contact", sa.String(256), nullable=True),
        _column("target_type", sa.String(32)),
        _column("target_id", sa.String(64)),
        _column("reason", sa.Text()),
        _column("evidence", sa.JSON(), nullable=True),
        _column("status", sa.String(16)),
        _column("admin_id", sa.Integer(), nullable=True),
        _column("admin_note", sa.Text(), nullable=True),
        _column("handled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    _add_indexes(table, (("ix_tr_status_time", ("status", "created_at"), False),))

    return metadata


def upgrade() -> None:
    # install.sh 从空库执行 upgrade head；这里只能创建 0001 当时已有的结构。
    _baseline_metadata().create_all(bind=op.get_bind())


def downgrade() -> None:
    # 后续迁移降级完成后，按外键依赖的逆序删除初始结构。
    _baseline_metadata().drop_all(bind=op.get_bind())
