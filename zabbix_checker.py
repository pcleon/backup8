# -*- coding: utf-8 -*-
"""Zabbix 角色验证门禁系统。

用于在中心调度端发起备份前，拦截非备库机器的物理克隆请求。
"""

import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import settings

logger = logging.getLogger("zabbix_checker")
logger.setLevel(logging.INFO)


async def verify_zabbix_role(ip: str, host_name: str) -> None:
    """在下发备份任务前，从该主机前缀关联的 Zabbix 库中校验其角色权限。

    根据 host_name.split('-')[0] 获取机房前缀，再匹配 Zabbix DB 连接串。
    获取其在 hosts 表中的 name 字段，提取尾部的 role（如 -L），
    仅当 role 在允许的角色列表中时允许备份，否则拒绝并抛出异常。

    Args:
        ip (str): 目标主机 IP。
        host_name (str): 主机别名（hostname）。

    Raises:
        RuntimeError: 当校验失败或非备库角色时抛出。
    """
    if not settings.enable_zabbix_check:
        logger.info("Zabbix 角色门禁校验已关闭 (ENABLE_ZABBIX_CHECK=False)，自动放行。")
        return

    if not settings.zabbix_db_urls_dict:
        raise RuntimeError("已启用 Zabbix 角色校验门禁，但在环境变量中未配置任何 ZABBIX_DB_URLS。")

    prefix = host_name.split("-")[0].strip()
    db_url = settings.zabbix_db_urls_dict.get(prefix)
    if not db_url:
        raise RuntimeError(f"未在 Zabbix 连接配置中找到该机房前缀 '{prefix}' 对应的数据库地址")

    logger.info(f"开始通过机房前缀 {prefix} 的 Zabbix 数据库校验 IP {ip} 的角色权限...")

    # 异步建立目标 Zabbix 库的连接引擎，配置5秒连接超时防止网络不可达时无限卡死
    connect_args = {"connect_timeout": 5}

    engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
    try:
        async with engine.connect() as conn:
            sql = text(
                "SELECT name FROM hosts WHERE hostid = (SELECT hostid FROM interface WHERE ip = :ip LIMIT 1)"
            )
            res = await conn.execute(sql, {"ip": ip})
            row = res.fetchone()

            if not row or not row[0]:
                raise RuntimeError(f"在 Zabbix 数据库中未找到 IP {ip} 对应的主机记录")

            zabbix_name = row[0]
            role = zabbix_name.split("-")[-1].strip()

            allowed_roles = settings.zabbix_allowed_roles_list
            if not allowed_roles:
                raise RuntimeError("Zabbix 允许的角色列表配置为空，出于安全考量拦截所有主机备份。")

            if role not in allowed_roles:
                raise RuntimeError(
                    f"主机 Zabbix 角色校验拒绝。当前主机在 Zabbix 中的名称为 '{zabbix_name}'，"
                    f"解析角色为 '{role}'，不在允许的备份角色列表 {allowed_roles} 中。"
                )

            logger.info(f"主机 Zabbix 角色校验通过：主机 {zabbix_name}，角色 {role} 允许备份。")
    except Exception as ex:
        # 如果本身就是我们自己抛出的 RuntimeError，保持原样抛出
        if isinstance(ex, RuntimeError):
            raise ex
            
        logger.error(f"连接 Zabbix 校验角色时发生错误: {str(ex)}")
        raise RuntimeError(f"Zabbix 角色检验失败（网络或SQL异常）: {str(ex)}")
    finally:
        await engine.dispose()
