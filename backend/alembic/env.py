"""Alembic 迁移运行时入口。

和默认模板相比做了两件事：
1. 从 app.core.config 读同步数据库连接串（不在 alembic.ini 硬编码）
2. 从 app.models 导入所有模型，让 autogenerate 能探测到所有表
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 导入应用配置（注意：此文件执行时必须能 import app 包）
from app.core.config import settings

# 触发所有模型加载，Base.metadata 才完整
from app.core.db import Base
from app import models  # noqa: F401  —— 不用它，但必须 import 让 Base 知道所有表

config = context.config
# 动态注入连接串
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """生成 SQL 文件，不实际执行。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
