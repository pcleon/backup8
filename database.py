# -*- coding: utf-8 -*-
"""数据库基础配置模块。

提供异步 SQLAlchemy Engine、Session 制造器以及数据库连接依赖。
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings

# 创建异步数据库引擎
# 使用 pool_pre_ping=True 自动检测断开的连接，防止交互期间连接失效
# pool_size 和 max_overflow 设置合理的连接数，以支持多主机并发
async_engine = create_async_engine(
    settings.management_db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
)

# 创建异步 Session 工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式模型基类。"""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库 Session 的生成器。

    Yields:
        AsyncSession: 异步数据库 Session 对象，并在使用完毕后自动关闭。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
