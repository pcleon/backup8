# -*- coding: utf-8 -*-
"""备份任务核心执行器。

通过 SSH 异步连接目标主机，执行数据目录空间确认、智能历史清理、
MySQL 8.0 克隆、进度监控轮询、最大化压缩打包、rsync 限速传输、双重校验及故障状态回滚。
"""

import asyncio
import logging
import os
import re
import traceback
from datetime import datetime
from typing import Optional, Tuple
import asyncssh
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config import settings
from database import AsyncSessionLocal
from models import BackupRecord, HostConfig
from notifier import send_alarm

# 初始化日志记录器
logger = logging.getLogger("backup_executor")
logger.setLevel(logging.INFO)


async def _run_remote_command(conn: asyncssh.SSHClientConnection, cmd: str) -> Tuple[int, str, str]:
    """在 SSH 连接上远程执行命令并返回退出状态码、标准输出和标准错误。

    Args:
        conn (asyncssh.SSHClientConnection): 已建立的 SSH 连接对象。
        cmd (str): 需要执行的 Bash 命令。

    Returns:
        Tuple[int, str, str]: 包含 (exit_status, stdout, stderr) 的元组。
    """
    result = await conn.run(cmd)
    stdout = result.stdout.strip() if result.stdout else ""
    stderr = result.stderr.strip() if result.stderr else ""
    return result.exit_status or 0, stdout, stderr


async def _poll_clone_progress(
    conn: asyncssh.SSHClientConnection,
    record_id: int,
    db_port: int,
    stop_event: asyncio.Event,
    local_log_file: str
):
    """异步循环查询 MySQL 的 performance_schema.clone_progress 以轮询克隆进度。

    Args:
        conn (asyncssh.SSHClientConnection): 用于执行进度查询的 SSH 连接。
        record_id (int): 数据库备份记录 ID，用于写回实时进度。
        db_port (int): 目标数据库的端口。
        stop_event (asyncio.Event): 结束事件信号。当克隆主任务结束时将 set()，以终止此轮询。
        local_log_file: 目标机本地日志文件路径。
    """
    sql_query = (
        f"mysql -u{settings.global_db_user} -p'{settings.global_db_password}' "
        f"-h127.0.0.1 -P{db_port} -s -N -e "
        f"\"SELECT STAGE, STATE, DATA FROM performance_schema.clone_progress ORDER BY BEGIN_TIME DESC LIMIT 1;\""
    )
    
    logger.info(f"[Record {record_id}] 开始监控 MySQL Clone 进度。")
    
    while not stop_event.is_set():
        try:
            code, out, err = await _run_remote_command(conn, sql_query)
            if code == 0 and out:
                # 解析字段，输出格式为: STAGE  STATE  DATA
                parts = out.split("\t")
                stage = parts[0] if len(parts) > 0 else "UNKNOWN"
                state = parts[1] if len(parts) > 1 else "UNKNOWN"
                data = parts[2] if len(parts) > 2 else ""
                
                progress_text = f"CLONE: {stage} ({state})"
                if data:
                    progress_text += f" - {data}"
                
                # 记录到目标机本地日志
                log_cmd = f"echo \"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {progress_text}\" >> {local_log_file}"
                await _run_remote_command(conn, log_cmd)
                
                # 异步同步更新管理库的进程状态
                async with AsyncSessionLocal() as session:
                    stmt = select(BackupRecord).where(BackupRecord.id == record_id)
                    res = await session.execute(stmt)
                    record = res.scalar_one_or_none()
                    if record:
                        record.progress_status = progress_text
                        await session.commit()
            else:
                # 如果没有进度记录，通常克隆尚未启动或没有活动
                log_cmd = f"echo \"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待克隆任务初始化...\" >> {local_log_file}"
                await _run_remote_command(conn, log_cmd)
                
        except Exception as ex:
            logger.error(f"[Record {record_id}] 轮询克隆进度时发生异常: {str(ex)}")
            
        # 每隔 5 秒轮询一次
        await asyncio.sleep(5)
        
    logger.info(f"[Record {record_id}] 停止 MySQL Clone 进度监控。")


async def _verify_zabbix_role(ip: str, host_name: str) -> None:
    """在备份执行前，从该主机前缀关联 of Zabbix 库校验其角色权限。

    根据 host_name.split('-')[0] 获取机房前缀，再匹配 Zabbix DB 连接串。
    获取其在 hosts 表中的 name 字段，提取尾部的 role（如 -L），
    仅当 role 在允许的角色列表中时允许备份，否则拒绝并抛出异常。

    Args:
        ip (str): 目标主机 IP。
        host_name (str): 主机别名（hostname）。

    Raises:
        RuntimeError: 当校验失败时抛出。
    """
    if not settings.enable_zabbix_check:
        logger.info("Zabbix 角色门禁校验已关闭 (ENABLE_ZABBIX_CHECK=False)，自动放行备份流程。")
        return

    if not settings.zabbix_db_urls_dict:
        raise RuntimeError("已启用 Zabbix 角色校验门禁，但在环境变量中未配置任何 ZABBIX_DB_URLS 连接字典。")

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
            # 用户要求的 SQL 结构：
            # select name from hosts where hostid=(select hostid from interface where ip = %s)
            sql = text(
                "SELECT name FROM hosts WHERE hostid = (SELECT hostid FROM interface WHERE ip = :ip LIMIT 1)"
            )
            res = await conn.execute(sql, {"ip": ip})
            row = res.fetchone()

            if not row or not row[0]:
                raise RuntimeError(f"在 Zabbix 数据库中未找到 IP {ip} 对应的主机记录")

            zabbix_name = row[0]
            # 用户逻辑: name.split('-')[-1]
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
        logger.error(f"连接 Zabbix 校验角色时发生错误: {str(ex)}")
        raise RuntimeError(f"Zabbix 角色检验失败: {str(ex)}")
    finally:
        await engine.dispose()


async def run_backup(host_id: int) -> bool:
    """针对单台主机执行完整的备份流程。

    Args:
        host_id (int): 目标主机在数据库中的 ID。

    Returns:
        bool: 备份成功返回 True，失败返回 False。
    """
    # 1. 初始化数据库 Session 并拉取主机配置
    async with AsyncSessionLocal() as session:
        stmt = select(HostConfig).where(HostConfig.id == host_id)
        result = await session.execute(stmt)
        host: Optional[HostConfig] = result.scalar_one_or_none()
        if not host:
            logger.warning(f"主机 ID {host_id} 不存在，拒绝执行备份。")
            return False

        # 创建初始的 BackupRecord，标记为 running 状态
        record = BackupRecord(
            host_id=host.id,
            status="running",
            progress_status="STARTING",
            start_time=datetime.now()
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        
        record_id = record.id
        ip = host.ip
        ssh_port = host.ssh_port
        db_port = host.db_port
        host_name = host.host_name

    logger.info(f"[Host {host_name} ({ip})] 备份任务 {record_id} 开始。")

    # 执行 Zabbix 主机备份角色门禁校验
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(BackupRecord).where(BackupRecord.id == record_id)
            res = await session.execute(stmt)
            rec = res.scalar_one_or_none()
            if rec:
                rec.progress_status = "VERIFYING_ZABBIX_ROLE"
                await session.commit()

        await _verify_zabbix_role(ip, host_name)
    except Exception as gate_ex:
        raise RuntimeError(f"Zabbix 备份门禁拦截: {str(gate_ex)}")

    # 本地路径定义
    backup_dir = settings.global_backup_dir.rstrip("/")
    nfs_dir = settings.global_nfs_dir.rstrip("/")
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    local_log_file = f"{backup_dir}/backup_{timestamp}.log"
    
    # 临时克隆目录与打包名定义
    temp_clone_dir = f"{backup_dir}/temp_clone_{timestamp}"
    temp_tar_file = f"{backup_dir}/temp_{timestamp}.tar.gz"
    final_tar_filename = ""

    conn = None
    stop_poll_event = asyncio.Event()
    poll_task = None
    
    try:
        # 2. 建立异步 SSH 连接
        # 如果指定了私钥文件，检查本地是否存在
        connect_kwargs = {
            "host": ip,
            "port": ssh_port,
            "username": settings.global_ssh_user,
            "known_hosts": None,
            "connect_timeout": 15,                     # 建立连接握手超时为 15 秒
            "keepalive_interval": 10,          # 每隔 10 秒发送一次 Keepalive 探测
            "keepalive_count_max": 3,          # 连续 3 次无心跳回应则断开连接
        }
        if os.path.exists(settings.global_ssh_key_path):
            connect_kwargs["client_keys"] = [settings.global_ssh_key_path]
        else:
            raise FileNotFoundError(f"全局 SSH 私钥文件 {settings.global_ssh_key_path} 不存在。")
            
        logger.info(f"[Record {record_id}] 正在建立 SSH 连接...")
        conn = await asyncssh.connect(**connect_kwargs)
        logger.info(f"[Record {record_id}] SSH 连接建立成功。")
        
        # 创建工作目录并初始化本地日志
        await _run_remote_command(conn, f"sudo mkdir -p {backup_dir} && sudo chown -R {settings.global_ssh_user} {backup_dir}")
        await _run_remote_command(conn, f"echo '=== Backup started at {datetime.now()} ===' > {local_log_file}")

        # 3. 启动前清扫历史残留临时文件 (Pre-flight Cleanup)
        logger.info(f"[Record {record_id}] 执行启动前临时目录清理...")
        cleanup_cmd = f"sudo rm -rf {backup_dir}/temp_clone_* {backup_dir}/temp_*.tar.gz"
        await _run_remote_command(conn, cleanup_cmd)

        # 4. 获取 datadir 并动态估算磁盘空间
        # 从数据库中查询 datadir 配置
        get_datadir_cmd = (
            f"mysql -u{settings.global_db_user} -p'{settings.global_db_password}' "
            f"-h127.0.0.1 -P{db_port} -s -N -e \"SHOW VARIABLES LIKE 'datadir';\""
        )
        code, out, err = await _run_remote_command(conn, get_datadir_cmd)
        if code != 0 or not out:
            raise RuntimeError(f"获取 MySQL 数据目录失败，错误: {err}")
        
        # SHOW VARIABLES LIKE 'datadir' 输出结果形如: datadir  /var/lib/mysql/
        parts = out.split()
        datadir_path = parts[1] if len(parts) > 1 else out.strip()
        logger.info(f"[Record {record_id}] 目标机 MySQL 数据目录: {datadir_path}")

        # 获取数据目录物理大小 D
        code, out, err = await _run_remote_command(conn, f"sudo du -sb {datadir_path}")
        if code != 0 or not out:
            raise RuntimeError(f"估算数据目录物理大小失败: {err}")
        required_bytes = int(out.split()[0])
        required_gb = required_bytes / (1024**3)
        logger.info(f"[Record {record_id}] 估算所需克隆物理空间: {required_gb:.2f} GB")

        # 获取本地备份目录可用空间 F
        code, out, err = await _run_remote_command(conn, f"df -B1 {backup_dir} | tail -n 1")
        if code != 0 or not out:
            raise RuntimeError(f"获取本地备份目录剩余空间失败: {err}")
        # df 最后一行的第四列代表可用字节数
        avail_bytes = int(out.split()[3])
        avail_gb = avail_bytes / (1024**3)
        logger.info(f"[Record {record_id}] 目标机本地可用备份空间: {avail_gb:.2f} GB")

        # 如果可用空间小于物理数据目录大小的 1.2 倍，进行智能清理
        if avail_bytes < required_bytes * 1.2:
            logger.info(f"[Record {record_id}] 空间不足 ({avail_gb:.2f} GB < {required_gb * 1.2:.2f} GB)，开始清理历史备份...")
            async with AsyncSessionLocal() as session:
                record.progress_status = "CLEANING_LOCAL_SPACE"
                await session.commit()

            # 检索本地所有的历史备份压缩包
            # 文件名匹配规则: {ip}_{host_name}_full_*.tar.gz
            find_cmd = f"find {backup_dir}/ -maxdepth 1 -name '{ip}_{host_name}_full_*.tar.gz' -printf '%f\\n'"
            code, out, err = await _run_remote_command(conn, find_cmd)
            if code == 0 and out:
                local_backups = out.strip().split("\n")
                # 按时间戳排序，优先删除最老的备份
                local_backups.sort()
                
                for backup_file in local_backups:
                    # 提取文件名中的 md5，并校验 NFS 中是否存在相同大小和 md5 的文件
                    # 文件命名: {ip}_{host_name}_full_{timestamp}.{md5}.tar.gz
                    match = re.search(r"_full_\d{12,14}\.([a-f0-9]{32})\.tar\.gz", backup_file)
                    if not match:
                        continue
                    expected_md5 = match.group(1)
                    
                    # 检查 NFS 中对应的文件是否存在，且大小相同
                    nfs_file_path = f"{nfs_dir}/{backup_file}"
                    check_nfs_cmd = (
                        f"[ -f {nfs_file_path} ] && "
                        f"stat -c%s {backup_dir}/{backup_file} && "
                        f"stat -c%s {nfs_file_path} && "
                        f"md5sum {nfs_file_path}"
                    )
                    nfs_code, nfs_out, nfs_err = await _run_remote_command(conn, check_nfs_cmd)
                    
                    if nfs_code == 0 and nfs_out:
                        # 检查输出中两处大小以及 md5 校验
                        lines = nfs_out.strip().split("\n")
                        if len(lines) >= 3:
                            local_size = lines[0].strip()
                            nfs_size = lines[1].strip()
                            calculated_md5 = lines[2].split()[0].strip()
                            
                            if local_size == nfs_size and calculated_md5 == expected_md5:
                                # 已确认成功上传至 NFS，安全删除本地历史备份以释放空间
                                logger.info(f"[Record {record_id}] 已在 NFS 确认文件，正在清理本地备份: {backup_file}")
                                await _run_remote_command(conn, f"sudo rm -f {backup_dir}/{backup_file}")
                                
                                # 重新检测空间
                                _, new_out, _ = await _run_remote_command(conn, f"df -B1 {backup_dir} | tail -n 1")
                                avail_bytes = int(new_out.split()[3])
                                avail_gb = avail_bytes / (1024**3)
                                logger.info(f"[Record {record_id}] 清理后目标机本地可用备份空间: {avail_gb:.2f} GB")
                                
                                if avail_bytes >= required_bytes * 1.2:
                                    logger.info(f"[Record {record_id}] 空间已足够，停止清理历史备份。")
                                    break
            
            # 若清理完毕后空间仍然不足，退出备份
            if avail_bytes < required_bytes * 1.2:
                raise RuntimeError(
                    f"目标主机本地备份目录空间不足。所需: {required_gb * 1.2:.2f} GB，可用: {avail_gb:.2f} GB，且无可清理的历史备份。"
                )

        # 5. 执行 MySQL Clone
        logger.info(f"[Record {record_id}] 空间验证通过。启动在线物理克隆...")
        async with AsyncSessionLocal() as session:
            record.progress_status = "CLONE: STARTING"
            await session.commit()

        # 启动后台异步监控克隆进度
        poll_task = asyncio.create_task(
            _poll_clone_progress(conn, record_id, db_port, stop_poll_event, local_log_file)
        )

        clone_sql = (
            f"mysql -u{settings.global_db_user} -p'{settings.global_db_password}' "
            f"-h127.0.0.1 -P{db_port} -e \"CLONE LOCAL DATA DIRECTORY = '{temp_clone_dir}';\""
        )
        clone_code, clone_out, clone_err = await _run_remote_command(conn, clone_sql)
        
        # 停止克隆进度轮询并等待其结束
        stop_poll_event.set()
        if poll_task:
            await poll_task

        if clone_code != 0:
            raise RuntimeError(f"MySQL 本地克隆命令失败: {clone_err or clone_out}")
            
        logger.info(f"[Record {record_id}] MySQL 本地物理克隆完成。")

        # 6. 打包压缩、计算 MD5 并重命名
        logger.info(f"[Record {record_id}] 开始进行物理克隆目录最大化打包压缩...")
        async with AsyncSessionLocal() as session:
            stmt = select(BackupRecord).where(BackupRecord.id == record_id)
            res = await session.execute(stmt)
            rec = res.scalar_one_or_none()
            if rec:
                rec.progress_status = "COMPRESSING"
                await session.commit()

        # 最大化压缩目录成 .tar.gz (使用 gzip 压缩等级 9 或默认最大压缩)
        tar_cmd = f"tar -czf {temp_tar_file} -C {backup_dir} temp_clone_{timestamp} >> {local_log_file} 2>&1"
        tar_code, _, tar_err = await _run_remote_command(conn, tar_cmd)
        if tar_code != 0:
            raise RuntimeError(f"打包克隆目录失败: {tar_err}")

        # 彻底清除临时物理克隆源目录
        logger.info(f"[Record {record_id}] 压缩打包完成，清理未压缩克隆目录...")
        await _run_remote_command(conn, f"sudo rm -rf {temp_clone_dir}")

        # 计算生成的压缩包 MD5
        code, out, err = await _run_remote_command(conn, f"md5sum {temp_tar_file}")
        if code != 0 or not out:
            raise RuntimeError(f"计算压缩包 MD5 失败: {err}")
        md5_val = out.split()[0].strip()
        logger.info(f"[Record {record_id}] 压缩包 MD5 校验值: {md5_val}")

        # 重命名压缩包：{ip}_{host_name}_full_{timestamp}.{md5}.tar.gz
        final_tar_filename = f"{ip}_{host_name}_full_{timestamp}.{md5_val}.tar.gz"
        final_tar_path = f"{backup_dir}/{final_tar_filename}"
        await _run_remote_command(conn, f"mv {temp_tar_file} {final_tar_path}")

        # 获取打包后文件大小
        code, out, err = await _run_remote_command(conn, f"stat -c%s {final_tar_path}")
        if code != 0 or not out:
            raise RuntimeError(f"获取压缩包大小失败: {err}")
        file_size = int(out.strip())
        logger.info(f"[Record {record_id}] 压缩打包大小: {file_size / (1024**2):.2f} MB")

        # 7. rsync 限速同步至 NFS
        logger.info(f"[Record {record_id}] 启动 rsync 同步到 NFS 存储...")
        async with AsyncSessionLocal() as session:
            stmt = select(BackupRecord).where(BackupRecord.id == record_id)
            res = await session.execute(stmt)
            rec = res.scalar_one_or_none()
            if rec:
                rec.progress_status = "RSYNCING"
                await session.commit()

        # 创建 NFS 目录以防不存在
        await _run_remote_command(conn, f"sudo mkdir -p {nfs_dir} && sudo chown -R {settings.global_ssh_user} {nfs_dir}")

        # 执行 rsync 并限制速度
        rsync_cmd = (
            f"rsync -av --bwlimit={settings.global_rsync_bwlimit} "
            f"{final_tar_path} {nfs_dir}/ >> {local_log_file} 2>&1"
        )
        rsync_code, _, rsync_err = await _run_remote_command(conn, rsync_cmd)
        if rsync_code != 0:
            raise RuntimeError(f"rsync 同步至 NFS 失败: {rsync_err}")

        # 8. 双重数据一致性校验
        logger.info(f"[Record {record_id}] 进行 NFS 传输数据双重一致性校验...")
        nfs_file_path = f"{nfs_dir}/{final_tar_filename}"
        code, out, err = await _run_remote_command(conn, f"stat -c%s {nfs_file_path}")
        if code != 0 or not out:
            raise RuntimeError(f"校验 NFS 备份文件大小失败: {err}")
        nfs_file_size = int(out.strip())

        if file_size != nfs_file_size:
            raise RuntimeError(
                f"NFS 数据一致性校验失败：本地文件大小 {file_size} 与 NFS 大小 {nfs_file_size} 不一致。"
            )
            
        logger.info(f"[Record {record_id}] 数据一致性校验通过。记录本地及 NFS 数据完整。")
        await _run_remote_command(conn, f"echo '=== Backup completed successfully at {datetime.now()} ===' >> {local_log_file}")

        # 9. 更新数据库为成功状态
        async with AsyncSessionLocal() as session:
            stmt = select(BackupRecord).where(BackupRecord.id == record_id)
            res = await session.execute(stmt)
            rec = res.scalar_one_or_none()
            if rec:
                rec.status = "success"
                rec.progress_status = "COMPLETED"
                rec.end_time = datetime.now()
                rec.backup_file = final_tar_filename
                rec.file_size_bytes = file_size
                await session.commit()
                
        logger.info(f"[Host {host_name} ({ip})] 备份成功！")
        return True

    except Exception as e:
        # 异常捕获与故障写入记录
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"[Host {host_name} ({ip})] 备份过程中遇到严重异常: {error_msg}")
        
        # 停止进度轮询
        stop_poll_event.set()
        if poll_task:
            await poll_task

        async with AsyncSessionLocal() as session:
            stmt = select(BackupRecord).where(BackupRecord.id == record_id)
            res = await session.execute(stmt)
            rec = res.scalar_one_or_none()
            if rec:
                rec.status = "failed"
                rec.progress_status = "FAILED"
                rec.end_time = datetime.now()
                rec.error_message = error_msg
                await session.commit()

        # 触发即时报警发送，在后台独立协程运行，捕获异常以防阻碍后续的清理流程
        if settings.alarm_script_path:
            title = f"MySQL 备份失败告警: 主机 {host_name}"
            brief_error = str(e).split("\n")[0]
            content = f"主机 IP: {ip}\n主机别名: {host_name}\n错误描述: {brief_error}\n\n详细故障堆栈:\n{error_msg}"
            asyncio.create_task(send_alarm(ip=ip, title=title, content=content))

        # 10. 故障本地垃圾清理 (On-Failure Cleanup)
        if conn:
            try:
                logger.info(f"[Record {record_id}] 正在清理中途失败产生的临时垃圾文件...")
                cleanup_cmd = f"sudo rm -rf {temp_clone_dir} {temp_tar_file}"
                await _run_remote_command(conn, cleanup_cmd)
                await _run_remote_command(conn, f"echo '=== Backup failed at {datetime.now()} ===' >> {local_log_file}")
            except Exception as cleanup_ex:
                logger.error(f"[Record {record_id}] 清理临时垃圾文件时失败: {str(cleanup_ex)}")

        return False

    finally:
        # 关闭 SSH 连接
        if conn:
            conn.close()
            await conn.wait_closed()
            logger.info(f"[Record {record_id}] SSH 连接已安全关闭。")
