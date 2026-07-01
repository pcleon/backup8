# -*- coding: utf-8 -*-
"""Pydantic 数据模式校验与序列化模块。

定义 API 交互所需的数据输入校验和输出序列化结构。
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
# ... (其余类保持不变)


class HostConfigBase(BaseModel):
    """主机配置基础模式。"""

    host_name: str = Field(..., max_length=100, description="主机别名")
    ip: str = Field(..., max_length=50, description="目标主机 IP 地址")
    ssh_port: int = Field(22, ge=1, le=65535, description="SSH 连接端口")
    db_port: int = Field(3306, ge=1, le=65535, description="数据库克隆端口")
    cron_expression: str = Field("0 2 * * *", max_length=100, description="备份触发 Cron 表达式")
    is_active: bool = Field(True, description="是否启用自动备份任务")
    direct_nfs: bool = Field(False, description="是否启用直写 NFS 模式")
    mysql_path: str = Field("/data/3306/mysql/bin/mysql", max_length=255, description="MySQL可执行文件路径")


class HostConfigCreate(HostConfigBase):
    """创建主机配置时的输入模式。"""
    host_name: str = Field("", max_length=100, description="主机别名，若留空则自动连接SSH抓取")


class HostConfigUpdate(BaseModel):
    """更新主机配置时的输入模式。"""

    host_name: Optional[str] = Field(None, max_length=100, description="主机别名")
    ip: Optional[str] = Field(None, max_length=50, description="目标主机 IP")
    ssh_port: Optional[int] = Field(None, ge=1, le=65535, description="SSH 端口")
    db_port: Optional[int] = Field(None, ge=1, le=65535, description="数据库端口")
    cron_expression: Optional[str] = Field(None, max_length=100, description="Cron 表达式")
    is_active: Optional[bool] = Field(None, description="是否启用")
    direct_nfs: Optional[bool] = Field(None, description="是否启用直写 NFS 模式")
    mysql_path: Optional[str] = Field(None, max_length=255, description="MySQL可执行文件路径")


class BackupRecordResponse(BaseModel):
    """备份历史记录的响应模式。"""

    id: int
    host_id: int
    status: str
    progress_status: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    backup_file: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HostConfigResponse(HostConfigBase):
    """主机配置的响应模式，附带数据库主键和时间戳。"""

    id: int
    last_heartbeat: Optional[datetime] = None
    agent_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # 最近一次备份记录，用于仪表盘直接展示当前状态
    latest_record: Optional[BackupRecordResponse] = None

    model_config = ConfigDict(from_attributes=True)


class HostConfigBatchCreate(BaseModel):
    """批量创建主机配置时的输入模式。"""

    ips: List[str] = Field(..., description="目标主机 IP 列表")
    ssh_port: int = Field(22, ge=1, le=65535, description="SSH 连接端口")
    db_port: int = Field(3306, ge=1, le=65535, description="数据库克隆端口")
    cron_expression: str = Field("0 2 * * *", max_length=100, description="备份触发 Cron 表达式")
    is_active: bool = Field(True, description="是否启用自动备份任务")
    direct_nfs: bool = Field(False, description="是否启用直写 NFS 模式")
    mysql_path: str = Field("/data/3306/mysql/bin/mysql", max_length=255, description="MySQL可执行文件路径")


class AgentTaskResponse(BaseModel):
    """Agent 拉取任务时的响应模式。"""
    record_id: int
    db_port: int
    db_user_enc: str = Field(..., description="加密后的 MySQL 用户名")
    db_pass_enc: str = Field(..., description="加密后的 MySQL 密码")
    backup_dir: str
    nfs_dir: str
    rsync_bwlimit: int
    direct_nfs: bool
    mysql_path: str


class AgentReportRequest(BaseModel):
    """Agent 上报进度的请求模式。"""
    agent_version: Optional[str] = None
    status: Optional[str] = None
    progress_status: Optional[str] = None
    backup_file: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error_message: Optional[str] = None


class TemplateUpdateRequest(BaseModel):
    """全局模板更新的请求模式。"""
    content: str = Field(..., description="模板配置文件内容")


