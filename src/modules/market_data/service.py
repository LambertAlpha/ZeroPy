"""
市场数据服务模块

负责获取、处理、分析市场数据和资金费率
"""
import asyncio
import logging
from typing import Dict, Any, Callable, List, Optional
import ccxt.async_support as ccxt
from datetime import datetime


class MarketDataService:
    """市场数据服务，负责获取和处理交易所的市场数据"""

    def __init__(self, config: Dict[str, Any]):
        """初始化市场数据服务
        
        Args:
            config: 系统配置
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.exchanges = {}
        self.subscriptions = {}
        self.ws_connections = {}
        self.ticker_cache = {}
        
    async def initialize(self):
        """初始化市场数据服务，连接各交易所"""
        self.logger.info("初始化市场数据服务")
        
        for exchange_id, exchange_config in self.config["exchanges"].items():
            try:
                # 获取API密钥和密码
                api_key = self._get_env_var(exchange_config["api_key_env"])
                api_secret = self._get_env_var(exchange_config["api_secret_env"])
                
                # 创建交易所实例
                exchange_class = getattr(ccxt, exchange_id)
                self.exchanges[exchange_id] = exchange_class({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'timeout': 30000,
                    'enableRateLimit': True,
                    'options': {'defaultType': 'spot'}
                })
                
                # 如果配置为测试网络，设置测试网络
                if exchange_config.get("testnet", False):
                    if hasattr(self.exchanges[exchange_id], 'set_sandbox_mode'):
                        self.exchanges[exchange_id].set_sandbox_mode(True)
                
                self.logger.info(f"成功连接交易所: {exchange_id}")
            except Exception as e:
                self.logger.error(f"连接交易所 {exchange_id} 失败: {e}")
                raise
    
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
    
    async def get_ticker(self, symbol: str, exchange_id: str = None) -> Dict[str, Any]:
        """获取交易对的最新行情
        
        Args:
            symbol: 交易对符号，例如 "BTC/USDT"
            exchange_id: 交易所ID，默认使用配置中的第一个交易所
            
        Returns:
            ticker数据
        """
        if exchange_id is None:
            exchange_id = next(iter(self.exchanges.keys()))
        
        # 检查缓存是否有最新数据
        cache_key = f"{exchange_id}_{symbol}"
        cached_ticker = self.ticker_cache.get(cache_key)
        current_time = datetime.now().timestamp()
        
        # 如果缓存有效且在2秒内，直接返回缓存数据
        if cached_ticker and current_time - cached_ticker["timestamp"] < 2:
            return cached_ticker
        
        try:
            ticker = await self.exchanges[exchange_id].fetch_ticker(symbol)
            # 更新缓存
            self.ticker_cache[cache_key] = ticker
            return ticker
        except Exception as e:
            self.logger.error(f"获取 {symbol} 的行情数据失败: {e}")
            # 如果有缓存数据，返回缓存
            if cached_ticker:
                self.logger.warning(f"返回 {symbol} 的缓存行情数据")
                return cached_ticker
            raise
    
    async def get_price(self, symbol: str, exchange_id: str = None) -> float:
        """获取交易对的当前价格
        
        Args:
            symbol: 交易对符号，例如 "BTC/USDT"
            exchange_id: 交易所ID，默认使用配置中的第一个交易所
            
        Returns:
            当前价格
        """
        ticker = await self.get_ticker(symbol, exchange_id)
        return ticker["last"]
    
    async def get_funding_rate(self, symbol: str, exchange_id: str = None) -> float:
        """获取合约的资金费率
        
        Args:
            symbol: 交易对符号，例如 "BTC/USDT"
            exchange_id: 交易所ID，默认使用配置中的第一个交易所
            
        Returns:
            资金费率，正值表示多头付费，负值表示空头付费
        """
        if exchange_id is None:
            exchange_id = next(iter(self.exchanges.keys()))
        
        try:
            exchange = self.exchanges[exchange_id]
            # 确保使用合约市场
            if hasattr(exchange, 'options'):
                original_market_type = exchange.options.get('defaultType', 'spot')
                exchange.options['defaultType'] = 'swap'
            
            funding_rate_info = await exchange.fetch_funding_rate(symbol)
            
            # 恢复原来的市场类型
            if hasattr(exchange, 'options') and 'defaultType' in exchange.options:
                exchange.options['defaultType'] = original_market_type
            
            return funding_rate_info["fundingRate"]
        except Exception as e:
            self.logger.error(f"获取 {symbol} 的资金费率失败: {e}")
            raise
    
    async def subscribe_to_ticker(self, symbol: str, callback: Callable, exchange_id: str = None):
        """订阅行情数据更新
        
        Args:
            symbol: 交易对符号，例如 "BTC/USDT"
            callback: 当数据更新时调用的回调函数
            exchange_id: 交易所ID，默认使用配置中的第一个交易所
        """
        if exchange_id is None:
            exchange_id = next(iter(self.exchanges.keys()))
        
        # 创建订阅key
        sub_key = f"{exchange_id}_{symbol}"
        
        # 如果已经订阅，添加回调
        if sub_key in self.subscriptions:
            self.subscriptions[sub_key].append(callback)
            return
        
        # 创建新的订阅
        self.subscriptions[sub_key] = [callback]
        
        # 启动WebSocket连接
        asyncio.create_task(self._ticker_websocket_loop(symbol, exchange_id))
    
    async def _ticker_websocket_loop(self, symbol: str, exchange_id: str):
        """WebSocket订阅循环
        
        Args:
            symbol: 交易对符号
            exchange_id: 交易所ID
        """
        sub_key = f"{exchange_id}_{symbol}"
        
        # 检查交易所是否支持WebSocket
        exchange = self.exchanges[exchange_id]
        
        if not hasattr(exchange, 'watch_ticker'):
            self.logger.warning(f"交易所 {exchange_id} 不支持WebSocket订阅，将使用轮询")
            asyncio.create_task(self._ticker_polling_loop(symbol, exchange_id))
            return
        
        while sub_key in self.subscriptions and self.subscriptions[sub_key]:
            try:
                ticker = await exchange.watch_ticker(symbol)
                
                # 更新缓存
                self.ticker_cache[sub_key] = ticker
                
                # 调用所有回调
                for callback in self.subscriptions[sub_key]:
                    try:
                        asyncio.create_task(callback(ticker))
                    except Exception as e:
                        self.logger.error(f"调用 {symbol} 的ticker回调时出错: {e}")
                
            except Exception as e:
                self.logger.error(f"WebSocket订阅 {symbol} 出错: {e}")
                # 短暂延迟后重试
                await asyncio.sleep(5)
    
    async def _ticker_polling_loop(self, symbol: str, exchange_id: str):
        """轮询获取ticker数据
        
        Args:
            symbol: 交易对符号
            exchange_id: 交易所ID
        """
        sub_key = f"{exchange_id}_{symbol}"
        
        while sub_key in self.subscriptions and self.subscriptions[sub_key]:
            try:
                ticker = await self.get_ticker(symbol, exchange_id)
                
                # 调用所有回调
                for callback in self.subscriptions[sub_key]:
                    try:
                        asyncio.create_task(callback(ticker))
                    except Exception as e:
                        self.logger.error(f"调用 {symbol} 的ticker回调时出错: {e}")
                
            except Exception as e:
                self.logger.error(f"轮询 {symbol} 的ticker数据时出错: {e}")
            
            # 轮询间隔
            await asyncio.sleep(1)
    
    async def calculate_target_price(self, entry_price: float, loss_target: float) -> float:
        """计算达到目标亏损的价格
        
        Args:
            entry_price: 入场价格
            loss_target: 目标亏损金额
            
        Returns:
            目标价格
        """
        # 实际计算逻辑需要根据具体策略调整
        # 这里仅作为示例
        # 假设: 价格每变动1%，会导致亏损资金的0.5%
        loss_percentage = loss_target / (entry_price * 100)  # 计算亏损百分比
        price_change_percentage = loss_percentage / 0.5  # 根据杠杆计算价格变动百分比
        
        # 如果是多头亏损，价格下跌；如果是空头亏损，价格上涨
        # 这里假设我们是空头策略，价格上涨导致亏损
        target_price = entry_price * (1 + price_change_percentage)
        
        return target_price
    
    async def close(self):
        """关闭市场数据服务"""
        self.logger.info("关闭市场数据服务")
        
        # 关闭所有交易所连接
        for exchange_id, exchange in self.exchanges.items():
            try:
                await exchange.close()
                self.logger.info(f"已关闭交易所 {exchange_id} 连接")
            except Exception as e:
                self.logger.error(f"关闭交易所 {exchange_id} 连接时出错: {e}")
