"""
账户相关的数据模型
"""
from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Position:
    """持仓信息"""
    symbol: str  # 交易对符号
    side: Literal["long", "short"]  # 持仓方向
    amount: float  # 持仓数量
    entry_price: float  # 入场价格
    leverage: float  # 杠杆倍数
    margin_type: Literal["isolated", "cross"]  # 保证金模式
    liquidation_price: float  # 清算价格
    unrealized_pnl: float  # 未实现盈亏
    is_coin_margined: bool  # 是否是币本位合约


@dataclass
class AccountState:
    """账户状态"""
    account_id: str  # 账户ID
    status: Literal["IDLE", "INITIALIZED", "WAITING_TARGET", "FUNDING_COLLECTION", "COMPLETED", "FAILED"]  # 账户状态
    balance: Dict[str, float]  # 各资产余额
    positions: List[Position]  # 持仓信息
    leverage_info: Dict[str, Any]  # 杠杆借贷信息
    entry_data: Optional[Dict[str, Any]] = None  # 入场数据
    next_account_id: Optional[str] = None  # 下一个处理的账户
