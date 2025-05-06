"""
订单相关的数据模型
"""
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Order:
    """交易订单"""
    order_id: str  # 订单ID
    account_id: str  # 账户ID
    symbol: str  # 交易对符号
    side: Literal["buy", "sell"]  # 订单方向
    type: Literal["market", "limit"]  # 订单类型
    amount: float  # 订单数量
    price: Optional[float] = None  # 订单价格
    status: Literal["open", "closed", "canceled"] = "open"  # 订单状态
    filled: float = 0.0  # 已成交数量
    remaining: float = 0.0  # 剩余未成交数量
    timestamp: datetime = None  # 订单创建时间


@dataclass
class Operation:
    """操作定义"""
    type: str  # 操作类型
    params: Dict[str, Any]  # 操作参数


@dataclass
class Result:
    """操作结果"""
    operation_id: str  # 操作ID
    success: bool  # 是否成功
    result_data: Optional[Dict[str, Any]] = None  # 结果数据
    error: Optional[str] = None  # 错误信息
    timestamp: datetime = None  # 操作时间
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
