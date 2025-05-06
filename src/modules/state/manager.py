"""
状态管理模块

管理策略执行状态，支持恢复和追踪
"""
import logging
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from ...models.strategy import StrategyState
from ...models.transaction import Transaction


class StateManager:
    """状态管理器，管理策略执行状态"""

    def __init__(self, config: Dict[str, Any]):
        """初始化状态管理器
        
        Args:
            config: 系统配置
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.engine = None
        self.async_session = None
        self.db_config = config.get("database", {}).get("timescale", {})
        self.redis_client = None
        
        # 文件路径，用于非数据库的状态管理
        self.state_file = "data/strategy_state.json"
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
    
    async def initialize(self):
        """初始化状态管理器，连接数据库"""
        self.logger.info("初始化状态管理器")
        
        try:
            # 连接TimescaleDB
            if self.db_config:
                db_url = self._get_db_url()
                self.engine = create_async_engine(db_url, echo=False)
                self.async_session = sessionmaker(
                    self.engine, class_=AsyncSession, expire_on_commit=False
                )
                
                # 测试连接
                async with self.engine.begin() as conn:
                    # 检查所需表是否存在，不存在则创建
                    await conn.run_sync(self._create_tables)
                
                self.logger.info("成功连接到TimescaleDB")
            
            # 连接Redis
            redis_config = self.config.get("database", {}).get("redis", {})
            if redis_config:
                import redis.asyncio as redis
                self.redis_client = redis.Redis(
                    host=redis_config.get("host", "localhost"),
                    port=redis_config.get("port", 6379),
                    db=redis_config.get("db", 0),
                    decode_responses=True
                )
                
                # 测试连接
                await self.redis_client.ping()
                self.logger.info("成功连接到Redis")
            
            self.logger.info("状态管理器初始化完成")
            
        except Exception as e:
            self.logger.error(f"初始化状态管理器失败: {e}")
            self.logger.warning("将使用文件系统作为备用状态存储")
    
    def _get_db_url(self) -> str:
        """获取数据库连接URL
        
        Returns:
            数据库连接URL
        """
        password = self._get_env_var(self.db_config.get("password_env", "DB_PASSWORD"))
        host = self.db_config.get("host", "localhost")
        port = self.db_config.get("port", 5432)
        user = self.db_config.get("user", "postgres")
        database = self.db_config.get("database", "funding_strategy")
        
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    
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
    
    @staticmethod
    def _create_tables(conn):
        """创建所需的数据库表
        
        Args:
            conn: 数据库连接
        """
        metadata = sa.MetaData()
        
        # 账户状态表
        sa.Table(
            "account_states",
            metadata,
            sa.Column("account_id", sa.String(50), primary_key=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("balance", sa.JSON, nullable=False),
            sa.Column("positions", sa.JSON),
            sa.Column("leverage_info", sa.JSON),
            sa.Column("entry_data", sa.JSON),
            sa.Column("next_account_id", sa.String(50)),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), default=sa.func.now())
        )
        
        # 交易记录表
        sa.Table(
            "transactions",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.String(50), nullable=False),
            sa.Column("type", sa.String(30), nullable=False),
            sa.Column("symbol", sa.String(20)),
            sa.Column("amount", sa.Numeric(20, 8), nullable=False),
            sa.Column("price", sa.Numeric(20, 8)),
            sa.Column("fee", sa.Numeric(20, 8)),
            sa.Column("timestamp", sa.TIMESTAMP(timezone=True), default=sa.func.now()),
            sa.Column("metadata", sa.JSON)
        )
        
        # 订单表
        sa.Table(
            "orders",
            metadata,
            sa.Column("order_id", sa.String(50), primary_key=True),
            sa.Column("account_id", sa.String(50), nullable=False),
            sa.Column("symbol", sa.String(20), nullable=False),
            sa.Column("side", sa.String(10), nullable=False),
            sa.Column("type", sa.String(10), nullable=False),
            sa.Column("amount", sa.Numeric(20, 8), nullable=False),
            sa.Column("price", sa.Numeric(20, 8)),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("filled", sa.Numeric(20, 8), default=0),
            sa.Column("remaining", sa.Numeric(20, 8)),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), default=sa.func.now()),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), default=sa.func.now())
        )
        
        # 策略状态表
        sa.Table(
            "strategy_states",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("strategy_id", sa.String(50), unique=True, nullable=False),
            sa.Column("is_active", sa.Boolean, default=False),
            sa.Column("accounts_status", sa.JSON),
            sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("last_updated", sa.TIMESTAMP(timezone=True), default=sa.func.now())
        )
        
        # 创建或更新表
        metadata.create_all(conn)
    
    async def save_strategy_state(self, state: StrategyState) -> None:
        """保存策略状态
        
        Args:
            state: 策略状态
        """
        try:
            if self.engine and self.async_session:
                # 使用数据库保存
                async with self.async_session() as session:
                    # 转换为数据库模型
                    state_dict = {
                        "strategy_id": "funding_strategy",  # 固定ID，可以改为动态的
                        "is_active": state.is_active,
                        "accounts_status": state.accounts_status,
                        "started_at": state.started_at,
                        "last_updated": datetime.now()
                    }
                    
                    # 插入或更新
                    query = """
                    INSERT INTO strategy_states (strategy_id, is_active, accounts_status, started_at, last_updated)
                    VALUES (:strategy_id, :is_active, :accounts_status, :started_at, :last_updated)
                    ON CONFLICT (strategy_id) DO UPDATE
                    SET is_active = :is_active, accounts_status = :accounts_status, last_updated = :last_updated
                    """
                    await session.execute(sa.text(query), state_dict)
                    await session.commit()
            else:
                # 使用文件系统保存
                state_dict = {
                    "is_active": state.is_active,
                    "accounts_status": state.accounts_status,
                    "started_at": state.started_at.isoformat() if state.started_at else None,
                    "last_updated": datetime.now().isoformat()
                }
                
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(state_dict, f, indent=2)
            
            self.logger.info("已保存策略状态")
            
        except Exception as e:
            self.logger.error(f"保存策略状态失败: {e}")
            # 尝试备用方法保存
            try:
                state_dict = {
                    "is_active": state.is_active,
                    "accounts_status": state.accounts_status,
                    "started_at": state.started_at.isoformat() if state.started_at else None,
                    "last_updated": datetime.now().isoformat()
                }
                
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(state_dict, f, indent=2)
                
                self.logger.info("已使用备用方法保存策略状态")
            except Exception as backup_e:
                self.logger.critical(f"备用方法保存策略状态也失败: {backup_e}")
    
    async def load_strategy_state(self) -> Optional[StrategyState]:
        """加载策略状态
        
        Returns:
            策略状态，如果不存在则返回None
        """
        try:
            if self.engine and self.async_session:
                # 使用数据库加载
                async with self.async_session() as session:
                    query = "SELECT * FROM strategy_states WHERE strategy_id = :strategy_id"
                    result = await session.execute(sa.text(query), {"strategy_id": "funding_strategy"})
                    row = result.fetchone()
                    
                    if row:
                        # 转换为StrategyState对象
                        return StrategyState(
                            is_active=row.is_active,
                            accounts_status=row.accounts_status,
                            started_at=row.started_at,
                            last_updated=row.last_updated
                        )
                    return None
            else:
                # 使用文件系统加载
                if os.path.exists(self.state_file):
                    with open(self.state_file, "r", encoding="utf-8") as f:
                        state_dict = json.load(f)
                    
                    # 转换时间字符串为datetime对象
                    started_at = datetime.fromisoformat(state_dict["started_at"]) if state_dict.get("started_at") else None
                    last_updated = datetime.fromisoformat(state_dict["last_updated"]) if state_dict.get("last_updated") else None
                    
                    return StrategyState(
                        is_active=state_dict["is_active"],
                        accounts_status=state_dict["accounts_status"],
                        started_at=started_at,
                        last_updated=last_updated
                    )
                return None
                
        except Exception as e:
            self.logger.error(f"加载策略状态失败: {e}")
            return None
    
    async def record_transaction(self, transaction: Transaction) -> None:
        """记录交易
        
        Args:
            transaction: 交易记录
        """
        try:
            if self.engine and self.async_session:
                # 使用数据库记录
                async with self.async_session() as session:
                    # 转换为数据库模型
                    transaction_dict = {
                        "account_id": transaction.account_id,
                        "type": transaction.type,
                        "symbol": transaction.symbol,
                        "amount": transaction.amount,
                        "price": transaction.price,
                        "fee": transaction.fee,
                        "timestamp": transaction.timestamp,
                        "metadata": transaction.metadata
                    }
                    
                    # 插入记录
                    query = """
                    INSERT INTO transactions (account_id, type, symbol, amount, price, fee, timestamp, metadata)
                    VALUES (:account_id, :type, :symbol, :amount, :price, :fee, :timestamp, :metadata)
                    """
                    await session.execute(sa.text(query), transaction_dict)
                    await session.commit()
            else:
                # 使用文件系统记录
                transaction_file = f"data/transactions_{transaction.account_id}.jsonl"
                os.makedirs(os.path.dirname(transaction_file), exist_ok=True)
                
                # 转换为字典
                transaction_dict = {
                    "account_id": transaction.account_id,
                    "type": transaction.type,
                    "symbol": transaction.symbol,
                    "amount": float(transaction.amount),
                    "price": float(transaction.price) if transaction.price else None,
                    "fee": float(transaction.fee) if transaction.fee else None,
                    "timestamp": transaction.timestamp.isoformat(),
                    "metadata": transaction.metadata
                }
                
                # 追加到文件
                with open(transaction_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(transaction_dict) + "\n")
            
            self.logger.info(f"已记录交易: {transaction.type} {transaction.symbol} {transaction.amount}")
            
        except Exception as e:
            self.logger.error(f"记录交易失败: {e}")
    
    async def get_account_state(self, account_id: str) -> Dict[str, Any]:
        """获取账户状态
        
        Args:
            account_id: 账户ID
            
        Returns:
            账户状态字典
        """
        try:
            if self.engine and self.async_session:
                # 使用数据库获取
                async with self.async_session() as session:
                    query = "SELECT * FROM account_states WHERE account_id = :account_id"
                    result = await session.execute(sa.text(query), {"account_id": account_id})
                    row = result.fetchone()
                    
                    if row:
                        # 转换为字典
                        account_state = {
                            "account_id": row.account_id,
                            "status": row.status,
                            "balance": row.balance,
                            "positions": row.positions,
                            "leverage_info": row.leverage_info,
                            "entry_data": row.entry_data,
                            "next_account_id": row.next_account_id,
                            "updated_at": row.updated_at
                        }
                        return account_state
                    
                    return {}
            else:
                # 使用策略状态获取
                strategy_state = await self.load_strategy_state()
                if strategy_state and account_id in strategy_state.accounts_status:
                    return strategy_state.accounts_status[account_id]
                return {}
                
        except Exception as e:
            self.logger.error(f"获取账户 {account_id} 状态失败: {e}")
            return {}
    
    async def update_account_state(self, account_id: str, new_state: Dict[str, Any]) -> None:
        """更新账户状态
        
        Args:
            account_id: 账户ID
            new_state: 新的账户状态
        """
        try:
            if self.engine and self.async_session:
                # 使用数据库更新
                async with self.async_session() as session:
                    # 检查是否存在
                    query = "SELECT 1 FROM account_states WHERE account_id = :account_id"
                    result = await session.execute(sa.text(query), {"account_id": account_id})
                    exists = result.fetchone() is not None
                    
                    if exists:
                        # 更新
                        update_query = """
                        UPDATE account_states
                        SET status = :status, balance = :balance, positions = :positions,
                            leverage_info = :leverage_info, entry_data = :entry_data,
                            next_account_id = :next_account_id, updated_at = :updated_at
                        WHERE account_id = :account_id
                        """
                        await session.execute(sa.text(update_query), {
                            "account_id": account_id,
                            "status": new_state.get("status"),
                            "balance": new_state.get("balance", {}),
                            "positions": new_state.get("positions", []),
                            "leverage_info": new_state.get("leverage_info", {}),
                            "entry_data": new_state.get("entry_data"),
                            "next_account_id": new_state.get("next_account_id"),
                            "updated_at": datetime.now()
                        })
                    else:
                        # 插入
                        insert_query = """
                        INSERT INTO account_states (account_id, status, balance, positions,
                                                   leverage_info, entry_data, next_account_id, updated_at)
                        VALUES (:account_id, :status, :balance, :positions,
                                :leverage_info, :entry_data, :next_account_id, :updated_at)
                        """
                        await session.execute(sa.text(insert_query), {
                            "account_id": account_id,
                            "status": new_state.get("status"),
                            "balance": new_state.get("balance", {}),
                            "positions": new_state.get("positions", []),
                            "leverage_info": new_state.get("leverage_info", {}),
                            "entry_data": new_state.get("entry_data"),
                            "next_account_id": new_state.get("next_account_id"),
                            "updated_at": datetime.now()
                        })
                    
                    await session.commit()
            else:
                # 使用策略状态更新
                strategy_state = await self.load_strategy_state()
                if strategy_state:
                    strategy_state.accounts_status[account_id] = new_state
                    strategy_state.last_updated = datetime.now()
                    await self.save_strategy_state(strategy_state)
            
            self.logger.info(f"已更新账户 {account_id} 状态")
            
        except Exception as e:
            self.logger.error(f"更新账户 {account_id} 状态失败: {e}")
    
    async def save_account_entry_data(self, account_id: str, entry_data: Dict[str, Any]) -> None:
        """保存账户入场数据
        
        Args:
            account_id: 账户ID
            entry_data: 入场数据
        """
        try:
            # 获取当前账户状态
            account_state = await self.get_account_state(account_id)
            
            # 更新入场数据
            account_state["entry_data"] = entry_data
            
            # 保存更新后的状态
            await self.update_account_state(account_id, account_state)
            
            self.logger.info(f"已保存账户 {account_id} 的入场数据")
            
        except Exception as e:
            self.logger.error(f"保存账户 {account_id} 的入场数据失败: {e}")
    
    async def get_account_entry_data(self, account_id: str) -> Dict[str, Any]:
        """获取账户入场数据
        
        Args:
            account_id: 账户ID
            
        Returns:
            入场数据字典
        """
        try:
            # 获取账户状态
            account_state = await self.get_account_state(account_id)
            
            # 返回入场数据
            return account_state.get("entry_data", {})
            
        except Exception as e:
            self.logger.error(f"获取账户 {account_id} 的入场数据失败: {e}")
            return {}
    
    async def close(self):
        """关闭状态管理器"""
        self.logger.info("关闭状态管理器")
        
        # 关闭数据库连接
        if self.engine:
            await self.engine.dispose()
            self.logger.info("已关闭数据库连接")
        
        # 关闭Redis连接
        if self.redis_client:
            await self.redis_client.close()
            self.logger.info("已关闭Redis连接")
