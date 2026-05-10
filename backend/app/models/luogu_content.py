"""洛谷内容相关 ORM 模型：文章 / 剪贴板 / 犇犇 / 陶片 / 题目。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._common import BigPKColumn, TimestampMixin, utcnow


# ============================================================
# 专栏文章
# ============================================================

class Article(Base, TimestampMixin):
    """洛谷文章最新快照。article_id 为洛谷原 ID（8 位 字母+数字）。"""

    __tablename__ = "articles"

    # 8 位洛谷 ID 做主键，直接字符串
    article_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    author_uid: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)

    # 当前有效版本 id；便于主查询只 JOIN 一次
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )

    # 原文是否已删除
    is_deleted_on_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    first_crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    versions: Mapped[list[ArticleVersion]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        foreign_keys="ArticleVersion.article_id",
    )


class ArticleVersion(Base):
    """文章历史版本。content_hash 判重：相同 hash 不再插入。"""

    __tablename__ = "article_versions"
    __table_args__ = (
        Index("ix_av_article_crawled", "article_id", "crawled_at"),
        UniqueConstraint("article_id", "content_hash", name="uq_av_article_hash"),
    )

    id: Mapped[int] = BigPKColumn()
    article_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("articles.article_id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    crawler_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    article: Mapped[Article] = relationship(back_populates="versions")


# ============================================================
# 剪贴板
# ============================================================

class Paste(Base, TimestampMixin):
    __tablename__ = "pastes"

    paste_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    author_uid: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    is_deleted_on_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    versions: Mapped[list[PasteVersion]] = relationship(
        back_populates="paste",
        cascade="all, delete-orphan",
        foreign_keys="PasteVersion.paste_id",
    )


class PasteVersion(Base):
    __tablename__ = "paste_versions"
    __table_args__ = (
        Index("ix_pv_paste_crawled", "paste_id", "crawled_at"),
        UniqueConstraint("paste_id", "content_hash", name="uq_pv_paste_hash"),
    )

    id: Mapped[int] = BigPKColumn()
    paste_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("pastes.paste_id", ondelete="CASCADE"), nullable=False
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    crawler_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    paste: Mapped[Paste] = relationship(back_populates="versions")


# ============================================================
# 犇犇（不可编辑，不做版本快照）
# ============================================================

class Feed(Base):
    """犇犇。洛谷原 feed id 做主键。不可编辑，没版本历史。"""

    __tablename__ = "feeds"
    __table_args__ = (
        Index("ix_feed_author_time", "author_uid", "time"),
        Index("ix_feed_time", "time"),  # 伪全网犇按时间倒序
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    author_uid: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


# ============================================================
# 陶片放逐（追加式）
# ============================================================

class Judgement(Base):
    """陶片放逐记录。每条追加式存储，从不更新。

    防重用 reason_hash（sha256 截前 16 字节 hex = 32 字符）做 UNIQUE(uid, time, reason_hash)。
    MySQL 不支持在 TEXT 列直接建唯一索引，所以原文保留在 reason 里，索引走 hash。
    """

    __tablename__ = "judgements"
    __table_args__ = (
        UniqueConstraint("uid", "time", "reason_hash", name="uq_judgement_key"),
        Index("ix_judgement_time", "time"),
        Index("ix_judgement_uid_time", "uid", "time"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 当时的用户名快照（即使后续改名也能追溯）
    username_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # reason 的 sha256 前 32 位，用于防重
    reason_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    revoked_permission: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_permission: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


# ============================================================
# 题目（只追踪难度 + 题解开放状态）
# ============================================================

class Problem(Base, TimestampMixin):
    """题目。pid 格式 `P1001` / `B2001` / `CF1A` 等，直接字符串主键。"""

    __tablename__ = "problems"

    pid: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # 难度：用枚举字符串存（入门/普及-/普及/提高-/提高+/省选-/省选/NOI-/NOI/NOI+/CTSC/暂无评定）
    difficulty: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # 是否允许提交题解
    solution_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    last_solution_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    solution_history: Mapped[list[ProblemSolutionHistory]] = relationship(
        back_populates="problem",
        cascade="all, delete-orphan",
    )


class ProblemSolutionHistory(Base):
    """题解开放状态变更追踪。只在状态真正变化时写入。"""

    __tablename__ = "problem_solution_history"
    __table_args__ = (
        Index("ix_psh_pid_time", "pid", "changed_at"),
    )

    id: Mapped[int] = BigPKColumn()
    pid: Mapped[str] = mapped_column(
        String(32), ForeignKey("problems.pid", ondelete="CASCADE"), nullable=False
    )
    solution_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    problem: Mapped[Problem] = relationship(back_populates="solution_history")
