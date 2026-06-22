# -*- coding: utf-8 -*-
"""自动备份系统全局配置模块。

从环境变量或 .env 文件中读取管理数据库 URL、SSH 凭证、数据库 Clone 凭证以及 rsync 限速等配置。
"""

import json
import os
from cryptography.fernet import Fernet
from pydantic import model_validator
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

    # 邮件告警 Python 脚本路径 (空表示禁用邮件发送)
    alarm_script_path: str = ""
    # 每日异常汇总发送时间 Cron 表达式 (默认每天晚上 23:30)
    email_send_cron: str = "30 23 * * *"

    # 敏感参数解密密钥 (32 字节 Base64 编码的 Fernet 密钥，为空则保持明文)
    encryption_key: str = ""

    @model_validator(mode="after")
    def decrypt_sensitive_configs(self) -> "Settings":
        """若配置了对称密钥，在加载后自动对敏感配置项进行解密。

        如果解密失败（可能是明文或密码错误），回退使用原值，确保向下兼容。

        Returns:
            Settings: 配置实例本身。
        """
        key = self.encryption_key.strip().strip("'\"")
        if not key:
            return self

        try:
            f = Fernet(key.strip().encode())

            def decrypt_field(val: str) -> str:
                if not val:
                    return val
                try:
                    return f.decrypt(val.strip().encode()).decode()
                except Exception:
                    # 解密失败，返回原值以兼容明文
                    return val

            self.global_ssh_user = decrypt_field(self.global_ssh_user)
            self.global_db_user = decrypt_field(self.global_db_user)
            self.global_db_password = decrypt_field(self.global_db_password)
            self.management_db_url = decrypt_field(self.management_db_url)
        except Exception:
            # 密钥格式不正确等引起 Fernet 实例化失败时，容错跳过，保留原值
            pass
        return self

    # 多机房 Zabbix 数据库连接映射 (JSON 字符串，格式如 {"bj": "mysql+aiomysql://...", "sh": "mysql+aiomysql://..."})
    zabbix_db_urls: str = "{}"

    @property
    def zabbix_db_urls_dict(self) -> dict:
        """安全解析多机房 Zabbix DB 映射。

        Returns:
            dict: 前缀与数据库URL的字典映射。
        """
        if not self.zabbix_db_urls:
            return {}
        try:
            return json.loads(self.zabbix_db_urls)
        except Exception:
            return {}

    # 配置文件读取选项
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# 实例化全局配置对象
settings = Settings()
