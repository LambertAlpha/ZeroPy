"""
策略引擎模块

实现策略逻辑，协调各模块执行
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..market_data.service import MarketDataService
from ..account.manager import AccountManager
from ..execution.service import ExecutionService
from ..risk.monitor import RiskMonitor
from ..state.manager import StateManager
from ...models.strategy import StrategyState


class StrategyEngine:
    """策略引擎，实现资金费率套利策略逻辑"""

    def __init__(
        self,
        config: Dict[str, Any],
        market_data: MarketDataService,
        account_manager: AccountManager,
        execution_service: ExecutionService,
        state_manager: StateManager,
        risk_monitor: RiskMonitor
    ):
        """初始化策略引擎
        
        Args:
            config: 系统配置
            market_data: 市场数据服务
            account_manager: 账户管理器
            execution_service: 交易执行服务
            state_manager: 状态管理器
            risk_monitor: 风险监控器
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.market_data = market_data
        self.account_manager = account_manager
        self.execution_service = execution_service
        self.state_manager = state_manager
        self.risk_monitor = risk_monitor
        
        self.strategy_config = None
        self.strategy_state = None
        self.is_running = False
        self.monitoring_tasks = {}
    
    async def initialize_strategy(self, strategy_config: Dict) -> None:
        """初始化策略
        
        Args:
            strategy_config: 策略配置
        """
        self.logger.info("初始化资金费率套利策略")
        self.strategy_config = strategy_config
        
        # 加载策略状态
        self.strategy_state = await self.state_manager.load_strategy_state()
        if not self.strategy_state:
            # 创建新的策略状态
            self.strategy_state = StrategyState(
                is_active=False,
                accounts_status={},
                started_at=datetime.now(),
                last_updated=datetime.now()
            )
            await self.state_manager.save_strategy_state(self.strategy_state)
        
        # 检查是否需要初始化账户
        if not self.strategy_state.accounts_status:
            await self._initialize_accounts()
        
        self.is_running = True
        self.logger.info("策略初始化完成")
    
    async def _initialize_accounts(self) -> None:
        """初始化所有子账户"""
        self.logger.info("开始初始化子账户")
        
        # 获取配置
        accounts_count = self.strategy_config.get("accounts_count", 20)
        account_capital = self.strategy_config.get("account_capital", 10000)
        
        # 获取主账户ID (简化处理，假设第一个是主账户)
        exchange_id = next(iter(self.config["exchanges"].keys()))
        master_account_id = f"{exchange_id}_main"
        
        # 为简化演示，假设子账户已经在交易所创建
        for i in range(accounts_count):
            account_id = f"{exchange_id}_sub_{i+1}"
            
            # 链式设置下一个账户
            next_account_id = f"{exchange_id}_sub_{i+2}" if i < accounts_count - 1 else None
            
            # 更新策略状态
            self.strategy_state.accounts_status[account_id] = {
                "status": "IDLE",
                "initialized": False,
                "entry_data": None,
                "next_account_id": next_account_id
            }
        
        # 初始化第一个账户
        first_account_id = f"{exchange_id}_sub_1"
        await self.initialize_account(first_account_id, account_capital)
        
        # 保存策略状态
        await self.state_manager.save_strategy_state(self.strategy_state)
        
        self.logger.info(f"完成初始化 {accounts_count} 个子账户")
    
    async def initialize_account(self, account_id: str, initial_capital: float) -> None:
        """初始化单个子账户
        
        Args:
            account_id: 账户ID
            initial_capital: 初始资金
        """
        self.logger.info(f"初始化账户 {account_id}，初始资金 {initial_capital} USDT")
        
        try:
            # 1. 从母账户转入初始资金
            master_account_id = account_id.split("_sub_")[0] + "_main"
            
            transfer_result = await self.account_manager.transfer_asset(
                from_account=master_account_id,
                to_account=account_id,
                asset="USDT",
                amount=initial_capital
            )
            
            if not transfer_result:
                raise Exception(f"从主账户转入资金到 {account_id} 失败")
            
            # 2. 借入杠杆资金
            leverage_ratio = self.strategy_config.get("leverage_ratio", 4)
            leverage_amount = initial_capital * leverage_ratio
            
            # 简化处理，直接使用杠杆购买
            
            # 3. 获取BTC价格
            btc_price = await self.market_data.get_price("BTC/USDT")
            
            # 4. 计算购买数量
            total_usdt = initial_capital + leverage_amount
            btc_amount = total_usdt / btc_price
            
            # 5. 杠杆购买BTC
            spot_order = await self.execution_service.spot_leverage_buy(
                account_id=account_id,
                symbol="BTC/USDT",
                amount=btc_amount,
                leverage=leverage_ratio
            )
            
            # 6. 开设U本位空头
            half_position_btc = btc_amount / 2
            
            futures_order1 = await self.execution_service.futures_short(
                account_id=account_id,
                symbol="BTC/USDT",
                amount=half_position_btc,
                is_coin_margined=False
            )
            
            # 使用另一个U本位合约对冲
            futures_symbol2 = "BTC/USDC" if "BTC/USDC" in self.market_data.ticker_cache else "BTC/USDT"
            futures_order2 = await self.execution_service.futures_short(
                account_id=account_id,
                symbol=futures_symbol2,
                amount=half_position_btc,
                is_coin_margined=False
            )
            
            # 7. 计算目标亏损价格
            target_loss_amount = self.strategy_config.get("target_loss", 10000)
            target_price = await self.market_data.calculate_target_price(
                entry_price=btc_price,
                loss_target=target_loss_amount
            )
            
            # 8. 记录初始状态
            entry_data = {
                "entry_price": btc_price,
                "target_price": target_price,
                "target_loss_amount": target_loss_amount,
                "entry_time": datetime.now().isoformat(),
                "leverage_amount": leverage_amount,
                "initial_btc_amount": btc_amount,
                "spot_order_id": spot_order.order_id,
                "futures_order1_id": futures_order1.order_id,
                "futures_order2_id": futures_order2.order_id,
            }
            
            # 9. 更新账户状态
            self.strategy_state.accounts_status[account_id] = {
                "status": "WAITING_TARGET",
                "initialized": True,
                "entry_data": entry_data,
                "next_account_id": self.strategy_state.accounts_status[account_id]["next_account_id"]
            }
            
            # 10. 保存策略状态
            await self.state_manager.save_strategy_state(self.strategy_state)
            
            # 11. 开始监控目标价格
            self.monitoring_tasks[account_id] = asyncio.create_task(
                self.monitor_target_conditions(account_id, entry_data)
            )
            
            self.logger.info(f"账户 {account_id} 初始化完成，进入等待目标价格阶段")
            
        except Exception as e:
            self.logger.error(f"初始化账户 {account_id} 失败: {e}")
            # 更新账户状态为失败
            if account_id in self.strategy_state.accounts_status:
                self.strategy_state.accounts_status[account_id]["status"] = "FAILED"
                self.strategy_state.accounts_status[account_id]["error"] = str(e)
                await self.state_manager.save_strategy_state(self.strategy_state)
            
            # 通知风险监控
            await self.risk_monitor.handle_account_error(account_id, f"初始化失败: {e}")
    
    async def initialize_next_account(self, account_id: str, initial_btc: float) -> None:
        """初始化下一个账户，使用上一个账户的BTC
        
        Args:
            account_id: 账户ID
            initial_btc: 初始BTC数量
        """
        self.logger.info(f"初始化下一个账户 {account_id}，初始BTC数量 {initial_btc}")
        
        try:
            # 获取BTC价格
            btc_price = await self.market_data.get_price("BTC/USDT")
            
            # 使用BTC价值计算杠杆借贷金额
            btc_value = initial_btc * btc_price
            leverage_ratio = self.strategy_config.get("leverage_ratio", 4)
            leverage_amount = btc_value * leverage_ratio
            
            # 开设U本位空头对冲持仓BTC
            futures_order1 = await self.execution_service.futures_short(
                account_id=account_id,
                symbol="BTC/USDT",
                amount=initial_btc,
                is_coin_margined=False
            )
            
            # 记录初始状态
            entry_data = {
                "entry_price": btc_price,
                "entry_time": datetime.now().isoformat(),
                "initial_btc_amount": initial_btc,
                "futures_order_id": futures_order1.order_id,
                "leverage_amount": leverage_amount
            }
            
            # 更新账户状态
            self.strategy_state.accounts_status[account_id] = {
                "status": "INITIALIZED",
                "initialized": True,
                "entry_data": entry_data,
                "next_account_id": self.strategy_state.accounts_status[account_id]["next_account_id"]
            }
            
            # 保存策略状态
            await self.state_manager.save_strategy_state(self.strategy_state)
            
            self.logger.info(f"下一个账户 {account_id} 初始化完成")
            
        except Exception as e:
            self.logger.error(f"初始化下一个账户 {account_id} 失败: {e}")
            # 更新账户状态为失败
            if account_id in self.strategy_state.accounts_status:
                self.strategy_state.accounts_status[account_id]["status"] = "FAILED"
                self.strategy_state.accounts_status[account_id]["error"] = str(e)
                await self.state_manager.save_strategy_state(self.strategy_state)
            
            # 通知风险监控
            await self.risk_monitor.handle_account_error(account_id, f"初始化下一账户失败: {e}")
    
    async def monitor_target_conditions(self, account_id: str, entry_data: Dict) -> None:
        """监控目标价格条件
        
        Args:
            account_id: 账户ID
            entry_data: 入场数据
        """
        self.logger.info(f"开始监控账户 {account_id} 的目标价格条件")
        
        try:
            # 提取目标价格
            target_price = entry_data["target_price"]
            
            # 设置条件单
            orders = [
                {
                    "symbol": "BTC/USDT",
                    "type": "limit",
                    "side": "buy",  # 买入平空
                    "amount": entry_data["initial_btc_amount"] / 2,
                    "price": target_price,
                    "params": {"reduceOnly": True}
                }
            ]
            
            # 如果使用了第二个合约对冲，也为它设置条件单
            if "futures_order2_id" in entry_data:
                futures_symbol2 = "BTC/USDC" if "BTC/USDC" in self.market_data.ticker_cache else "BTC/USDT"
                orders.append({
                    "symbol": futures_symbol2,
                    "type": "limit",
                    "side": "buy",  # 买入平空
                    "amount": entry_data["initial_btc_amount"] / 2,
                    "price": target_price,
                    "params": {"reduceOnly": True}
                })
            
            # 设置条件单
            conditional_orders = await self.execution_service.set_conditional_orders(
                account_id=account_id,
                orders=orders
            )
            
            self.logger.info(f"账户 {account_id} 设置条件单完成，目标价格: {target_price}")
            
            # 持续监控价格
            wait_counter = 0
            while self.is_running:
                try:
                    current_price = await self.market_data.get_price("BTC/USDT")
                    
                    # 每100次轮询输出一次日志
                    wait_counter += 1
                    if wait_counter % 100 == 0:
                        self.logger.info(f"账户 {account_id} 当前价格: {current_price}，目标价格: {target_price}")
                    
                    # 如果价格接近目标价格，准备执行关键操作
                    if current_price >= target_price * 0.995:
                        self.logger.info(f"账户 {account_id} 价格接近目标: 当前价格 {current_price}，目标 {target_price}")
                        await self.execute_critical_operations(account_id)
                        break
                    
                    # 使用风险监控检查账户状态
                    risk_level = await self.risk_monitor.check_account_risk(account_id)
                    if risk_level == "HIGH":
                        self.logger.warning(f"账户 {account_id} 风险级别高，提前执行目标操作")
                        await self.execute_critical_operations(account_id)
                        break
                        
                except Exception as e:
                    self.logger.error(f"监控账户 {account_id} 目标价格时出错: {e}")
                
                # 轮询间隔
                await asyncio.sleep(0.5)
            
        except Exception as e:
            self.logger.error(f"账户 {account_id} 监控目标条件过程中出错: {e}")
            # 通知风险监控
            await self.risk_monitor.handle_account_error(account_id, f"监控目标条件失败: {e}")
    
    async def execute_critical_operations(self, account_id: str) -> None:
        """执行关键操作
        
        Args:
            account_id: 账户ID
        """
        self.logger.info(f"开始执行账户 {account_id} 的关键操作")
        
        try:
            # 获取账户状态
            account_state = self.strategy_state.accounts_status[account_id]
            entry_data = account_state["entry_data"]
            
            # 获取BTC余额
            btc_balance = await self.account_manager.get_account_balance(account_id, "BTC")
            
            # 准备操作列表
            operations = [
                # 平仓U本位空头
                {
                    "type": "close_position",
                    "symbol": "BTC/USDT",
                    "market_order": True
                }
            ]
            
            # 如果使用了第二个合约，也平仓它
            if "futures_order2_id" in entry_data:
                futures_symbol2 = "BTC/USDC" if "BTC/USDC" in self.market_data.ticker_cache else "BTC/USDT"
                operations.append({
                    "type": "close_position",
                    "symbol": futures_symbol2,
                    "market_order": True
                })
            
            # 偿还杠杆借款
            operations.append({
                "type": "repay_loan",
                "asset": "USDT",
                "amount": entry_data["leverage_amount"]
            })
            
            # 计算用于开设币本位空头的BTC数量
            funding_allocation = self.strategy_config.get("funding_allocation", 0.15)
            btc_for_funding = btc_balance * funding_allocation
            
            # 开设币本位空头
            operations.append({
                "type": "open_coin_margin_short",
                "symbol": "BTC/USD",  # 或其他币本位合约
                "amount": btc_for_funding
            })
            
            # 同步执行所有操作
            results = await self.execution_service.execute_critical_operations(
                account_id=account_id,
                operations=operations
            )
            
            # 验证结果
            success = all(result.success for result in results.values())
            
            if success:
                # 获取下一个账户ID
                next_account_id = account_state["next_account_id"]
                
                # 计算剩余BTC
                remaining_btc = btc_balance * (1 - funding_allocation)
                
                # 如果有下一个账户，转移BTC
                if next_account_id:
                    transfer_result = await self.account_manager.transfer_asset(
                        from_account=account_id,
                        to_account=next_account_id,
                        asset="BTC",
                        amount=remaining_btc
                    )
                    
                    if transfer_result:
                        self.logger.info(f"成功转移 {remaining_btc} BTC 从 {account_id} 到 {next_account_id}")
                        
                        # 初始化下一个账户
                        await self.initialize_next_account(
                            account_id=next_account_id,
                            initial_btc=remaining_btc
                        )
                    else:
                        self.logger.error(f"转移BTC从 {account_id} 到 {next_account_id} 失败")
                
                # 更新账户状态
                self.strategy_state.accounts_status[account_id]["status"] = "FUNDING_COLLECTION"
                self.strategy_state.accounts_status[account_id]["funding_start_time"] = datetime.now().isoformat()
                await self.state_manager.save_strategy_state(self.strategy_state)
                
                self.logger.info(f"账户 {account_id} 成功执行关键操作，进入资金费率收集阶段")
                
                # 开始资金费率收集监控
                self.monitoring_tasks[account_id] = asyncio.create_task(
                    self.monitor_funding_rate(account_id)
                )
            else:
                self.logger.error(f"账户 {account_id} 关键操作执行失败: {results}")
                # 通知风险监控
                await self.risk_monitor.handle_operation_failure(account_id, results)
                
        except Exception as e:
            self.logger.error(f"执行账户 {account_id} 的关键操作时出错: {e}")
            # 通知风险监控
            await self.risk_monitor.handle_account_error(account_id, f"执行关键操作失败: {e}")
    
    async def monitor_funding_rate(self, account_id: str) -> None:
        """监控资金费率
        
        Args:
            account_id: 账户ID
        """
        self.logger.info(f"开始监控账户 {account_id} 的资金费率")
        
        try:
            while self.is_running:
                # 获取币本位合约的资金费率
                funding_rate = await self.market_data.get_funding_rate("BTC/USD")
                
                # 检查资金费率是否在合理范围内
                min_funding_rate = self.config["risk"].get("min_funding_rate", -0.01)
                
                if funding_rate < min_funding_rate:
                    self.logger.warning(f"账户 {account_id} 资金费率 {funding_rate} 低于最小阈值 {min_funding_rate}，准备退出策略")
                    # 平仓币本位空头
                    await self.exit_funding_strategy(account_id)
                    break
                
                # 计算和记录收益
                positions = await self.account_manager.get_positions(account_id)
                for position in positions:
                    if position.is_coin_margined and position.side == "short":
                        # 估算本次资金费率收益
                        funding_profit = position.amount * position.entry_price * abs(funding_rate)
                        self.logger.info(f"账户 {account_id} 资金费率: {funding_rate}, 预计收益: {funding_profit} USD")
                        break
                
                # 每小时检查一次
                await asyncio.sleep(3600)
                
        except Exception as e:
            self.logger.error(f"监控账户 {account_id} 资金费率时出错: {e}")
    
    async def exit_funding_strategy(self, account_id: str) -> None:
        """退出资金费率策略
        
        Args:
            account_id: 账户ID
        """
        self.logger.info(f"账户 {account_id} 开始退出资金费率策略")
        
        try:
            # 平仓所有币本位空头持仓
            positions = await self.account_manager.get_positions(account_id)
            
            for position in positions:
                if position.is_coin_margined and position.side == "short":
                    await self.execution_service.close_position(
                        account_id=account_id,
                        symbol=position.symbol,
                        amount=position.amount
                    )
                    self.logger.info(f"账户 {account_id} 已平仓币本位空头: {position.symbol} {position.amount}")
            
            # 更新账户状态
            self.strategy_state.accounts_status[account_id]["status"] = "COMPLETED"
            self.strategy_state.accounts_status[account_id]["completed_time"] = datetime.now().isoformat()
            await self.state_manager.save_strategy_state(self.strategy_state)
            
            self.logger.info(f"账户 {account_id} 已完成资金费率策略")
            
        except Exception as e:
            self.logger.error(f"账户 {account_id} 退出资金费率策略时出错: {e}")
            # 通知风险监控
            await self.risk_monitor.handle_account_error(account_id, f"退出资金费率策略失败: {e}")
    
    async def execute_strategy_cycle(self) -> None:
        """执行策略周期，检查所有账户状态"""
        if not self.is_running:
            return
        
        try:
            # 检查账户状态
            for account_id, account_state in self.strategy_state.accounts_status.items():
                # 处理尚未初始化的账户
                if account_state["status"] == "IDLE" and not account_state["initialized"]:
                    # 第一个账户已经在初始化策略时处理了，这里不需要额外处理
                    pass
                
                # 检查任务是否完成或出错
                if account_id in self.monitoring_tasks and self.monitoring_tasks[account_id].done():
                    try:
                        # 检查任务是否有异常
                        await self.monitoring_tasks[account_id]
                    except Exception as e:
                        self.logger.error(f"账户 {account_id} 的监控任务出错: {e}")
                        # 通知风险监控
                        await self.risk_monitor.handle_account_error(account_id, f"监控任务失败: {e}")
                    
                    # 移除完成的任务
                    del self.monitoring_tasks[account_id]
            
            # 更新策略状态
            self.strategy_state.last_updated = datetime.now()
            await self.state_manager.save_strategy_state(self.strategy_state)
            
        except Exception as e:
            self.logger.error(f"执行策略周期时出错: {e}")
    
    async def execute_account_strategy(self, account_id: str) -> None:
        """执行特定账户的策略操作
        
        Args:
            account_id: 账户ID
        """
        try:
            # 检查账户状态
            if account_id not in self.strategy_state.accounts_status:
                self.logger.error(f"账户 {account_id} 不在策略状态中")
                return
            
            account_state = self.strategy_state.accounts_status[account_id]
            
            # 根据状态执行相应操作
            if account_state["status"] == "IDLE" and not account_state["initialized"]:
                # 初始化账户
                account_capital = self.strategy_config.get("account_capital", 10000)
                await self.initialize_account(account_id, account_capital)
                
            elif account_state["status"] == "WAITING_TARGET":
                # 检查是否有监控任务在运行
                if account_id not in self.monitoring_tasks or self.monitoring_tasks[account_id].done():
                    # 重新启动监控任务
                    self.monitoring_tasks[account_id] = asyncio.create_task(
                        self.monitor_target_conditions(account_id, account_state["entry_data"])
                    )
                    
            elif account_state["status"] == "FUNDING_COLLECTION":
                # 检查是否有监控任务在运行
                if account_id not in self.monitoring_tasks or self.monitoring_tasks[account_id].done():
                    # 重新启动资金费率监控
                    self.monitoring_tasks[account_id] = asyncio.create_task(
                        self.monitor_funding_rate(account_id)
                    )
            
        except Exception as e:
            self.logger.error(f"执行账户 {account_id} 策略时出错: {e}")
