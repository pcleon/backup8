# -*- coding: utf-8 -*-
"""用户自定义告警测试脚本。

用于本地开发调试或现场联调，模拟 MyAlarm 类的发送行为。
"""
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_alarm")


class MyAlarm:
    """模拟用户的邮件告警类。"""

    def __init__(self, ip: str, title: str, content: str) -> None:
        """初始化告警类。

        Args:
            ip (str): 报警关联的目标主机 IP。
            title (str): 邮件通知标题。
            content (str): 邮件正文内容。
        """
        self.ip = ip
        self.title = title
        self.content = content

    def send(self) -> None:
        """模拟发送邮件，打印日志内容。"""
        logger.info("=== [MyAlarm MOCK 发送成功] ===")
        logger.info(f"关联主机 IP: {self.ip}")
        logger.info(f"邮件标题: {self.title}")
        logger.info(f"邮件内容:\n{self.content}")
        logger.info("=================================")
