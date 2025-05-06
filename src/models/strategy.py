"""
策略相关的数据模型
"""
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass


@dataclass
class StrategyState:
    """策略状态"""
    is_active: bool  # 策略是否激活
    accounts_status: Dict[str, Dict[str, Any]]  # 账户状态字典，key为账户ID
    started_at: Optional[datetime] = None  # 策略启动时间
    last_updated: Optional[datetime] = None  # 最后更新时间
