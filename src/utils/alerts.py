"""
告警工具模块

提供告警发送和处理功能
"""
import logging
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

# 尝试导入Telegram库，不可用时提供降级方案
try:
    import telegram
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class AlertHandler:
    """基础告警处理器"""
    
    def __init__(self):
        """初始化告警处理器"""
        self.logger = logging.getLogger(__name__)
    
    async def send_alert(self, message: str) -> bool:
        """发送告警
        
        Args:
            message: 告警消息
            
        Returns:
            是否发送成功
        """
        raise NotImplementedError("子类必须实现此方法")


class TelegramAlertHandler(AlertHandler):
    """Telegram告警处理器"""
    
    def __init__(self, token: str, chat_id: str):
        """初始化Telegram告警处理器
        
        Args:
            token: Telegram机器人token
            chat_id: 聊天ID
        """
        super().__init__()
        self.token = token
        self.chat_id = chat_id
        self.bot = self._create_bot() if TELEGRAM_AVAILABLE else None
    
    def _create_bot(self) -> Optional[telegram.Bot]:
        """创建Telegram机器人
        
        Returns:
            Telegram机器人实例
        """
        if not TELEGRAM_AVAILABLE:
            self.logger.warning("Telegram库未安装，无法创建机器人")
            return None
        
        try:
            return telegram.Bot(token=self.token)
        except Exception as e:
            self.logger.error(f"创建Telegram机器人失败: {e}")
            return None
    
    async def send_alert(self, message: str) -> bool:
        """发送Telegram告警
        
        Args:
            message: 告警消息
            
        Returns:
            是否发送成功
        """
        if not TELEGRAM_AVAILABLE or not self.bot:
            self.logger.warning("Telegram不可用，无法发送告警")
            return False
        
        try:
            # 在开发模式下使用同步方式避免异步问题
            import os
            dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"
            
            if dev_mode:
                # 开发模式下只记录日志，不实际发送
                self.logger.info(f"开发模式: 模拟发送Telegram告警: {message}")
                return True
            else:
                # 正确处理异步调用
                await self.bot.send_message(chat_id=self.chat_id, text=message)
                return True
        except Exception as e:
            self.logger.error(f"发送Telegram告警失败: {e}")
            return False


class EmailAlertHandler(AlertHandler):
    """邮件告警处理器"""
    
    def __init__(self, smtp_server: str, port: int, sender: str, password: str, recipients: List[str]):
        """初始化邮件告警处理器
        
        Args:
            smtp_server: SMTP服务器
            port: 端口
            sender: 发件人
            password: 密码
            recipients: 收件人列表
        """
        super().__init__()
        self.smtp_server = smtp_server
        self.port = port
        self.sender = sender
        self.password = password
        self.recipients = recipients
    
    async def send_alert(self, message: str) -> bool:
        """发送邮件告警
        
        Args:
            message: 告警消息
            
        Returns:
            是否发送成功
        """
        try:
            # 创建邮件
            msg = MIMEMultipart()
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = "资金费率套利策略告警"
            
            # 添加正文
            msg.attach(MIMEText(message, "plain"))
            
            # 使用异步执行发送
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._send_email,
                msg
            )
            return True
        except Exception as e:
            self.logger.error(f"发送邮件告警失败: {e}")
            return False
    
    def _send_email(self, msg):
        """发送邮件
        
        Args:
            msg: 邮件消息
        """
        with smtplib.SMTP(self.smtp_server, self.port) as server:
            server.starttls()
            server.login(self.sender, self.password)
            server.sendmail(self.sender, self.recipients, msg.as_string())


class ConsoleAlertHandler(AlertHandler):
    """控制台告警处理器，用于本地测试"""
    
    async def send_alert(self, message: str) -> bool:
        """在控制台打印告警
        
        Args:
            message: 告警消息
            
        Returns:
            始终返回True
        """
        print(f"[告警] {message}")
        return True
