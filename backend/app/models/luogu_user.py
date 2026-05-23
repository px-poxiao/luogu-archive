"""洛谷用户相关 ORM 模型。

设计要点：
- users 主表只存**最新**快照；所有历史进对应的 _versions / _history 表
- "文本字段"变化才存版本（introduction、name）
- "数值字段"（follower、ranking、咕值、Elo）存时间序列，不视作版本
- user_name_violations：命中即不可逆，此时刻之前的 name 永久隐藏
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._common import (
    BigPKColumn,
    IntPKColumn,
    LuoguColor,
    NameViolationSource,
    TimestampMixin,
    utcnow,
)


class LuoguUser(Base, TimestampMixin):
    """洛谷用户最新快照。uid 作为主键（洛谷原 uid）。"""

    __tablename__ = "luogu_users"

    uid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    # 基本信息
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    background: Mapped[str | None] = mapped_column(String(512), nullable=True)
    slogan: Mapped[str | None] = mapped_column(String(512), nullable=True)
    badge: Mapped[str | None] = mapped_column(String(64), nullable=True)
    introduction: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 状态
    color: Mapped[LuoguColor] = mapped_column(
        Enum(LuoguColor, native_enum=False, length=16),
        nullable=False,
        default=LuoguColor.Gray,
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # OI / ICPC 等级
    ccf_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    xcpc_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 计数（最新值；历史值进 user_numeric_snapshots）
    following_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    follower_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed_problem_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_problem_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 洛谷注册时间
    register_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 本站记录
    first_crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # 犇犇分层轮询依据：用户最近一次发犇犇时间
    last_active_feed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # 关系
    name_versions: Mapped[list[UserNameVersion]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    intro_versions: Mapped[list[UserIntroVersion]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    prizes: Mapped[list[UserPrize]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    elo_history: Mapped[list[UserEloHistory]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    gu_history: Mapped[list[UserGuHistory]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    daily_activity: Mapped[list[UserDailyActivity]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    name_violations: Mapped[list[UserNameViolation]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserNameVersion(Base):
    """用户名历史。每次改名关闭旧行 + 新增一行。"""

    __tablename__ = "user_name_versions"
    __table_args__ = (
        Index("ix_unv_uid_first_seen", "uid", "first_seen_at"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 是否被级联隐藏（由违规触发时批量置为 true）
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    user: Mapped[LuoguUser] = relationship(back_populates="name_versions")


class UserIntroVersion(Base):
    """用户个人介绍（markdown）历史版本。"""

    __tablename__ = "user_intro_versions"
    __table_args__ = (
        Index("ix_uiv_uid_crawled", "uid", "crawled_at"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 hex 64 位
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    user: Mapped[LuoguUser] = relationship(back_populates="intro_versions")


class UserPrize(Base):
    """OI 奖项（NOIP/CSP 年份+等级）。洛谷原字段对应。"""

    __tablename__ = "user_prizes"
    __table_args__ = (
        # 同一用户 + 年 + 比赛 + event + 奖项 视作同一条
        UniqueConstraint("uid", "year", "contest", "event", "prize", name="uq_user_prize"),
        Index("ix_up_uid", "uid"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    contest: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prize: Mapped[str] = mapped_column(String(64), nullable=False)
    # 公开成绩才有；XCPC 的 score 是浮点（赛区 penalty 算法）
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[LuoguUser] = relationship(back_populates="prizes")


class UserEloHistory(Base):
    """月赛 Elo 变化时间序列（非版本快照）。"""

    __tablename__ = "user_elo_history"
    __table_args__ = (
        # 同一用户 + 某场比赛只有一次 Elo 结果
        UniqueConstraint("uid", "contest_id", name="uq_user_elo_contest"),
        Index("ix_ueh_uid_time", "uid", "time"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contest_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contest_name: Mapped[str] = mapped_column(String(256), nullable=False)
    prev_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[LuoguUser] = relationship(back_populates="elo_history")


class UserGuHistory(Base):
    """咕值时间序列。每次抓到变化才插入。"""

    __tablename__ = "user_gu_history"
    __table_args__ = (
        Index("ix_ugh_uid_time", "uid", "time"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    social: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    basic: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contest: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    practice: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prize: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[LuoguUser] = relationship(back_populates="gu_history")


class UserDailyActivity(Base):
    """365 天打卡热图。"""

    __tablename__ = "user_daily_activity"
    __table_args__ = (
        UniqueConstraint("uid", "date", name="uq_uda_uid_date"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[LuoguUser] = relationship(back_populates="daily_activity")


class UserNumericSnapshot(Base):
    """数值字段时间序列（follower / following / ranking / passed_problem_count ...）。

    用 field_name 做分辨器而不是每个字段一张表，方便后续扩展新指标。
    """

    __tablename__ = "user_numeric_snapshots"
    __table_args__ = (
        Index("ix_uns_uid_field_time", "uid", "field_name", "snapped_at"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class UserNameViolation(Base):
    """用户名违规处分记录。

    **命中即不可逆**。triggered_at 之前的所有 name_version 永久 is_hidden=true。
    之后用户若改成合规名，新 version 正常显示；违规历史不解除隐藏。
    """

    __tablename__ = "user_name_violations"
    __table_args__ = (
        Index("ix_unvio_uid_triggered", "uid", "triggered_at"),
    )

    id: Mapped[int] = BigPKColumn()
    uid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luogu_users.uid", ondelete="CASCADE"), nullable=False
    )
    trigger_source: Mapped[NameViolationSource] = mapped_column(
        Enum(NameViolationSource, native_enum=False, length=32),
        nullable=False,
    )
    # 关联引用：陶片 id（整数字符串） / 管理员 id / NULL
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_keywords: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 关键时间戳：此时间之前的 name 永久隐藏
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    user: Mapped[LuoguUser] = relationship(back_populates="name_violations")
