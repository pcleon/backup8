# -*- coding: utf-8 -*-
"""自动备份系统全局配置模块。

从环境变量或 .env 文件中读取管理数据库 URL、SSH 凭证、数据库 Clone 凭证以及 rsync 限速等配置。
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """系统全局配置类。

    使用 Pydantic BaseSettings 自动从环境变量或 .env 文件中加载配置项。
    """

    # 管理数据库连接 URL (使用 SQLAlchemy 异步驱动，如 mysql+aiomysql://user:pass@host:port/dbname)
    management_db_url: str = "mysql+aiomysql://root:root@localhost:3306/auto_backup"

    # 全局 SSH 配置
    global_ssh_user: str = "backup_user"
    global_ssh_key_path: str = "/home/leon/.ssh/id_rsa"

    # 全局目标 MySQL 克隆配置
    global_db_user: str = "clone_user"
    global_db_password: str = "clone_password"

    # 路径配置 (根据用户反馈固定)
    global_backup_dir: str = "/data/3306/mybackup/my3306/clone/"
    global_nfs_dir: str = "/data/3306/mybackup/gfs/clone/"

    # 全局 rsync 速度限制，单位为 KB/s (5120 即 5MB/s，10240 即 10MB/s)
    global_rsync_bwlimit: int = 10240

    # 配置文件读取选项
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# 实例化全局配置对象
settings = Settings()
