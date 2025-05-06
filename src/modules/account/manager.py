"""
账户管理模块

负责管理多个交易子账户，跟踪余额和持仓
"""
import logging
from typing import Dict, Any, List, Optional
import ccxt.async_support as ccxt
from datetime import datetime

from ...models.account import Position


class AccountManager:
    """账户管理器，负责管理多个交易子账户"""

    def __init__(self, config: Dict[str, Any]):
        """初始化账户管理器
        
        Args:
            config: 系统配置
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.exchanges = {}
        self.accounts = {}  # 存储账户信息的缓存
        self.positions_cache = {}  # 存储持仓信息的缓存
        self.balance_cache = {}  # 存储余额信息的缓存
    
    async def initialize(self):
        """初始化账户管理器，连接各交易所"""
        self.logger.info("初始化账户管理器")
        
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
                
                self.logger.info(f"账户管理器成功连接交易所: {exchange_id}")
                
                # 初始化账户信息
                await self._initialize_accounts(exchange_id)
                
            except Exception as e:
                self.logger.error(f"账户管理器连接交易所 {exchange_id} 失败: {e}")
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
    
    async def _initialize_accounts(self, exchange_id: str):
        """初始化交易所的账户信息
        
        Args:
            exchange_id: 交易所ID
        """
        try:
            exchange = self.exchanges[exchange_id]
            
            # 检查交易所是否支持子账户
            if hasattr(exchange, 'fetch_sub_accounts'):
                sub_accounts = await exchange.fetch_sub_accounts()
                self.logger.info(f"交易所 {exchange_id} 拥有 {len(sub_accounts)} 个子账户")
                
                # 存储子账户信息
                for account in sub_accounts:
                    account_id = account['id']
                    self.accounts[account_id] = {
                        'exchange_id': exchange_id,
                        'info': account,
                        'last_updated': datetime.now()
                    }
            else:
                # 如果不支持子账户，则将主账户视为唯一账户
                balance = await exchange.fetch_balance()
                main_account_id = f"{exchange_id}_main"
                self.accounts[main_account_id] = {
                    'exchange_id': exchange_id,
                    'info': {'id': main_account_id, 'name': '主账户'},
                    'balance': balance,
                    'last_updated': datetime.now()
                }
                self.logger.info(f"交易所 {exchange_id} 使用主账户: {main_account_id}")
                
        except Exception as e:
            self.logger.error(f"初始化交易所 {exchange_id} 的账户信息失败: {e}")
            raise
    
    async def get_account_balance(self, account_id: str, asset: str) -> float:
        """获取账户特定资产的余额
        
        Args:
            account_id: 账户ID
            asset: 资产符号，例如 "BTC", "USDT"
            
        Returns:
            资产余额
        """
        # 检查缓存是否有最新数据
        cache_key = f"{account_id}_{asset}"
        cached_balance = self.balance_cache.get(cache_key)
        current_time = datetime.now().timestamp()
        
        # 如果缓存有效且在30秒内，直接返回缓存数据
        if cached_balance and current_time - cached_balance["timestamp"] < 30:
            return cached_balance["amount"]
        
        try:
            # 获取账户所属的交易所
            if account_id not in self.accounts:
                raise ValueError(f"账户 {account_id} 不存在")
            
            exchange_id = self.accounts[account_id]['exchange_id']
            exchange = self.exchanges[exchange_id]
            
            # 根据交易所API获取余额
            if hasattr(exchange, 'fetch_balance_by_account_id'):
                # 如果交易所API支持直接按账户ID查询
                balance = await exchange.fetch_balance_by_account_id(account_id)
            else:
                # 否则获取主账户余额
                balance = await exchange.fetch_balance()
            
            # 提取特定资产的余额
            asset_balance = 0.0
            if asset in balance and 'free' in balance[asset]:
                asset_balance = float(balance[asset]['free'])
            
            # 更新缓存
            self.balance_cache[cache_key] = {
                "amount": asset_balance,
                "timestamp": current_time
            }
            
            return asset_balance
            
        except Exception as e:
            self.logger.error(f"获取账户 {account_id} 的 {asset} 余额失败: {e}")
            # 如果有缓存数据，返回缓存
            if cached_balance:
                self.logger.warning(f"返回账户 {account_id} 的 {asset} 缓存余额数据")
                return cached_balance["amount"]
            raise
    
    async def get_positions(self, account_id: str) -> List[Position]:
        """获取账户的持仓信息
        
        Args:
            account_id: 账户ID
            
        Returns:
            持仓列表
        """
        # 检查缓存是否有最新数据
        cached_positions = self.positions_cache.get(account_id)
        current_time = datetime.now().timestamp()
        
        # 如果缓存有效且在30秒内，直接返回缓存数据
        if cached_positions and current_time - cached_positions["timestamp"] < 30:
            return cached_positions["positions"]
        
        try:
            # 获取账户所属的交易所
            if account_id not in self.accounts:
                raise ValueError(f"账户 {account_id} 不存在")
            
            exchange_id = self.accounts[account_id]['exchange_id']
            exchange = self.exchanges[exchange_id]
            
            # 获取持仓信息
            positions = []
            
            # 检查交易所API是否支持获取持仓
            if hasattr(exchange, 'fetch_positions'):
                # 先获取合约市场持仓
                if hasattr(exchange, 'options'):
                    original_market_type = exchange.options.get('defaultType', 'spot')
                    exchange.options['defaultType'] = 'swap'  # 或 'future'，取决于交易所
                
                raw_positions = await exchange.fetch_positions()
                
                # 恢复原来的市场类型
                if hasattr(exchange, 'options') and 'defaultType' in exchange.options:
                    exchange.options['defaultType'] = original_market_type
                
                # 处理持仓数据
                for pos in raw_positions:
                    if float(pos.get('contracts', 0)) > 0:
                        position = Position(
                            symbol=pos['symbol'],
                            side="long" if float(pos.get('side', 0)) > 0 else "short",
                            amount=float(pos.get('contracts', 0)),
                            entry_price=float(pos.get('entryPrice', 0)),
                            leverage=float(pos.get('leverage', 1)),
                            margin_type=pos.get('marginType', 'cross'),
                            liquidation_price=float(pos.get('liquidationPrice', 0)),
                            unrealized_pnl=float(pos.get('unrealizedPnl', 0)),
                            is_coin_margined=pos.get('marginMode', '') == 'coin'
                        )
                        positions.append(position)
            
            # 可能还需要获取现货杠杆持仓
            if hasattr(exchange, 'fetch_lending_positions'):
                lending_positions = await exchange.fetch_lending_positions()
                # 处理杠杆持仓数据...
            
            # 更新缓存
            self.positions_cache[account_id] = {
                "positions": positions,
                "timestamp": current_time
            }
            
            return positions
            
        except Exception as e:
            self.logger.error(f"获取账户 {account_id} 的持仓信息失败: {e}")
            # 如果有缓存数据，返回缓存
            if cached_positions:
                self.logger.warning(f"返回账户 {account_id} 的缓存持仓数据")
                return cached_positions["positions"]
            raise
    
    async def transfer_asset(self, from_account: str, to_account: str, asset: str, amount: float) -> bool:
        """在账户之间转移资产
        
        Args:
            from_account: 源账户ID
            to_account: 目标账户ID
            asset: 资产符号
            amount: 转移金额
            
        Returns:
            转移是否成功
        """
        try:
            # 检查源账户和目标账户
            if from_account not in self.accounts:
                raise ValueError(f"源账户 {from_account} 不存在")
            if to_account not in self.accounts:
                raise ValueError(f"目标账户 {to_account} 不存在")
            
            # 获取源账户所属的交易所
            from_exchange_id = self.accounts[from_account]['exchange_id']
            to_exchange_id = self.accounts[to_account]['exchange_id']
            
            # 检查是否在同一交易所
            if from_exchange_id != to_exchange_id:
                raise ValueError(f"不支持跨交易所转账: {from_exchange_id} -> {to_exchange_id}")
            
            exchange = self.exchanges[from_exchange_id]
            
            # 执行转账
            if hasattr(exchange, 'transfer'):
                result = await exchange.transfer(
                    asset,
                    amount,
                    from_account.replace(f"{from_exchange_id}_", ""),  # 去除交易所前缀
                    to_account.replace(f"{to_exchange_id}_", "")       # 去除交易所前缀
                )
                
                # 清除缓存
                for cache_key in list(self.balance_cache.keys()):
                    if cache_key.startswith(f"{from_account}_") or cache_key.startswith(f"{to_account}_"):
                        del self.balance_cache[cache_key]
                
                self.logger.info(f"成功转移 {amount} {asset} 从 {from_account} 到 {to_account}")
                return True
            else:
                raise NotImplementedError(f"交易所 {from_exchange_id} 不支持子账户间转账")
                
        except Exception as e:
            self.logger.error(f"转移资产失败: {e}")
            return False
    
    async def get_leverage_loan_info(self, account_id: str) -> Dict:
        """获取杠杆借贷信息
        
        Args:
            account_id: 账户ID
            
        Returns:
            杠杆借贷信息
        """
        try:
            # 检查账户
            if account_id not in self.accounts:
                raise ValueError(f"账户 {account_id} 不存在")
            
            # 获取账户所属的交易所
            exchange_id = self.accounts[account_id]['exchange_id']
            exchange = self.exchanges[exchange_id]
            
            # 获取杠杆借贷信息
            if hasattr(exchange, 'fetch_borrow_interest'):
                borrow_info = await exchange.fetch_borrow_interest()
                return borrow_info
            else:
                # 尝试获取借贷信息的替代API
                if hasattr(exchange, 'fetch_borrowed_currencies'):
                    borrowed = await exchange.fetch_borrowed_currencies()
                    return borrowed
                elif hasattr(exchange, 'fetch_margin_positions'):
                    margin_positions = await exchange.fetch_margin_positions()
                    return {'margin_positions': margin_positions}
                else:
                    raise NotImplementedError(f"交易所 {exchange_id} 不支持查询杠杆借贷信息")
                
        except Exception as e:
            self.logger.error(f"获取账户 {account_id} 的杠杆借贷信息失败: {e}")
            raise
    
    async def close(self):
        """关闭账户管理器"""
        self.logger.info("关闭账户管理器")
        
        # 关闭所有交易所连接
        for exchange_id, exchange in self.exchanges.items():
            try:
                await exchange.close()
                self.logger.info(f"已关闭账户管理器的交易所 {exchange_id} 连接")
            except Exception as e:
                self.logger.error(f"关闭账户管理器的交易所 {exchange_id} 连接时出错: {e}")
