# -*- coding: utf-8 -*-
"""一键自动部署 Agent 模块。

利用高权限 SSH 通道向目标机器投递并安装 Agent。
"""

import os
import io
import logging
import asyncssh
from typing import Optional

from config import settings

logger = logging.getLogger("deploy_agent")
logger.setLevel(logging.INFO)

async def deploy_agent_to_host(ip: str, ssh_port: int, host_name: str, api_base: str = "http://127.0.0.1:8000") -> None:
    """自动化下发并部署 Agent 到目标机器。
    
    1. 检查本地 dist/backup-agent 和 backup-agent.service 是否存在
    2. SSH 连入目标机器
    3. 创建目录 /opt/backup-agent
    4. sftp 上传 backup-agent
    5. 生成并上传 .env
    6. sftp 上传 backup-agent.service 到 /etc/systemd/system/
    7. chmod +x
    8. systemctl daemon-reload && systemctl enable --now backup-agent
    """
    
    # 1. 检查本地源码与模板
    local_src = os.path.join("agent", "agent_main.py")
    local_svc = os.path.join("agent", "backup-agent.service")
    
    if not os.path.isfile(local_src):
        raise RuntimeError("未在管理端找到 Agent 源码文件 (agent/agent_main.py)。")
    if not os.path.isfile(local_svc):
        raise RuntimeError("未找到 systemd 模板文件 (agent/backup-agent.service)。")
        
    ssh_user = settings.global_ssh_user
    ssh_key = settings.global_ssh_key_path
    
    logger.info(f"开始向目标机器 {ip}:{ssh_port} 部署 Agent...")
    
    try:
        async with asyncssh.connect(
            ip,
            port=ssh_port,
            username=ssh_user,
            client_keys=[ssh_key],
            known_hosts=None
        ) as conn:
            
            # 2. 创建目录
            logger.info("创建目标目录 /opt/backup-agent...")
            result = await conn.run('sudo mkdir -p /opt/backup-agent && sudo chown -R $USER /opt/backup-agent')
            if result.exit_status != 0:
                raise RuntimeError(f"创建目标目录失败: {result.stderr}")
                
            # 3. SFTP 投递
            logger.info("通过 SFTP 上传 backup-agent 与 .env...")
            async with conn.start_sftp_client() as sftp:
                # 投递纯 Python 脚本，并在内存中植入执行头
                with open(local_src, 'r', encoding='utf-8') as src_file:
                    script_content = "#!/usr/bin/env python3\n" + src_file.read()
                
                async with sftp.open('/opt/backup-agent/backup-agent', 'w') as f:
                    await f.write(script_content)
                
                # 投递 systemd 服务模板（由于纯静态模板架构，不再进行字符串替换）
                with open(local_svc, 'r', encoding='utf-8') as svc_file:
                    svc_content = svc_file.read()
                
                async with sftp.open('/opt/backup-agent/backup-agent.service', 'w') as f:
                    await f.write(svc_content)
                
            # 4. 执行安装和权限配置
            logger.info("应用执行权限并拉起 Systemd 服务...")
            
            # 注意: 如果 global_ssh_user 不是 root，则此处依赖免密 sudo
            setup_cmd = (
                "sudo chmod +x /opt/backup-agent/backup-agent && "
                "sudo cp /opt/backup-agent/backup-agent.service /etc/systemd/system/ && "
                "sudo systemctl daemon-reload && "
                "sudo systemctl enable --now backup-agent.service && "
                "sudo systemctl restart backup-agent.service"
            )
            
            setup_res = await conn.run(setup_cmd)
            if setup_res.exit_status != 0:
                raise RuntimeError(f"安装及拉起 systemd 服务失败: {setup_res.stderr}")
                
            logger.info(f"目标机 {host_name} ({ip}) Agent 部署成功！")
            
    except asyncssh.Error as e:
        logger.error(f"SSH 传输或连接发生错误: {str(e)}")
        raise RuntimeError(f"SSH 部署失败 (认证失败或网络不可达): {str(e)}")
    except Exception as e:
        logger.error(f"部署过程中发生意外错误: {str(e)}")
        raise RuntimeError(f"部署异常: {str(e)}")
