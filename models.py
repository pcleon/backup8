# -*- coding: utf-8 -*-
"""数据库 ORM 模型定义模块。

基于 SQLAlchemy 2.0 定义主机配置表 (HostConfig) 与备份历史记录表 (BackupRecord)，
并建立相应的索引和外键关联关系。
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import ForeignKey, String, Integer, Boolean, DateTime, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database import Base


class HostConfig(Base):
    """主机配置信息模型类。

    存储各被备份的目标主机及数据库连接属性。
    """
    __tablename__ = "host_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    host_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="主机别名")
    ip: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="目标主机 IP")
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22, comment="SSH 端口")
    db_port: Mapped[int] = mapped_column(Integer, nullable=False, default=3306, comment="目标数据库端口")
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False, default="0 2 * * *", comment="自动备份 Cron 表达式")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用定时备份任务")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系定义：与 BackupRecord 建立一对多关联
    # 启用级联删除，当主机被删除时，其关联的备份历史记录一并删除
    records: Mapped[List["BackupRecord"]] = relationship(
        "BackupRecord",
        back_populates="host",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BackupRecord(Base):
    """备份任务历史与状态记录模型类。

    存储每一次备份任务的执行历史、状态、实时进度、生成的文件及错误堆栈。
    """
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    
    # 显式声明外键，并加上 index=True 保证高频查询性能，加上 ondelete="CASCADE" 保证删除主机时级联删除
    host_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("host_configs.id", ondelete="CASCADE"), nullable=False, index=True, comment="关联主机ID"
    )
    
    # 状态：running (进行中), success (成功), failed (失败)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True, comment="备份状态")
    
    # 实时进度描述：例如 CLONE: FILE COPY (45%) 或 COMPRESSING 或 RSYNCING
    progress_status: Mapped[str] = mapped_column(String(200), nullable=True, comment="当前备份的实时步骤进度")
    
    start_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="备份开始时间"
    )
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="备份结束时间")
    
    # 备份生成的文件名：形如 {ip}_{hostname}_full_{timestamp}.{md5}.tar.gz
    backup_file: Mapped[str] = mapped_column(String(255), nullable=True, comment="最终生成的备份文件名")
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=True, comment="备份文件大小(字节)")
    
    # 失败时的具体错误日志或异常信息
    error_message: Mapped[str] = mapped_column(Text, nullable=True, comment="故障错误信息")
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="日志记录时间"
    )

    # 关系定义：反向关联 HostConfig
    host: Mapped["HostConfig"] = relationship("HostConfig", back_populates="records")
