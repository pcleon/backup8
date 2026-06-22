# -*- coding: utf-8 -*-
"""备份任务调度管理器。

使用 APScheduler 的 AsyncIOScheduler 定时调度和触发被激活主机的克隆备份任务，
支持从管理数据库动态同步、添加、移除和更新调度作业。
"""

import logging
from typing import Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from backup_executor import run_backup
from config import settings
from database import AsyncSessionLocal
from models import HostConfig

# 初始化日志
logger = logging.getLogger("backup_scheduler")
logger.setLevel(logging.INFO)


class BackupScheduler:
    """自动备份调度管理器类。

    封装 AsyncIOScheduler 以进行定时任务的管理。
    """

    def __init__(self) -> None:
        """初始化调度管理器。"""
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler()
        # 本地作业内存字典，用于跟踪当前已被调度的作业 {host_id: job_id}
        self._active_jobs: Dict[int, str] = {}

    def start(self) -> None:
        """启动定时调度器。"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("备份定时调度器已启动。")

    def shutdown(self) -> None:
        """关闭定时调度器。"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("备份定时调度器已关闭。")

    def _get_job_id(self, host_id: int) -> str:
        """生成作业 ID 的辅助方法。

        Args:
            host_id (int): 主机配置 ID。

        Returns:
            str: 格式化后的作业 ID 字符串。
        """
        return f"backup_job_host_{host_id}"

    def add_host_job(self, host_id: int, cron_expr: str, host_name: str) -> bool:
        """添加单个主机的定时备份任务。

        Args:
            host_id (int): 主机配置 ID。
            cron_expr (str): Cron 表达式（如 "0 2 * * *"）。
            host_name (str): 主机别名。

        Returns:
            bool: 添加成功返回 True，失败返回 False。
        """
        job_id = self._get_job_id(host_id)
        
        # 如果已经存在该作业，先移除以防重复
        self.remove_host_job(host_id)

        try:
            # 解析 cron 表达式
            trigger = CronTrigger.from_crontab(cron_expr)
            self.scheduler.add_job(
                run_backup,
                trigger=trigger,
                args=[host_id],
                id=job_id,
                name=f"Backup for {host_name}",
                replace_existing=True,
            )
            self._active_jobs[host_id] = job_id
            logger.info(f"成功为主机 {host_name} (ID: {host_id}) 添加定时任务。Cron: '{cron_expr}'")
            return True
        except Exception as e:
            logger.error(f"为主机 {host_name} (ID: {host_id}) 添加定时任务失败，Cron 格式错误: {str(e)}")
            return False

    def remove_host_job(self, host_id: int) -> None:
        """移除指定主机的定时备份任务。

        Args:
            host_id (int): 主机配置 ID。
        """
        job_id = self._get_job_id(host_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"已移除主机 ID {host_id} 的定时任务。")
        self._active_jobs.pop(host_id, None)

    def update_host_job(self, host_id: int, cron_expr: str, host_name: str, is_active: bool) -> None:
        """更新指定主机的定时备份任务。

        根据主机的激活状态和最新的 Cron 表达式重新分配或移除作业。

        Args:
            host_id (int): 主机配置 ID。
            cron_expr (str): 最新的 Cron 表达式。
            host_name (str): 主机别名。
            is_active (bool): 主机是否处于激活状态。
        """
        if is_active:
            self.add_host_job(host_id, cron_expr, host_name)
        else:
            self.remove_host_job(host_id)

    def add_email_report_job(self) -> None:
        """如果配置了报警脚本路径，注册每日备份异常邮件汇总定时任务。"""
        if not settings.alarm_script_path:
            logger.info("未配置邮件报警脚本路径，跳过注册每日备份异常汇总任务。")
            if self.scheduler.get_job("daily_backup_error_report"):
                self.scheduler.remove_job("daily_backup_error_report")
            return

        try:
            from notifier import send_daily_error_report
            trigger = CronTrigger.from_crontab(settings.email_send_cron)
            self.scheduler.add_job(
                send_daily_error_report,
                trigger=trigger,
                id="daily_backup_error_report",
                name="Daily MySQL backup error report",
                replace_existing=True,
            )
            logger.info(f"成功注册每日备份异常汇总发信任务。Cron: '{settings.email_send_cron}'")
        except Exception as e:
            logger.error(f"注册每日备份异常汇总发信定时任务失败: {str(e)}")

    async def sync_jobs_from_db(self) -> None:
        """从管理数据库中拉取所有处于活跃状态的主机配置，同步到调度器作业队列中。"""
        logger.info("正在从管理数据库同步备份定时作业...")
        
        async with AsyncSessionLocal() as session:
            stmt = select(HostConfig).where(HostConfig.is_active == True)
            result = await session.execute(stmt)
            active_hosts = result.scalars().all()
            
            # 当前数据库中处于活跃状态的 ID 集合
            active_db_ids = set()
            
            for host in active_hosts:
                active_db_ids.add(host.id)
                self.add_host_job(host.id, host.cron_expression, host.host_name)
                
            # 清理那些在数据库中已被停用/删除但仍在调度器中运行的作业
            current_active_job_ids = list(self._active_jobs.keys())
            for host_id in current_active_job_ids:
                if host_id not in active_db_ids:
                    self.remove_host_job(host_id)
                    
        logger.info(f"定时作业同步完成，当前活动定时作业数: {len(self._active_jobs)}")
        
        # 挂载可选的每日异常汇总邮件任务
        self.add_email_report_job()


# 全局单例调度管理器对象
backup_scheduler = BackupScheduler()
