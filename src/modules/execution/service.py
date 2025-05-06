"""
交易执行模块

负责执行各类交易操作，确保操作可靠和高效
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional
import ccxt.async_support as ccxt
from datetime import datetime

from ...models.order import Order, Operation, Result


class ExecutionService:
    """交易执行服务，负责执行各类交易操作"""

    def __init__(self, config: Dict[str, Any]):
        """初始化交易执行服务
        
        Args:
            config: 系统配置
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.exchanges = {}
        self.order_cache = {}
    
    async def initialize(self):
        """初始化交易执行服务，连接各交易所"""
        self.logger.info("初始化交易执行服务")
        
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
                    'enableRateLimit': True
                })
                
                # 如果配置为测试网络，设置测试网络
                if exchange_config.get("testnet", False):
                    if hasattr(self.exchanges[exchange_id], 'set_sandbox_mode'):
                        self.exchanges[exchange_id].set_sandbox_mode(True)
                
                self.logger.info(f"交易执行服务成功连接交易所: {exchange_id}")
                
            except Exception as e:
                self.logger.error(f"交易执行服务连接交易所 {exchange_id} 失败: {e}")
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
    
    def _get_exchange_for_account(self, account_id: str) -> ccxt.Exchange:
        """获取账户对应的交易所实例
        
        Args:
            account_id: 账户ID
            
        Returns:
            交易所实例
            
        Raises:
            ValueError: 如果账户对应的交易所未连接
        """
        # 简单实现，根据账户ID前缀确定交易所
        for exchange_id, exchange in self.exchanges.items():
            if account_id.startswith(exchange_id):
                return exchange
        
        raise ValueError(f"无法找到账户 {account_id} 对应的交易所")
    
    async def spot_leverage_buy(self, account_id: str, symbol: str, amount: float, leverage: int) -> Order:
        """杠杆现货买入
        
        Args:
            account_id: 账户ID
            symbol: 交易对符号，例如 "BTC/USDT"
            amount: 买入数量
            leverage: 杠杆倍数
            
        Returns:
            订单信息
        """
        try:
            exchange = self._get_exchange_for_account(account_id)
            
            # 设置杠杆
            if hasattr(exchange, 'set_leverage'):
                await exchange.set_leverage(leverage, symbol)
            
            # 设置保证金模式
            if hasattr(exchange, 'set_margin_mode'):
                await exchange.set_margin_mode('cross', symbol)  # 使用全仓模式
            
            # 执行买入操作
            if hasattr(exchange, 'create_margin_order'):
                result = await exchange.create_margin_order(
                    symbol=symbol,
                    type='market',
                    side='buy',
                    amount=amount,
                    params={'leverage': leverage}
                )
            else:
                # 先设置为杠杆交易
                if hasattr(exchange, 'options'):
                    original_market_type = exchange.options.get('defaultType', 'spot')
                    exchange.options['defaultType'] = 'margin'
                
                result = await exchange.create_market_buy_order(
                    symbol=symbol,
                    amount=amount,
                    params={'leverage': leverage}
                )
                
                # 恢复原来的市场类型
                if hasattr(exchange, 'options') and 'defaultType' in exchange.options:
                    exchange.options['defaultType'] = original_market_type
            
            # 构建订单对象
            order = Order(
                order_id=result['id'],
                account_id=account_id,
                symbol=symbol,
                side='buy',
                type='market',
                amount=amount,
                price=result.get('price'),
                status=result['status'],
                filled=result.get('filled', 0),
                remaining=result.get('remaining', amount),
                timestamp=datetime.now()
            )
            
            self.logger.info(f"账户 {account_id} 杠杆现货买入 {amount} {symbol} 成功，订单ID: {order.order_id}")
            return order
            
        except Exception as e:
            self.logger.error(f"账户 {account_id} 杠杆现货买入 {amount} {symbol} 失败: {e}")
            raise
    
    async def futures_short(self, account_id: str, symbol: str, amount: float, is_coin_margined: bool = False) -> Order:
        """期货做空
        
        Args:
            account_id: 账户ID
            symbol: 交易对符号，例如 "BTC/USDT"
            amount: 做空数量
            is_coin_margined: 是否是币本位合约，默认为U本位
            
        Returns:
            订单信息
        """
        try:
            exchange = self._get_exchange_for_account(account_id)
            
            # 设置合约类型
            contract_type = 'swap'  # 永续合约
            if hasattr(exchange, 'options'):
                original_market_type = exchange.options.get('defaultType', 'spot')
                if is_coin_margined:
                    exchange.options['defaultType'] = 'delivery'  # 币本位通常是交割合约
                else:
                    exchange.options['defaultType'] = 'swap'  # U本位通常是永续合约
            
            # 设置杠杆
            if hasattr(exchange, 'set_leverage'):
                await exchange.set_leverage(5, symbol)  # 默认使用5倍杠杆
            
            # 设置保证金模式
            if hasattr(exchange, 'set_margin_mode'):
                await exchange.set_margin_mode('cross', symbol)  # 使用全仓模式
            
            # 执行做空操作
            result = await exchange.create_market_sell_order(
                symbol=symbol,
                amount=amount,
                params={
                    'reduceOnly': False,
                    'margin': is_coin_margined,
                }
            )
            
            # 恢复原来的市场类型
            if hasattr(exchange, 'options') and 'defaultType' in exchange.options:
                exchange.options['defaultType'] = original_market_type
            
            # 构建订单对象
            order = Order(
                order_id=result['id'],
                account_id=account_id,
                symbol=symbol,
                side='sell',
                type='market',
                amount=amount,
                price=result.get('price'),
                status=result['status'],
                filled=result.get('filled', 0),
                remaining=result.get('remaining', amount),
                timestamp=datetime.now()
            )
            
            contract_type_str = "币本位" if is_coin_margined else "U本位"
            self.logger.info(f"账户 {account_id} {contract_type_str}合约做空 {amount} {symbol} 成功，订单ID: {order.order_id}")
            return order
            
        except Exception as e:
            contract_type_str = "币本位" if is_coin_margined else "U本位"
            self.logger.error(f"账户 {account_id} {contract_type_str}合约做空 {amount} {symbol} 失败: {e}")
            raise
    
    async def close_position(self, account_id: str, symbol: str, amount: float, limit_price: Optional[float] = None) -> Order:
        """平仓操作
        
        Args:
            account_id: 账户ID
            symbol: 交易对符号，例如 "BTC/USDT"
            amount: 平仓数量
            limit_price: 限价，如果为None则执行市价平仓
            
        Returns:
            订单信息
        """
        try:
            exchange = self._get_exchange_for_account(account_id)
            
            # 获取当前持仓方向
            positions = await exchange.fetch_positions([symbol])
            
            if not positions or not len(positions):
                raise ValueError(f"账户 {account_id} 没有 {symbol} 的持仓")
            
            position = positions[0]
            is_long = position['side'] == 'long'
            
            # 设置市场类型
            if hasattr(exchange, 'options'):
                if 'future' in position.get('info', {}).get('marginType', ''):
                    exchange.options['defaultType'] = 'delivery'  # 币本位合约
                else:
                    exchange.options['defaultType'] = 'swap'  # U本位合约
            
            # 执行平仓操作
            order_type = 'limit' if limit_price else 'market'
            side = 'sell' if is_long else 'buy'  # 多头平仓为卖出，空头平仓为买入
            
            params = {
                'reduceOnly': True,  # 仅减仓
                'closePosition': True  # 平仓标志
            }
            
            if order_type == 'limit':
                if is_long:
                    result = await exchange.create_limit_sell_order(
                        symbol=symbol,
                        amount=amount,
                        price=limit_price,
                        params=params
                    )
                else:
                    result = await exchange.create_limit_buy_order(
                        symbol=symbol,
                        amount=amount,
                        price=limit_price,
                        params=params
                    )
            else:
                if is_long:
                    result = await exchange.create_market_sell_order(
                        symbol=symbol,
                        amount=amount,
                        params=params
                    )
                else:
                    result = await exchange.create_market_buy_order(
                        symbol=symbol,
                        amount=amount,
                        params=params
                    )
            
            # 构建订单对象
            order = Order(
                order_id=result['id'],
                account_id=account_id,
                symbol=symbol,
                side=side,
                type=order_type,
                amount=amount,
                price=limit_price if order_type == 'limit' else result.get('price'),
                status=result['status'],
                filled=result.get('filled', 0),
                remaining=result.get('remaining', amount),
                timestamp=datetime.now()
            )
            
            position_type = "多头" if is_long else "空头"
            order_type_str = "限价" if order_type == 'limit' else "市价"
            self.logger.info(f"账户 {account_id} {order_type_str}平仓 {position_type} {amount} {symbol} 成功，订单ID: {order.order_id}")
            return order
            
        except Exception as e:
            self.logger.error(f"账户 {account_id} 平仓 {amount} {symbol} 失败: {e}")
            raise
    
    async def repay_leverage_loan(self, account_id: str, asset: str, amount: float) -> bool:
        """偿还杠杆借款
        
        Args:
            account_id: 账户ID
            asset: 资产符号，例如 "BTC", "USDT"
            amount: 偿还金额
            
        Returns:
            是否偿还成功
        """
        try:
            exchange = self._get_exchange_for_account(account_id)
            
            # 切换到杠杆市场
            if hasattr(exchange, 'options'):
                original_market_type = exchange.options.get('defaultType', 'spot')
                exchange.options['defaultType'] = 'margin'
            
            # 执行偿还操作
            if hasattr(exchange, 'repay_margin'):
                result = await exchange.repay_margin(asset, amount)
            elif hasattr(exchange, 'margin_repay'):
                result = await exchange.margin_repay(asset, amount)
            else:
                raise NotImplementedError(f"交易所 {exchange.__class__.__name__} 不支持杠杆偿还操作")
            
            # 恢复原来的市场类型
            if hasattr(exchange, 'options') and 'defaultType' in exchange.options:
                exchange.options['defaultType'] = original_market_type
            
            self.logger.info(f"账户 {account_id} 成功偿还 {amount} {asset} 的杠杆借款")
            return True
            
        except Exception as e:
            self.logger.error(f"账户 {account_id} 偿还 {amount} {asset} 的杠杆借款失败: {e}")
            return False
    
    async def execute_critical_operations(self, account_id: str, operations: List[Operation]) -> Dict[str, Result]:
        """同步执行关键操作
        
        Args:
            account_id: 账户ID
            operations: 操作列表
            
        Returns:
            操作结果字典
        """
        results = {}
        
        try:
            self.logger.info(f"账户 {account_id} 开始执行 {len(operations)} 个关键操作")
            
            # 记录开始时间
            start_time = datetime.now()
            
            # 批量执行所有操作
            for i, operation in enumerate(operations):
                op_key = f"op_{i}_{operation['type']}"
                try:
                    if operation['type'] == 'close_position':
                        order = await self.close_position(
                            account_id=account_id,
                            symbol=operation['symbol'],
                            amount=operation.get('amount', 0),
                            limit_price=operation.get('limit_price')
                        )
                        results[op_key] = Result(
                            operation_id=op_key,
                            success=True,
                            result_data={"order_id": order.order_id, "status": order.status}
                        )
                    
                    elif operation['type'] == 'repay_loan':
                        success = await self.repay_leverage_loan(
                            account_id=account_id,
                            asset=operation['asset'],
                            amount=operation['amount']
                        )
                        results[op_key] = Result(
                            operation_id=op_key,
                            success=success,
                            result_data={"repaid": operation['amount'] if success else 0}
                        )
                    
                    elif operation['type'] == 'open_coin_margin_short':
                        order = await self.futures_short(
                            account_id=account_id,
                            symbol=operation['symbol'],
                            amount=operation['amount'],
                            is_coin_margined=True
                        )
                        results[op_key] = Result(
                            operation_id=op_key,
                            success=True,
                            result_data={"order_id": order.order_id, "status": order.status}
                        )
                    
                    else:
                        results[op_key] = Result(
                            operation_id=op_key,
                            success=False,
                            error=f"不支持的操作类型: {operation['type']}"
                        )
                
                except Exception as e:
                    self.logger.error(f"账户 {account_id} 执行操作 {operation['type']} 失败: {e}")
                    results[op_key] = Result(
                        operation_id=op_key,
                        success=False,
                        error=str(e)
                    )
            
            # 计算总执行时间
            execution_time = (datetime.now() - start_time).total_seconds() * 1000  # 毫秒
            self.logger.info(f"账户 {account_id} 完成关键操作执行，耗时: {execution_time:.2f}ms")
            
            # 分析结果
            success_count = sum(1 for r in results.values() if r.success)
            self.logger.info(f"账户 {account_id} 关键操作执行结果: {success_count}/{len(operations)} 成功")
            
            return results
            
        except Exception as e:
            self.logger.error(f"账户 {account_id} 执行关键操作过程中发生错误: {e}")
            results["global_error"] = Result(
                operation_id="global_error",
                success=False,
                error=str(e)
            )
            return results
    
    async def set_conditional_orders(self, account_id: str, orders: List[Dict]) -> Dict[str, Order]:
        """设置条件单
        
        Args:
            account_id: 账户ID
            orders: 订单列表
            
        Returns:
            订单ID和订单对象的字典
        """
        results = {}
        
        for i, order_info in enumerate(orders):
            try:
                exchange = self._get_exchange_for_account(account_id)
                
                # 设置合适的市场类型
                if hasattr(exchange, 'options'):
                    # 根据符号判断是现货还是合约
                    if order_info['symbol'].endswith('USD'):
                        exchange.options['defaultType'] = 'swap'  # 或 'future'，取决于交易所
                
                # 创建条件单
                if not hasattr(exchange, 'create_order'):
                    raise NotImplementedError(f"交易所 {exchange.__class__.__name__} 不支持创建条件单")
                
                params = {}
                if order_info.get('type') == 'limit':
                    params['price'] = order_info['price']
                
                if order_info.get('trigger_price'):
                    params['triggerPrice'] = order_info['trigger_price']
                    params['stopPrice'] = order_info['trigger_price']
                
                # 添加其他参数
                if 'params' in order_info:
                    params.update(order_info['params'])
                
                # 执行订单创建
                result = await exchange.create_order(
                    symbol=order_info['symbol'],
                    type=order_info['type'],
                    side=order_info['side'],
                    amount=order_info['amount'],
                    params=params
                )
                
                # 构建订单对象
                order = Order(
                    order_id=result['id'],
                    account_id=account_id,
                    symbol=order_info['symbol'],
                    side=order_info['side'],
                    type=order_info['type'],
                    amount=order_info['amount'],
                    price=order_info.get('price'),
                    status=result['status'],
                    filled=result.get('filled', 0),
                    remaining=result.get('remaining', order_info['amount']),
                    timestamp=datetime.now()
                )
                
                results[order.order_id] = order
                self.logger.info(f"账户 {account_id} 成功创建{order_info['type']}单: {order_info['side']} {order_info['amount']} {order_info['symbol']}")
                
            except Exception as e:
                self.logger.error(f"账户 {account_id} 创建条件单失败: {e}")
                # 创建一个失败的订单对象
                order = Order(
                    order_id=f"failed_{i}",
                    account_id=account_id,
                    symbol=order_info['symbol'],
                    side=order_info['side'],
                    type=order_info['type'],
                    amount=order_info['amount'],
                    price=order_info.get('price'),
                    status="failed",
                    filled=0,
                    remaining=order_info['amount'],
                    timestamp=datetime.now()
                )
                results[order.order_id] = order
        
        return results
    
    async def close(self):
        """关闭交易执行服务"""
        self.logger.info("关闭交易执行服务")
        
        # 关闭所有交易所连接
        for exchange_id, exchange in self.exchanges.items():
            try:
                await exchange.close()
                self.logger.info(f"已关闭交易执行服务的交易所 {exchange_id} 连接")
            except Exception as e:
                self.logger.error(f"关闭交易执行服务的交易所 {exchange_id} 连接时出错: {e}")
