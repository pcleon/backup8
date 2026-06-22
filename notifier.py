# -*- coding: utf-8 -*-
"""邮件报警通知模块。

动态加载用户配置的 Python 脚本中的 MyAlarm 类，
并在备份任务异常或每日定时总结时调用该类发送邮件。
"""

import asyncio
import importlib.util
import logging
import os
import sys
from datetime import datetime, time
from typing import Any, Optional

from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models import BackupRecord, HostConfig

# 初始化日志记录器
logger = logging.getLogger("backup_notifier")
logger.setLevel(logging.INFO)


def load_my_alarm_class() -> Optional[Any]:
    """动态从用户配置的脚本路径中导入并获取 MyAlarm 类。

    通过 importlib 载入目标 Python 文件，并读取其导出的 MyAlarm 属性。
    自动将目标脚本所在目录追加到 sys.path 中以支持相对导入。

    Returns:
        Optional[Any]: 导出的 MyAlarm 类；若配置为空、文件不存在或加载异常则返回 None。
    """
    path = settings.alarm_script_path
    if not path:
        return None

    # 获取脚本的绝对路径
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        logger.error(f"自定义报警发送脚本不存在，请检查配置: {abs_path}")
        return None

    try:
        # 将脚本所在的目录临时加入 sys.path，保证其内部的相对导入正常运行
        script_dir = os.path.dirname(abs_path)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        # 动态加载模块
        spec = importlib.util.spec_from_file_location("alarm_module", abs_path)
        if spec is None or spec.loader is None:
            logger.error(f"无法为路径创建 spec 加载器: {abs_path}")
            return None

        alarm_module = importlib.util.module_from_spec(spec)
        sys.modules["alarm_module"] = alarm_module
        spec.loader.exec_module(alarm_module)

        # 获取 MyAlarm 属性
        if hasattr(alarm_module, "MyAlarm"):
            return getattr(alarm_module, "MyAlarm")
        else:
            logger.error(f"报警脚本加载成功，但其中找不到 'MyAlarm' 类: {abs_path}")
            return None
    except Exception as e:
        logger.error(f"动态加载 MyAlarm 类时抛出异常: {str(e)}", exc_info=True)
        return None


async def send_alarm(ip: str, title: str, content: str) -> bool:
    """异步发送单次邮件报警。

    利用 asyncio.to_thread 在后台线程池中同步调用用户自定义的 MyAlarm 类以防阻塞主循环。

    Args:
        ip (str): 报警关联的目标主机 IP。
        title (str): 邮件通知标题。
        content (str): 邮件具体正文内容。

    Returns:
        bool: 发送并执行成功返回 True，配置无效或抛出异常返回 False。
    """
    MyAlarm = load_my_alarm_class()
    if not MyAlarm:
        return False

    try:
        # 定义同步执行的发信过程
        def _sync_send() -> None:
            alarm = MyAlarm(ip, title, content)
            alarm.send()

        # 在异步线程池中运行同步发信，保证不挂起主线程
        await asyncio.to_thread(_sync_send)
        logger.info(f"成功调用自定义 MyAlarm 发送邮件: ip={ip}, title={title}")
        return True
    except Exception as e:
        logger.error(f"调用 MyAlarm 发送报警邮件发生异常: ip={ip}, 错误: {str(e)}", exc_info=True)
        return False


async def send_daily_error_report() -> None:
    """自动收集当天备份异常的主机列表与 IP，并通过 MyAlarm 统一发送汇总邮件报告。

    获取当天 (00:00:00 - 23:59:59) 所有 status 为 'failed' 的 BackupRecord，
    并把它们拼接为 HTML 样式表格通过报警类投递。
    """
    logger.info("正在生成每日备份异常汇总数据...")

    # 获取当天起止时间
    now = datetime.now()
    today_start = datetime.combine(now.date(), time.min)
    today_end = datetime.combine(now.date(), time.max)

    # 1. 批量查询当天所有失败的备份任务及对应的 IP 配置
    async with AsyncSessionLocal() as session:
        stmt = (
            select(BackupRecord, HostConfig)
            .join(HostConfig)
            .where(BackupRecord.status == "failed")
            .where(BackupRecord.start_time >= today_start)
            .where(BackupRecord.start_time <= today_end)
            .order_by(BackupRecord.start_time)
        )
        res = await session.execute(stmt)
        failed_records = res.all()

    if not failed_records:
        logger.info("今日暂无备份失败的异常记录，跳过发送异常汇总邮件。")
        return

    # 2. 构造精美的 HTML 表格邮件内容
    table_rows = []
    for rec, host in failed_records:
        # 裁剪异常详情，避免邮件内容过长
        err_msg = (rec.error_message or "未知异常").split("\n")[0][:150]
        row_html = (
            f"<tr>"
            f"<td style='padding: 8px; border: 1px solid #ddd;'>{host.ip}</td>"
            f"<td style='padding: 8px; border: 1px solid #ddd;'>{host.host_name}</td>"
            f"<td style='padding: 8px; border: 1px solid #ddd;'>{rec.start_time.strftime('%Y-%m-%d %H:%M:%S')}</td>"
            f"<td style='padding: 8px; border: 1px solid #ddd; color: #d9534f;'>{err_msg}</td>"
            f"</tr>"
        )
        table_rows.append(row_html)

    html_content = (
        f"<h3>MySQL 物理备份系统 - 今日异常汇总报告</h3>"
        f"<p>报告时间: {now.strftime('%Y-%m-%d %H:%M:%S')}</p>"
        f"<table style='width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 14px;'>"
        f"<thead>"
        f"<tr style='background-color: #f8f9fa; text-align: left;'>"
        f"<th style='padding: 8px; border: 1px solid #ddd;'>主机 IP</th>"
        f"<th style='padding: 8px; border: 1px solid #ddd;'>主机别名</th>"
        f"<th style='padding: 8px; border: 1px solid #ddd;'>备份启动时间</th>"
        f"<th style='padding: 8px; border: 1px solid #ddd;'>故障主要原因</th>"
        f"</tr>"
        f"</thead>"
        f"<tbody>"
        f"".join(table_rows) +
        f"</tbody>"
        f"</table>"
        f"<p style='color: #666; font-size: 12px; margin-top: 15px;'>* 注意: 本邮件为系统自动发送，详细故障堆栈请前往管理后台进行系统日志走查。</p>"
    )

    # 3. 调起 MyAlarm，传入管理机 localhost 标识 (127.0.0.1) 和汇总信息
    title = f"MySQL 备份异常每日汇总 (共 {len(failed_records)} 台主机失败)"
    success = await send_alarm(ip="127.0.0.1", title=title, content=html_content)
    if success:
        logger.info("每日备份异常汇总报告邮件发送成功。")
    else:
        logger.error("每日备份异常汇总报告邮件发送失败。")
