"""
交易记录数据模型
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Transaction:
    """交易记录"""
    account_id: str  # 账户ID
    type: str  # 交易类型
    symbol: str  # 交易对符号
    amount: float  # 交易数量
    price: Optional[float] = None  # 交易价格
    fee: Optional[float] = None  # 手续费
    timestamp: datetime = None  # 交易时间
    metadata: Optional[Dict[str, Any]] = None  # 元数据
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}
