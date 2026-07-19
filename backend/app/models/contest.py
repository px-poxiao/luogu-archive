"""比赛排行榜与等级分预测 ORM 模型。"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.contest_rating import is_elo_rated
from app.core.db import Base
from app.models._common import BigPKColumn, LuoguColor, TimestampMixin


class ContestArchiveStatus(str, enum.Enum):
    """比赛从发现到正式结算的处理状态。"""

    discovered = "discovered"
    queued = "queued"
    crawling = "crawling"
    refreshing_users = "refreshing_users"
    predicted = "predicted"
    official = "official"
    failed = "failed"


class Contest(Base, TimestampMixin):
    """洛谷比赛及其归档状态。"""

    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    method: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rated_type: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elo_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elo_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    problem_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[ContestArchiveStatus] = mapped_column(
        Enum(ContestArchiveStatus, native_enum=False, length=24),
        nullable=False,
        default=ContestArchiveStatus.discovered,
        index=True,
    )
    predicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    official_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_official_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    problems: Mapped[list[ContestProblem]] = relationship(
        back_populates="contest", cascade="all, delete-orphan"
    )
    participants: Mapped[list[ContestParticipant]] = relationship(
        back_populates="contest", cascade="all, delete-orphan"
    )

    @property
    def is_elo_rated(self) -> bool:
        """洛谷用 ``eloThreshold = -1`` 表示比赛不计等级分。"""

        return is_elo_rated(self.rated_type, self.elo_threshold)


class ContestProblem(Base):
    """比赛题目表头；不包含提交记录或代码。"""

    __tablename__ = "contest_problems"
    __table_args__ = (
        UniqueConstraint("contest_id", "pid", name="uq_contest_problem"),
        UniqueConstraint("contest_id", "label", name="uq_contest_problem_label"),
    )

    id: Mapped[int] = BigPKColumn()
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pid: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    contest: Mapped[Contest] = relationship(back_populates="problems")


class ContestParticipant(Base):
    """一场比赛中实际出现在排行榜上的用户。"""

    __tablename__ = "contest_participants"
    __table_args__ = (
        UniqueConstraint("contest_id", "uid", name="uq_contest_participant"),
        Index("ix_contest_participant_rank", "contest_id", "is_penalized", "rank_order"),
        Index("ix_contest_participant_name", "contest_id", "name"),
    )

    id: Mapped[int] = BigPKColumn()
    contest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="CASCADE"), nullable=False
    )
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[LuoguColor] = mapped_column(
        Enum(LuoguColor, native_enum=False, length=16),
        nullable=False,
        default=LuoguColor.Gray,
    )
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # rank_order 是原榜顺序；rank_value 是公式使用的并列平均名次。
    rank_order: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_value: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    running_time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    is_penalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    problem_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    profile_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    profile_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    profile_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    old_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    history_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performance: Mapped[float | None] = mapped_column(Float, nullable=True)
    rperf: Mapped[float | None] = mapped_column(Float, nullable=True)
    official_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    official_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)

    contest: Mapped[Contest] = relationship(back_populates="participants")
