# -*- coding: utf-8 -*-
"""Alembic 数据库迁移环境配置模块。

配置 Alembic 如何加载 ORM 模型的元数据 (metadata) 并利用异步 SQLAlchemy 引擎执行数据库迁移。
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 将项目根目录添加到 sys.path，保证 config 与 models 模块正常导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from models import Base

# 获取 Alembic 配置对象
config = context.config

# 配置日志记录器
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 注册 ORM 模型的元数据，用于支持自动生成迁移脚本 (autogenerate)
target_metadata = Base.metadata

# 从全局设置中动态读取数据库连接配置，避免在 alembic.ini 中硬编码敏感凭证
config.set_main_option("sqlalchemy.url", settings.management_db_url)


def run_migrations_offline() -> None:
    """在“离线模式”下运行迁移。

    这会在没有数据库连接的情况下运行迁移，生成迁移 SQL 脚本输出。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在已连接的同步上下文事务中真正运行迁移。

    Args:
        connection (Connection): 数据库同步连接。
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在“在线模式”下运行迁移。

    创建异步引擎连接数据库，并利用 run_sync 在同步上下文中执行迁移操作。
    """
    # 从 ini 选项中读取配置字典
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # 使用 run_sync 方法在同步运行环境中调用迁移
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    # 异步模式下调用协程运行
    asyncio.run(run_migrations_online())
