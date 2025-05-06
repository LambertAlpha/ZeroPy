#!/usr/bin/env python
"""
资金费率套利策略系统 - 主应用入口

该模块是整个系统的主入口，负责初始化和协调各个模块的运行。
"""
import asyncio
import logging
import os
import signal
import sys
from typing import Dict, Any

import yaml

from src.modules.market_data.service import MarketDataService
from src.modules.account.manager import AccountManager
from src.modules.execution.service import ExecutionService
from src.modules.strategy.engine import StrategyEngine
from src.modules.risk.monitor import RiskMonitor
from src.modules.state.manager import StateManager
from src.utils.logger import setup_logger
from src.utils.metrics import setup_metrics


class Application:
    """主应用类，负责系统初始化和生命周期管理"""
    
    def __init__(self, config_path: str = "config/default.yaml"):
        """初始化应用实例
        
        Args:
            config_path: 配置文件路径
        """
        self.config = self._load_config(config_path)
        self.logger = setup_logger(self.config["logging"])
        self.logger.info("系统初始化开始...")
        
        # 初始化各个服务模块
        self.market_data_service = MarketDataService(self.config)
        self.account_manager = AccountManager(self.config)
        self.execution_service = ExecutionService(self.config)
        self.state_manager = StateManager(self.config)
        self.risk_monitor = RiskMonitor(self.config)
        
        # 策略引擎依赖其他所有服务
        self.strategy_engine = StrategyEngine(
            config=self.config,
            market_data=self.market_data_service,
            account_manager=self.account_manager,
            execution_service=self.execution_service,
            state_manager=self.state_manager,
            risk_monitor=self.risk_monitor
        )
        
        # 设置指标和监控
        self.metrics = setup_metrics(self.config["monitoring"])
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        self.is_running = False
        self.logger.info("系统初始化完成")
    
    @staticmethod
    def _load_config(config_path: str) -> Dict[str, Any]:
        """加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置字典
        """
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                return yaml.safe_load(file)
        except Exception as e:
            print(f"配置文件加载失败: {e}")
            sys.exit(1)
    
    async def start(self):
        """启动应用"""
        self.logger.info("系统启动中...")
        self.is_running = True
        
        # 初始化数据库连接
        await self.state_manager.initialize()
        
        # 初始化交易所连接
        await self.market_data_service.initialize()
        await self.account_manager.initialize()
        await self.execution_service.initialize()
        
        # 启动风险监控
        await self.risk_monitor.start_monitoring()
        
        # 运行策略
        await self.strategy_engine.initialize_strategy(self.config["strategy"])
        await self.run_strategy_loop()
    
    async def run_strategy_loop(self):
        """运行策略主循环"""
        self.logger.info("策略循环开始运行")
        try:
            while self.is_running:
                await self.strategy_engine.execute_strategy_cycle()
                await asyncio.sleep(1)  # 主循环间隔
        except Exception as e:
            self.logger.error(f"策略循环异常: {e}")
            await self.shutdown()
    
    def _handle_shutdown(self, sig, frame):
        """处理关闭信号"""
        self.logger.info(f"接收到关闭信号: {sig}")
        asyncio.create_task(self.shutdown())
    
    async def shutdown(self):
        """关闭应用"""
        self.logger.info("系统正在关闭...")
        self.is_running = False
        
        # 关闭各个模块
        await self.risk_monitor.stop_monitoring()
        await self.market_data_service.close()
        await self.account_manager.close()
        await self.execution_service.close()
        await self.state_manager.close()
        
        self.logger.info("系统已安全关闭")


async def main():
    """主函数"""
    # 确定配置文件路径
    config_path = os.environ.get("CONFIG_PATH", "config/default.yaml")
    
    # 创建并启动应用
    app = Application(config_path)
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())
