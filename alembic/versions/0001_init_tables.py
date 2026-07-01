# -*- coding: utf-8 -*-
"""初始化自动备份系统数据库表。

Revision ID: 0001
Revises: None
Create Date: 2026-06-22 14:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# 迁移修订标识
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """执行数据库升级，创建 host_configs 与 backup_records 表及索引。"""
    # 1. 创建 host_configs 表
    op.create_table(
        "host_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("host_name", sa.String(length=100), nullable=False, comment="主机别名"),
        sa.Column("ip", sa.String(length=50), nullable=False, comment="目标主机 IP"),
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22", comment="SSH 端口"),
        sa.Column("db_port", sa.Integer(), nullable=False, server_default="3306", comment="目标数据库端口"),
        sa.Column("cron_expression", sa.String(length=100), nullable=False, server_default="0 2 * * *", comment="自动备份 Cron 表达式"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1", comment="是否启用定时备份任务"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_name")
    )
    # 为 host_configs.ip 创建高频查询索引
    op.create_index(op.f("ix_host_configs_ip"), "host_configs", ["ip"], unique=False)

    # 2. 创建 backup_records 表
    op.create_table(
        "backup_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("host_id", sa.Integer(), nullable=False, comment="关联主机ID"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running", comment="备份状态"),
        sa.Column("progress_status", sa.String(length=200), nullable=True, comment="实时进度状态 (WAITING_FOR_AGENT, PULLED_BY_AGENT, INITIALIZING, CLONE: RUNNING, COMPRESSING, RSYNCING, COMPLETED, FAILED, ZABBIX_ROLE_REJECTED, CANCELED_DUPLICATE, TIMEOUT_ZOMBIE, ABORTED, ABORTED_BY_NEW_MANUAL_TRIGGER)"),
        sa.Column("start_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="备份开始时间"),
        sa.Column("end_time", sa.DateTime(), nullable=True, comment="备份结束时间"),
        sa.Column("backup_file", sa.String(length=255), nullable=True, comment="最终生成的备份文件名"),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True, comment="备份文件大小(字节)"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="故障错误信息"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="日志记录时间"),
        # 关联外键约束并支持级联删除
        sa.ForeignKeyConstraint(["host_id"], ["host_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id")
    )
    # 为 backup_records.host_id 与 backup_records.status 创建高频查询索引
    op.create_index(op.f("ix_backup_records_host_id"), "backup_records", ["host_id"], unique=False)
    op.create_index(op.f("ix_backup_records_status"), "backup_records", ["status"], unique=False)


def downgrade() -> None:
    """回滚数据库迁移，安全删除表结构。

    > [!WARNING]
    > 降级数据库时将删除整个 backup_records 表和 host_configs 表，
    > 这将导致所有的主机配置和备份日志被永久删除，请在降级前备份好元数据。
    """
    # 先删除具有外键依赖的 backup_records 表的索引和表本身
    op.drop_index(op.f("ix_backup_records_status"), table_name="backup_records")
    op.drop_index(op.f("ix_backup_records_host_id"), table_name="backup_records")
    op.drop_table("backup_records")

    # 再删除主表 host_configs 的索引和表本身
    op.drop_index(op.f("ix_host_configs_ip"), table_name="host_configs")
    op.drop_table("host_configs")
