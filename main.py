# -*- coding: utf-8 -*-
"""FastAPI 服务端主模块。

包含 API 路由接口（主机增删改查、备份手动触发、历史记录查询）、
服务生命周期管理（数据库表创建与定时任务加载）以及前端静态资源的代理托管。
"""

import asyncio
import os
import asyncssh
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backup_executor import run_backup
from config import settings
from database import async_engine, Base, get_db
from models import HostConfig, BackupRecord
from scheduler import backup_scheduler
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

    # 1. 定时作业同步并启动调度器
    await backup_scheduler.sync_jobs_from_db()
    backup_scheduler.start()
    
    yield
    
    # 2. 关闭调度器
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
    # 1. 异步预检获取目标主机的真实主机名
    try:
        connect_kwargs = {
            "host": host_in.ip,
            "port": host_in.ssh_port,
            "username": settings.global_ssh_user,
            "known_hosts": None,
        }
        if os.path.exists(settings.global_ssh_key_path):
            connect_kwargs["client_keys"] = [settings.global_ssh_key_path]
        else:
            raise FileNotFoundError(f"全局 SSH 私钥文件 {settings.global_ssh_key_path} 不存在。")
            
        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run("hostname")
            if result.exit_status != 0:
                raise RuntimeError(result.stderr or "执行 hostname 命令返回异常")
            fetched_hostname = result.stdout.strip()
            if not fetched_hostname:
                raise RuntimeError("主机名返回结果为空")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法通过 SSH 连接到目标主机验证并获取主机名，请检查 IP、SSH 端口及密钥配置。错误信息: {str(e)}"
        )

    # 2. 查重
    dup_stmt = select(HostConfig).where(HostConfig.host_name == fetched_hostname)
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"自动获取的主机名 '{fetched_hostname}' 在系统中已存在，请勿重复添加同一主机。"
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

    async def _verify_and_create_single_host(ip_addr: str) -> dict:
        """异步执行单台机器的 SSH 校验与管理库插入逻辑。"""
        # 1. 建立预检 SSH 连接
        try:
            connect_kwargs = {
                "host": ip_addr,
                "port": batch_in.ssh_port,
                "username": settings.global_ssh_user,
                "known_hosts": None,
            }
            if os.path.exists(settings.global_ssh_key_path):
                connect_kwargs["client_keys"] = [settings.global_ssh_key_path]
            else:
                return {"ip": ip_addr, "status": "failed", "reason": "管理机上的全局 SSH 私钥文件不存在"}

            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await conn.run("hostname")
                if result.exit_status != 0:
                    return {"ip": ip_addr, "status": "failed", "reason": f"SSH执行失败: {result.stderr or '未知错误'}"}
                fetched_hostname = result.stdout.strip()
                if not fetched_hostname:
                    return {"ip": ip_addr, "status": "failed", "reason": "目标机 hostname 命令返回空结果"}
        except Exception as e:
            return {"ip": ip_addr, "status": "failed", "reason": f"SSH连接异常: {str(e)}"}

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

    # 检查是否修改了网络配置以决定是否重新抓取 hostname
    new_ip = host_in.ip
    new_port = host_in.ssh_port
    
    if (new_ip is not None and new_ip != host.ip) or (new_port is not None and new_port != host.ssh_port):
        check_ip = new_ip if new_ip is not None else host.ip
        check_port = new_port if new_port is not None else host.ssh_port
        try:
            connect_kwargs = {
                "host": check_ip,
                "port": check_port,
                "username": settings.global_ssh_user,
                "known_hosts": None,
            }
            if os.path.exists(settings.global_ssh_key_path):
                connect_kwargs["client_keys"] = [settings.global_ssh_key_path]
            
            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await conn.run("hostname")
                if result.exit_status != 0:
                    raise RuntimeError(result.stderr or "执行 hostname 异常")
                fetched_hostname = result.stdout.strip()
                if not fetched_hostname:
                    raise RuntimeError("主机名为空")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"更新网络配置失败：无法通过 SSH 连接到新主机地址验证。错误: {str(e)}"
            )

        # 查重 (排除自己)
        dup_stmt = select(HostConfig).where(HostConfig.host_name == fetched_hostname).where(HostConfig.id != host_id)
        dup_res = await db.execute(dup_stmt)
        if dup_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"目标主机的新主机名 '{fetched_hostname}' 在系统中已存在冲突。"
            )
        host.host_name = fetched_hostname

    # 更新配置数据
    update_data = host_in.model_dump(exclude_unset=True)
    # host_name 不能由客户端手动传入修改，因为它由 IP 抓取决定
    update_data.pop("host_name", None)
    
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

    # 2. 页面防抖与并发保护：检查该主机当前是否已有正在运行的备份任务
    running_stmt = (
        select(BackupRecord)
        .where(BackupRecord.host_id == host_id)
        .where(BackupRecord.status == "running")
    )
    running_res = await db.execute(running_stmt)
    if running_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前该主机已有一个备份任务正在运行中，请勿重复触发！"
        )

    # 3. 异步拉起备份任务并立即返回响应，保证 HTTP 不阻塞
    asyncio.create_task(run_backup(host_id))
    
    return {"status": "triggered", "detail": f"主机 '{host.host_name}' 备份任务已成功下发并后台运行。"}


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
