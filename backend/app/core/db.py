"""MySQL 连接与 Session 管理。

设计要点：
- 异步引擎（aiomysql）用于 FastAPI + 爬虫任务
- 同步引擎仅给 Alembic 迁移用
- 用 `async_scoped_session` 避免在并发请求里共享 session
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# ---------- 异步引擎 ----------
engine = create_async_engine(
    settings.async_database_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,           # 断线自动重连
    pool_recycle=3600,            # 1 小时回收，防 MySQL wait_timeout 断连
    echo=False,                   # 改 True 查 SQL
    future=True,
)

# session 工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,       # 提交后对象仍可访问属性
    autoflush=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


# ---------- Session 依赖 ----------
async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用。每个请求一个独立 session，退出自动关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        # commit 由业务代码显式调用，避免隐式提交


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """在非 HTTP 场景（如队列任务、定时任务）里使用。

    用法：
        async with db_session() as session:
            session.add(obj)
            await session.commit()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
