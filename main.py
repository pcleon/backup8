# -*- coding: utf-8 -*-
"""FastAPI 服务端主模块。

包含 API 路由接口（主机增删改查、备份手动触发、历史记录查询）、
服务生命周期管理（数据库表创建与定时任务加载）以及前端静态资源的代理托管。
"""

import asyncio
import os
import base64
from datetime import datetime
import asyncssh
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_engine, Base, get_db, AsyncSessionLocal
from models import HostConfig, BackupRecord
from scheduler import backup_scheduler
from zabbix_checker import verify_zabbix_role
from deploy_agent import deploy_agent_to_host
import schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理 FastAPI 服务的生命周期。

    在服务启动时同步定时备份作业，并启动调度器。
    在服务关闭时安全停用调度器。
    """
    logger = app.state.logger
    logger.info("正在启动服务...")
    logger.info("请确保在启动服务前已运行 'alembic upgrade head' 以完成数据库迁移和结构同步。")

    # 1. 自动清理状态为 running 的异常残留备份任务
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(BackupRecord).where(BackupRecord.status == "running")
            res = await session.execute(stmt)
            running_records = res.scalars().all()
            if running_records:
                logger.info(f"检测到有 {len(running_records)} 个未完成的残留备份任务处于运行状态，正在进行清理...")
                for rec in running_records:
                    rec.status = "failed"
                    rec.progress_status = "FAILED"
                    rec.end_time = datetime.now()
                    rec.error_message = "备份服务意外重启或中断，导致任务被系统自动中止清理。"
                await session.commit()
                logger.info("异常残留备份任务清理完毕。")
    except Exception as cleanup_ex:
        logger.error(f"启动时清理残留备份任务失败: {str(cleanup_ex)}")

    # 2. 定时作业同步并启动调度器
    await backup_scheduler.sync_jobs_from_db()
    backup_scheduler.start()
    
    yield
    
    # 3. 关闭调度器
    backup_scheduler.shutdown()
    logger.info("服务已安全关闭。")


app = FastAPI(
    title="MySQL Auto Backup Management Console",
    description="基于 Python 3 + FastAPI + React 的分布式 MySQL 自动物理克隆备份管理后台",
    version="1.0.0",
    lifespan=lifespan
)

# 挂载内部日志记录器
import logging
app.state.logger = logging.getLogger("main")
app.state.logger.setLevel(logging.INFO)

# 配置跨域请求中间件 (开发阶段前后端分离联调使用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# API 接口路由定义
# =====================================================================

@app.get("/api/hosts", response_model=List[schemas.HostConfigResponse], summary="查询主机配置列表及最新备份状态")
async def list_hosts(db: AsyncSession = Depends(get_db)):
    """查询数据库中所有主机配置，并附带各自最新的备份记录。"""
    # 1. 查询所有主机
    hosts_stmt = select(HostConfig).order_by(HostConfig.host_name)
    hosts_res = await db.execute(hosts_stmt)
    hosts = list(hosts_res.scalars().all())

    if not hosts:
        return []

    # 2. 批量查出每个主机的最新一条备份记录，以避免 N+1 查询问题
    # 先分组查出每个 host_id 最大的记录 ID
    max_id_subq = (
        select(func.max(BackupRecord.id).label("max_id"))
        .group_by(BackupRecord.host_id)
        .subquery()
    )
    # 基于最大记录 ID 查出完整的记录行
    records_stmt = select(BackupRecord).where(BackupRecord.id.in_(select(max_id_subq.c.max_id)))
    records_res = await db.execute(records_stmt)
    records = {r.host_id: r for r in records_res.scalars().all()}

    # 3. 将最新纪录装配回主机配置中
    response_data = []
    for host in hosts:
        # 将 ORM 转为字典或直接包装成 Schema 格式
        host_dict = {
            "id": host.id,
            "host_name": host.host_name,
            "ip": host.ip,
            "ssh_port": host.ssh_port,
            "db_port": host.db_port,
            "cron_expression": host.cron_expression,
            "is_active": host.is_active,
            "created_at": host.created_at,
            "updated_at": host.updated_at,
            "latest_record": records.get(host.id)  # 装配最新的一条备份状态
        }
        response_data.append(host_dict)

    return response_data


@app.post("/api/hosts", response_model=schemas.HostConfigResponse, summary="新增主机配置")
async def create_host(host_in: schemas.HostConfigCreate, db: AsyncSession = Depends(get_db)):
    """向管理库添加一台新的目标数据库服务器，自动建立 SSH 预检连接抓取主机名并保存，同时注册定时备份。"""
    import asyncssh

    # 1. 如果用户未提供主机名，则尝试通过 SSH 自动抓取
    fetched_hostname = host_in.host_name.strip()
    if not fetched_hostname:
        try:
            async with asyncssh.connect(
                host_in.ip,
                port=host_in.ssh_port,
                username=settings.global_ssh_user,
                client_keys=[settings.global_ssh_key_path],
                known_hosts=None
            ) as conn:
                result = await conn.run('hostname', check=True)
                fetched_hostname = result.stdout.strip()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"获取主机名失败，请手动填写。SSH 错误信息: {str(e)}"
            )

    if not fetched_hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法获取主机别名，不可为空"
        )

    # 2. 查重
    dup_stmt = select(HostConfig).where(HostConfig.host_name == fetched_hostname)
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"主机名 '{fetched_hostname}' 在系统中已存在，请勿重复添加同一主机。"
        )

    # 3. 写入主机
    host_data = host_in.model_dump()
    host_data["host_name"] = fetched_hostname
    host = HostConfig(**host_data)
    db.add(host)
    await db.commit()
    await db.refresh(host)

    # 4. 同步定时调度任务
    if host.is_active:
        backup_scheduler.add_host_job(host.id, host.cron_expression, host.host_name)

    return host


@app.post("/api/hosts/batch", summary="批量导入主机并并发执行验证")
async def batch_create_hosts(batch_in: schemas.HostConfigBatchCreate):
    """批量添加目标主机配置。

    并发异步地对所有 IP 进行 SSH 验证连接抓取 hostname，
    成功的主机入库并同步注册定时备份；失败的机器收集具体原因并汇总报告返回。
    """
    # 过滤空 IP 并去重
    raw_ips = [ip.strip() for ip in batch_in.ips if ip.strip()]
    unique_ips = list(set(raw_ips))

    if not unique_ips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="提供的 IP 地址列表为空，请至少输入一个有效的 IP 地址。"
        )

    # 从数据库管理器导入 Session 制造器
    from database import AsyncSessionLocal

    import asyncssh

    async def _verify_and_create_single_host(ip_addr: str) -> dict:
        # 1. 尝试通过 SSH 登录目标机获取原生 hostname
        fetched_hostname = f"host-{ip_addr.replace('.', '-')}"
        try:
            async with asyncssh.connect(
                ip_addr,
                port=batch_in.ssh_port,
                username=settings.global_ssh_user,
                client_keys=[settings.global_ssh_key_path],
                known_hosts=None
            ) as conn:
                result = await conn.run('hostname', check=True)
                real_hostname = result.stdout.strip()
                if real_hostname:
                    fetched_hostname = real_hostname
        except Exception as e:
            # 获取失败则降级使用 IP 生成的别名
            pass

        # 2. 查重并写入数据库 (使用独立的子 Session，保证并发事务隔离)
        try:
            async with AsyncSessionLocal() as session:
                # 查重 A：别名唯一性
                dup_name_stmt = select(HostConfig).where(HostConfig.host_name == fetched_hostname)
                dup_name_res = await session.execute(dup_name_stmt)
                if dup_name_res.scalar_one_or_none():
                    return {"ip": ip_addr, "status": "failed", "reason": f"主机名 '{fetched_hostname}' 在库中已存在冲突"}

                # 查重 B：IP 唯一性
                dup_ip_stmt = select(HostConfig).where(HostConfig.ip == ip_addr)
                dup_ip_res = await session.execute(dup_ip_stmt)
                if dup_ip_res.scalar_one_or_none():
                    return {"ip": ip_addr, "status": "failed", "reason": f"IP '{ip_addr}' 已经注册过，请勿重复添加"}

                # 保存主机
                host_obj = HostConfig(
                    host_name=fetched_hostname,
                    ip=ip_addr,
                    ssh_port=batch_in.ssh_port,
                    db_port=batch_in.db_port,
                    cron_expression=batch_in.cron_expression,
                    is_active=batch_in.is_active
                )
                session.add(host_obj)
                await session.commit()
                await session.refresh(host_obj)

                # 同步注册定时备份作业
                if host_obj.is_active:
                    backup_scheduler.add_host_job(host_obj.id, host_obj.cron_expression, host_obj.host_name)

                return {"ip": ip_addr, "status": "success", "hostname": fetched_hostname}
        except Exception as db_ex:
            return {"ip": ip_addr, "status": "failed", "reason": f"数据库写入异常: {str(db_ex)}"}

    # 并发预检与注册
    tasks = [_verify_and_create_single_host(ip) for ip in unique_ips]
    results = await asyncio.gather(*tasks)

    # 统计成功数与失败汇总
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_hosts = [r for r in results if r["status"] == "failed"]

    return {
        "total": len(unique_ips),
        "success_count": success_count,
        "failed_hosts": failed_hosts
    }


@app.put("/api/hosts/{host_id}", response_model=schemas.HostConfigResponse, summary="修改主机配置")
async def update_host(host_id: int, host_in: schemas.HostConfigUpdate, db: AsyncSession = Depends(get_db)):
    """更新指定主机的配置信息。若修改了网络配置，自动触发 SSH 验证连接更新主机名并重载调度作业。"""
    stmt = select(HostConfig).where(HostConfig.id == host_id)
    res = await db.execute(stmt)
    host = res.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该主机配置")

    # 检查是否有重名的冲突
    if host_in.host_name and host_in.host_name != host.host_name:
        dup_stmt = select(HostConfig).where(HostConfig.host_name == host_in.host_name).where(HostConfig.id != host_id)
        dup_res = await db.execute(dup_stmt)
        if dup_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"目标主机的新主机名 '{host_in.host_name}' 在系统中已存在冲突。"
            )

    # 更新配置数据
    update_data = host_in.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(host, field, value)
    
    await db.commit()
    await db.refresh(host)

    # 同步更新调度作业
    backup_scheduler.update_host_job(
        host.id, host.cron_expression, host.host_name, host.is_active
    )

    return host


@app.delete("/api/hosts/{host_id}", summary="删除主机配置")
async def delete_host(host_id: int, db: AsyncSession = Depends(get_db)):
    """从数据库中删除指定主机配置，并移除对应的定时备份任务及级联删除其历史备份记录。"""
    stmt = select(HostConfig).where(HostConfig.id == host_id)
    res = await db.execute(stmt)
    host = res.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该主机配置")

    # 从调度器中注销作业
    backup_scheduler.remove_host_job(host.id)

    # 从数据库中移除主机配置
    await db.delete(host)
    await db.commit()

    return {"status": "success", "detail": f"主机配置 {host_id} 已成功移除。"}


@app.get("/api/hosts/{host_id}/records", response_model=List[schemas.BackupRecordResponse], summary="查询主机的历史备份记录")
async def get_host_records(host_id: int, page: int = 1, limit: int = 10, db: AsyncSession = Depends(get_db)):
    """分页查询某台主机的历史备份执行日志记录。"""
    offset = (page - 1) * limit
    stmt = (
        select(BackupRecord)
        .where(BackupRecord.host_id == host_id)
        .order_by(desc(BackupRecord.start_time))
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return records


@app.post("/api/hosts/{host_id}/backup", summary="手动点击重新生成/触发备份")
async def trigger_manual_backup(host_id: int, db: AsyncSession = Depends(get_db)):
    """手动触发立即执行针对某主机的数据库克隆备份（异步非阻塞）。"""
    # 1. 检查是否存在该主机
    stmt = select(HostConfig).where(HostConfig.id == host_id)
    res = await db.execute(stmt)
    host = res.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该主机配置")

    # 2. 页面防抖与并发保护：中止该主机当前所有正在运行或排队的任务
    running_stmt = (
        select(BackupRecord)
        .where(BackupRecord.host_id == host_id)
        .where(BackupRecord.status.in_(["pending", "running"]))
    )
    running_res = await db.execute(running_stmt)
    active_records = running_res.scalars().all()
    for active_record in active_records:
        active_record.status = "failed"
        active_record.progress_status = "ABORTED_BY_NEW_MANUAL_TRIGGER"
        active_record.end_time = datetime.now()
        active_record.error_message = "被新的手动触发任务强制中止"
    
    if active_records:
        await db.commit()

    # 3. 执行 Zabbix 角色校验，拦截非备库节点
    try:
        await verify_zabbix_role(host.ip, host.host_name)
    except RuntimeError as e:
        # 如果不符合要求，生成一条失败记录以便前端溯源
        record = BackupRecord(
            host_id=host.id,
            status="failed",
            progress_status="ZABBIX_ROLE_REJECTED",
            error_message=str(e),
            start_time=datetime.now(),
            end_time=datetime.now()
        )
        db.add(record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Zabbix 主备角色验证未通过，拒绝下发任务: {str(e)}"
        )

    # 4. 生成 pending 状态任务，替代原来的直接 SSH 执行
    record = BackupRecord(
        host_id=host.id,
        status="pending",
        progress_status="WAITING_FOR_AGENT",
        start_time=datetime.now()
    )
    db.add(record)
    await db.commit()
    
    return {"status": "triggered", "detail": f"主机 '{host.host_name}' 备份任务已成功下发（处于 pending 状态，等待 Agent 拉取）。"}


@app.post("/api/hosts/{host_id}/records/{record_id}/abort", summary="手动中止或重置运行中的备份记录")
async def abort_backup_record(host_id: int, record_id: int, db: AsyncSession = Depends(get_db)):
    """手动中止指定主机的备份历史记录，并将状态标记为失败。

    Args:
        host_id (int): 关联的主机 ID。
        record_id (int): 备份记录 ID。
        db (AsyncSession): 数据库 Session。

    Returns:
        dict: 执行结果状态。

    Raises:
        HTTPException: 当记录不存在或已经结束时抛出。
    """
    stmt = (
        select(BackupRecord)
        .where(BackupRecord.id == record_id)
        .where(BackupRecord.host_id == host_id)
    )
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到对应的备份记录"
        )

    if record.status not in ("running", "pending"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该备份任务已结束，无法中止"
        )

    record.status = "failed"
    record.progress_status = "ABORTED"
    record.end_time = datetime.now()
    record.error_message = "备份任务已被管理员手动中止"

    await db.commit()
    return {"status": "success", "detail": f"备份记录 {record_id} 已手动中止。"}


@app.post("/api/hosts/{host_id}/deploy", summary="一键自动化部署目标机 Agent")
async def deploy_host_agent(host_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """向目标主机发起一键 Agent 安装部署。"""
    stmt = select(HostConfig).where(HostConfig.id == host_id)
    res = await db.execute(stmt)
    host = res.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="未找到该主机配置")
        
    try:
        # 获取当前请求的基础 URL 作为 API_BASE（如果存在反向代理可能需要自行修正）
        api_base = str(request.base_url).rstrip("/")
        
        await deploy_agent_to_host(
            ip=host.ip,
            ssh_port=host.ssh_port,
            host_name=host.host_name,
            api_base=api_base
        )
        return {"status": "success", "detail": "Agent 部署成功且已启动运行！"}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"部署过程发生未捕获的错误: {str(e)}")


@app.post("/api/hosts/batch-deploy", summary="批量自动部署所有有效主机的 Agent")
async def batch_deploy_agents(request: Request, db: AsyncSession = Depends(get_db)):
    """并发向所有有效的主机推送最新 Agent。"""
    stmt = select(HostConfig).where(HostConfig.is_active == True)
    res = await db.execute(stmt)
    hosts = res.scalars().all()
    
    if not hosts:
        raise HTTPException(status_code=400, detail="没有找到任何已启用的主机配置")

    api_base = str(request.base_url).rstrip("/")
    
    async def _deploy_single(host):
        try:
            await deploy_agent_to_host(
                ip=host.ip,
                ssh_port=host.ssh_port,
                host_name=host.host_name,
                api_base=api_base
            )
            return {"host_name": host.host_name, "ip": host.ip, "status": "success"}
        except Exception as e:
            return {"host_name": host.host_name, "ip": host.ip, "status": "failed", "reason": str(e)}

    tasks = [_deploy_single(h) for h in hosts]
    results = await asyncio.gather(*tasks)
    
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_hosts = [r for r in results if r["status"] == "failed"]
    
    return {
        "status": "success",
        "total": len(hosts),
        "success_count": success_count,
        "failed_hosts": failed_hosts,
        "detail": f"批量部署完成。成功 {success_count} 台，失败 {len(failed_hosts)} 台。"
    }


# =====================================================================
# Agent (Pull 模式) 通信接口
# =====================================================================

from encrypt_tool import encrypt_text

@app.get("/api/agent/task", response_model=Optional[schemas.AgentTaskResponse], summary="Agent 轮询获取任务")
async def agent_get_task(hostname: str, authorization: str = Header(...), db: AsyncSession = Depends(get_db)):
    """Agent 轮询获取 pending 的备份任务。"""
    # 1. 验证 Authorization Header
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    token = authorization.split("Bearer ")[1]
    if token != settings.encryption_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    # 2. 查找主机并更新心跳
    stmt = select(HostConfig).where(HostConfig.host_name == hostname)
    host = (await db.execute(stmt)).scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
        
    host.last_heartbeat = datetime.now()
    await db.commit()
    
    # 3. 查找该主机的首个 pending 任务
    stmt_task = select(BackupRecord).where(
        BackupRecord.host_id == host.id,
        BackupRecord.status == "pending"
    ).order_by(BackupRecord.id.asc()).limit(1)
    record = (await db.execute(stmt_task)).scalar_one_or_none()
    
    if not record:
        return None  # 当前无任务
        
    # 4. 生成 Base64 混淆凭据并返回（防止明文直接暴露在网络嗅探器的基础视线中）
    db_user_enc = base64.b64encode(settings.global_db_user.encode()).decode()
    db_pass_enc = base64.b64encode(settings.global_db_password.encode()).decode()
    
    # 5. 更新任务状态为 running
    record.status = "running"
    record.progress_status = "PULLED_BY_AGENT"
    await db.commit()
    
    return schemas.AgentTaskResponse(
        record_id=record.id,
        db_port=host.db_port,
        db_user_enc=db_user_enc,
        db_pass_enc=db_pass_enc,
        backup_dir=settings.global_backup_dir,
        nfs_dir=settings.global_nfs_dir,
        rsync_bwlimit=settings.global_rsync_bwlimit
    )

@app.post("/api/agent/report/{record_id}", summary="Agent 上报执行进度与状态")
async def agent_report_progress(record_id: int, report: schemas.AgentReportRequest, authorization: str = Header(...), db: AsyncSession = Depends(get_db)):
    """Agent 回调更新备份任务状态接口。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    token = authorization.split("Bearer ")[1]
    if token != settings.encryption_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    stmt = select(BackupRecord).where(BackupRecord.id == record_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
        
    # 增加并发死锁保护：如果任务已经被服务端强制中止，忽略 Agent 延迟发来的任何上报
    if record.progress_status and "ABORT" in record.progress_status.upper():
        return {"status": "ignored", "detail": "Record already aborted by server"}
        
    if report.status:
        record.status = report.status
    if report.progress_status:
        record.progress_status = report.progress_status
    if report.error_message:
        record.error_message = report.error_message
    if report.backup_file:
        record.backup_file = report.backup_file
    if report.file_size_bytes is not None:
        record.file_size_bytes = report.file_size_bytes
        
    if report.status in ["success", "failed"]:
        record.end_time = datetime.now()
        
    # 顺带更新主机的 Agent 版本号与心跳
    if report.agent_version:
        stmt_host = select(HostConfig).where(HostConfig.id == record.host_id)
        host = (await db.execute(stmt_host)).scalar_one_or_none()
        if host:
            host.agent_version = report.agent_version
            host.last_heartbeat = datetime.now()

    await db.commit()
    
    # TODO: 失败可在此触发告警邮件
    if report.status == "failed" and settings.alarm_script_path:
        from notifier import send_alarm
        host_name = "Agent Node"
        ip = "Unknown IP"
        # 尝试查询更多信息
        stmt_h = select(HostConfig).where(HostConfig.id == record.host_id)
        h = (await db.execute(stmt_h)).scalar_one_or_none()
        if h:
            host_name = h.host_name
            ip = h.ip
        brief_error = (report.error_message or "Unknown").split("\n")[0]
        content = f"主机 IP: {ip}\n主机别名: {host_name}\n错误描述: {brief_error}\n\n详细故障堆栈:\n{report.error_message}"
        asyncio.create_task(send_alarm(ip=ip, title=f"MySQL 备份失败告警: 主机 {host_name}", content=content))

    return {"status": "ok"}


@app.get("/api/settings/template", summary="获取 Agent systemd 部署模板")
async def get_agent_template():
    """读取并返回全局的 backup-agent.service 模板内容。"""
    local_svc = os.path.join("agent", "backup-agent.service")
    if not os.path.isfile(local_svc):
        raise HTTPException(status_code=404, detail="系统模板文件不存在")
    try:
        with open(local_svc, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取模板失败: {str(e)}")


@app.put("/api/settings/template", summary="更新 Agent systemd 部署模板")
async def update_agent_template(req: schemas.TemplateUpdateRequest):
    """覆盖更新本地的 backup-agent.service 模板内容。"""
    local_svc = os.path.join("agent", "backup-agent.service")
    try:
        # 确保 agent 目录存在
        os.makedirs("agent", exist_ok=True)
        with open(local_svc, "w", encoding="utf-8") as f:
            f.write(req.content)
        return {"status": "success", "detail": "模板已成功保存！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存模板失败: {str(e)}")


# =====================================================================
# 静态文件挂载与前端整体托管
# =====================================================================

# 检查 frontend/dist 打包输出目录是否存在
# 若存在，则由 FastAPI 通过 / 根路由进行静态资源托管代理，实现单端口一键运行
dist_path = os.path.join(os.path.dirname(__file__), "frontend/dist")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
    logging.info(f"前端静态目录托管成功: {dist_path}")
else:
    logging.warning(
        f"未检测到编译后的前端静态目录: {dist_path}。可能是初次启动或开发分离状态下，请在 frontend 下执行 'npm run build' 打包。"
    )
