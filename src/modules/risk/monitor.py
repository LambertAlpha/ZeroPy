"""
风险监控模块

监控系统风险，确保策略安全执行
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional, Literal
import time
from datetime import datetime

from ..market_data.service import MarketDataService
from ..account.manager import AccountManager


class RiskMonitor:
    """风险监控，负责监控系统风险并确保策略安全执行"""

    def __init__(self, config: Dict[str, Any], market_data: Optional[MarketDataService] = None, account_manager: Optional[AccountManager] = None):
        """初始化风险监控
        
        Args:
            config: 系统配置
            market_data: 市场数据服务，可选，会在start_monitoring时获取
            account_manager: 账户管理器，可选，会在start_monitoring时获取
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.market_data = market_data
        self.account_manager = account_manager
        
        self.risk_config = config.get("risk", {})
        self.monitoring_task = None
        self.is_monitoring = False
        self.alert_handlers = {}
        self.account_risk_levels = {}
        
        # 初始化告警处理器
        self._init_alert_handlers()
    
    def _init_alert_handlers(self):
        """初始化告警处理器"""
        alerts_config = self.config.get("alerts", {})
        
        # 配置Telegram告警
        if alerts_config.get("telegram", {}).get("enabled", False):
            try:
                from src.utils.alerts import TelegramAlertHandler
                telegram_config = alerts_config["telegram"]
                token = self._get_env_var(telegram_config["token_env"])
                chat_id = self._get_env_var(telegram_config["chat_id_env"])
                
                self.alert_handlers["telegram"] = TelegramAlertHandler(token, chat_id)
                self.logger.info("已初始化Telegram告警处理器")
            except Exception as e:
                self.logger.error(f"初始化Telegram告警处理器失败: {e}")
        
        # 配置邮件告警
        if alerts_config.get("email", {}).get("enabled", False):
            try:
                from src.utils.alerts import EmailAlertHandler
                email_config = alerts_config["email"]
                sender = self._get_env_var(email_config["sender_env"])
                password = self._get_env_var(email_config["password_env"])
                
                self.alert_handlers["email"] = EmailAlertHandler(
                    smtp_server=email_config["smtp_server"],
                    port=email_config["port"],
                    sender=sender,
                    password=password,
                    recipients=email_config["recipients"]
                )
                self.logger.info("已初始化邮件告警处理器")
            except Exception as e:
                self.logger.error(f"初始化邮件告警处理器失败: {e}")
    
    @staticmethod
    def _get_env_var(env_var_name: str) -> str:
        """从环境变量获取值
        
        Args:
            env_var_name: 环境变量名
            
        Returns:
            环境变量的值
            
        Raises:
            ValueError: 如果环境变量不存在
        """
        import os
        value = os.environ.get(env_var_name)
        if value is None:
            raise ValueError(f"环境变量 {env_var_name} 未设置")
        return value
    
    async def start_monitoring(self, market_data: Optional[MarketDataService] = None, account_manager: Optional[AccountManager] = None):
        """开始风险监控
        
        Args:
            market_data: 市场数据服务，可选
            account_manager: 账户管理器，可选
        """
        self.logger.info("开始风险监控")
        
        # 如果提供了服务实例，覆盖现有实例
        if market_data:
            self.market_data = market_data
        if account_manager:
            self.account_manager = account_manager
        
        # 确保必要的服务可用
        if not self.market_data or not self.account_manager:
            raise ValueError("风险监控需要市场数据服务和账户管理器")
        
        # 标记为正在监控
        self.is_monitoring = True
        
        # 启动监控任务
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        self.logger.info("风险监控已启动")
    
    async def stop_monitoring(self):
        """停止风险监控"""
        self.logger.info("停止风险监控")
        
        # 标记为停止监控
        self.is_monitoring = False
        
        # 取消监控任务
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            
            self.monitoring_task = None
        
        self.logger.info("风险监控已停止")
    
    async def _monitoring_loop(self):
        """风险监控主循环"""
        self.logger.info("风险监控循环已启动")
        
        while self.is_monitoring:
            try:
                # 监控市场条件
                market_status = await self.monitor_market_conditions()
                if market_status != "NORMAL":
                    self.logger.warning(f"市场状态异常: {market_status}")
                    await self._send_alert(
                        message=f"市场状态异常: {market_status}",
                        level="WARNING",
                        channels=["telegram", "email"]
                    )
                
                # 监控所有账户风险
                # 简化处理，仅监控已知账户
                for account_id in self.account_risk_levels.keys():
                    risk_level = await self.check_account_risk(account_id)
                    if risk_level == "HIGH":
                        self.logger.error(f"账户 {account_id} 风险级别高")
                        await self._send_alert(
                            message=f"账户 {account_id} 风险级别高，请检查",
                            level="ERROR",
                            channels=["telegram", "email"]
                        )
                        
                        # 强制执行风险限制
                        await self.enforce_risk_limits(account_id)
            
            except Exception as e:
                self.logger.error(f"风险监控循环出错: {e}")
            
            # 监控间隔
            await asyncio.sleep(5)  # 每5秒监控一次
    
    async def check_account_risk(self, account_id: str) -> Literal["LOW", "MEDIUM", "HIGH"]:
        """检查账户风险级别
        
        Args:
            account_id: 账户ID
            
        Returns:
            风险级别: "LOW", "MEDIUM", "HIGH"
        """
        try:
            # 获取账户持仓
            positions = await self.account_manager.get_positions(account_id)
            
            # 获取账户杠杆借贷信息
            leverage_info = await self.account_manager.get_leverage_loan_info(account_id)
            
            # 计算杠杆率
            leverage_ratio = 1.0  # 默认值
            if leverage_info and "margin_positions" in leverage_info:
                for pos in leverage_info["margin_positions"]:
                    if float(pos.get("leverage", 1.0)) > leverage_ratio:
                        leverage_ratio = float(pos["leverage"])
            
            # 检查持仓风险
            for position in positions:
                # 检查清算价格风险
                if position.liquidation_price:
                    current_price = await self.market_data.get_price(position.symbol)
                    
                    # 计算距离清算价格的百分比
                    if position.side == "long":
                        liquidation_distance = (current_price - position.liquidation_price) / current_price
                    else:  # short
                        liquidation_distance = (position.liquidation_price - current_price) / current_price
                    
                    if liquidation_distance < 0.05:  # 距离清算价格小于5%
                        self.account_risk_levels[account_id] = "HIGH"
                        return "HIGH"
                    elif liquidation_distance < 0.15:  # 距离清算价格小于15%
                        self.account_risk_levels[account_id] = "MEDIUM"
                        return "MEDIUM"
            
            # 检查杠杆率
            max_leverage_ratio = self.risk_config.get("max_leverage_ratio", 10)
            if leverage_ratio > max_leverage_ratio:
                self.account_risk_levels[account_id] = "HIGH"
                return "HIGH"
            elif leverage_ratio > max_leverage_ratio * 0.7:  # 70%的最大杠杆率
                self.account_risk_levels[account_id] = "MEDIUM"
                return "MEDIUM"
            
            # 如果没有高风险指标，返回LOW
            self.account_risk_levels[account_id] = "LOW"
            return "LOW"
            
        except Exception as e:
            self.logger.error(f"检查账户 {account_id} 风险级别时出错: {e}")
            # 发生错误时，保守起见返回MEDIUM
            self.account_risk_levels[account_id] = "MEDIUM"
            return "MEDIUM"
    
    async def monitor_market_conditions(self) -> Literal["NORMAL", "VOLATILE", "EXTREME"]:
        """监控市场条件
        
        Returns:
            市场状态: "NORMAL", "VOLATILE", "EXTREME"
        """
        try:
            # 获取BTC价格
            btc_price = await self.market_data.get_price("BTC/USDT")
            
            # 获取资金费率
            funding_rate = await self.market_data.get_funding_rate("BTC/USD")
            
            # 检查资金费率是否异常
            min_funding_rate = self.risk_config.get("min_funding_rate", -0.01)
            emergency_exit_threshold = self.risk_config.get("emergency_exit_threshold", -0.02)
            
            if funding_rate < emergency_exit_threshold:
                return "EXTREME"
            elif funding_rate < min_funding_rate:
                return "VOLATILE"
            
            # 后续可以增加其他市场指标检查，如波动率等
            
            return "NORMAL"
            
        except Exception as e:
            self.logger.error(f"监控市场条件时出错: {e}")
            # 发生错误时，保守起见返回VOLATILE
            return "VOLATILE"
    
    async def enforce_risk_limits(self, account_id: str) -> None:
        """强制执行风险限制
        
        Args:
            account_id: 账户ID
        """
        self.logger.info(f"为账户 {account_id} 强制执行风险限制")
        
        try:
            risk_level = self.account_risk_levels.get(account_id, "MEDIUM")
            
            if risk_level == "HIGH":
                # 减仓或平仓
                positions = await self.account_manager.get_positions(account_id)
                
                for position in positions:
                    # 对高杠杆位置进行减仓
                    if position.leverage > self.risk_config.get("max_leverage_ratio", 10):
                        # 这里简化处理，直接平掉一半仓位
                        from ..execution.service import ExecutionService
                        execution_service = ExecutionService(self.config)
                        await execution_service.initialize()
                        
                        try:
                            await execution_service.close_position(
                                account_id=account_id,
                                symbol=position.symbol,
                                amount=position.amount * 0.5  # 平掉一半仓位
                            )
                            self.logger.info(f"已为账户 {account_id} 减仓 {position.symbol} 50%")
                        finally:
                            await execution_service.close()
                
                await self._send_alert(
                    message=f"已为账户 {account_id} 执行风险限制措施，减仓50%",
                    level="WARNING",
                    channels=["telegram"]
                )
                
        except Exception as e:
            self.logger.error(f"为账户 {account_id} 强制执行风险限制时出错: {e}")
            await self._send_alert(
                message=f"为账户 {account_id} 执行风险限制失败: {e}",
                level="ERROR",
                channels=["telegram", "email"]
            )
    
    async def trigger_emergency_stop(self, reason: str) -> None:
        """触发紧急停止
        
        Args:
            reason: 停止原因
        """
        self.logger.critical(f"触发紧急停止，原因: {reason}")
        
        try:
            # 发送紧急告警
            await self._send_alert(
                message=f"触发紧急停止，原因: {reason}",
                level="CRITICAL",
                channels=["telegram", "email"]
            )
            
            # 这里应该实现紧急停止逻辑，如平仓所有持仓等
            # 由于涉及到其他模块，实际实现时需要考虑如何优雅地处理
            
            # 停止监控
            await self.stop_monitoring()
            
        except Exception as e:
            self.logger.critical(f"执行紧急停止时出错: {e}")
            # 尝试再次发送告警
            await self._send_alert(
                message=f"执行紧急停止失败: {e}",
                level="CRITICAL",
                channels=["telegram", "email"]
            )
    
    async def handle_account_error(self, account_id: str, error_message: str) -> None:
        """处理账户错误
        
        Args:
            account_id: 账户ID
            error_message: 错误信息
        """
        self.logger.error(f"账户 {account_id} 发生错误: {error_message}")
        
        try:
            # 发送告警
            await self._send_alert(
                message=f"账户 {account_id} 发生错误: {error_message}",
                level="ERROR",
                channels=["telegram"]
            )
            
            # 更新账户风险级别
            self.account_risk_levels[account_id] = "HIGH"
            
            # 检查是否需要执行风险限制
            await self.enforce_risk_limits(account_id)
            
        except Exception as e:
            self.logger.error(f"处理账户 {account_id} 错误时出错: {e}")
    
    async def handle_operation_failure(self, account_id: str, operation_results: Dict) -> None:
        """处理操作失败
        
        Args:
            account_id: 账户ID
            operation_results: 操作结果
        """
        self.logger.error(f"账户 {account_id} 操作失败: {operation_results}")
        
        try:
            # 构建失败详情
            failure_details = []
            for op_id, result in operation_results.items():
                if not result.get("success", False):
                    failure_details.append(f"{op_id}: {result.get('error', '未知错误')}")
            
            # 发送告警
            await self._send_alert(
                message=f"账户 {account_id} 操作失败:\n" + "\n".join(failure_details),
                level="ERROR",
                channels=["telegram"]
            )
            
            # 更新账户风险级别
            self.account_risk_levels[account_id] = "HIGH"
            
            # 检查是否需要执行风险限制
            await self.enforce_risk_limits(account_id)
            
        except Exception as e:
            self.logger.error(f"处理账户 {account_id} 操作失败时出错: {e}")
    
    async def _send_alert(self, message: str, level: str, channels: List[str]) -> None:
        """发送告警
        
        Args:
            message: 告警消息
            level: 告警级别
            channels: 告警渠道列表
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alert_message = f"[{level}] {timestamp}\n{message}"
        
        for channel in channels:
            if channel in self.alert_handlers:
                try:
                    await self.alert_handlers[channel].send_alert(alert_message)
                    self.logger.info(f"已通过 {channel} 发送告警")
                except Exception as e:
                    self.logger.error(f"通过 {channel} 发送告警失败: {e}")
