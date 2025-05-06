"""
指标监控工具

提供Prometheus指标收集和暴露功能
"""
import logging
from typing import Dict, Any
import threading
import time

# 尝试导入Prometheus客户端库，不可用时提供降级方案
try:
    import prometheus_client as prom
    from prometheus_client import Counter, Gauge, Histogram, Summary
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


class MetricsCollector:
    """指标收集器，用于收集和暴露系统指标"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化指标收集器
        
        Args:
            config: 监控配置字典
        """
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        self.metrics = {}
        self.server = None
        
        if not PROMETHEUS_AVAILABLE:
            self.logger.warning("Prometheus客户端库未安装，指标收集功能不可用")
            return
        
        self._initialize_metrics()
        self._start_server()
    
    def _initialize_metrics(self):
        """初始化指标"""
        if not PROMETHEUS_AVAILABLE:
            return
        
        # 交易指标
        self.metrics["orders_total"] = Counter(
            "orders_total", 
            "Total number of orders executed",
            ["account_id", "symbol", "side", "type"]
        )
        
        self.metrics["order_amount_total"] = Counter(
            "order_amount_total",
            "Total amount of all orders",
            ["account_id", "symbol", "side"]
        )
        
        # 账户指标
        self.metrics["account_balance"] = Gauge(
            "account_balance",
            "Current account balance",
            ["account_id", "asset"]
        )
        
        self.metrics["account_position"] = Gauge(
            "account_position",
            "Current account position",
            ["account_id", "symbol", "side"]
        )
        
        self.metrics["account_leverage"] = Gauge(
            "account_leverage",
            "Current account leverage",
            ["account_id"]
        )
        
        # 市场指标
        self.metrics["funding_rate"] = Gauge(
            "funding_rate",
            "Current funding rate",
            ["symbol"]
        )
        
        self.metrics["ticker_price"] = Gauge(
            "ticker_price",
            "Current ticker price",
            ["symbol"]
        )
        
        # 性能指标
        self.metrics["operation_duration"] = Histogram(
            "operation_duration_seconds",
            "Duration of operations",
            ["operation", "account_id"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        self.metrics["api_errors"] = Counter(
            "api_errors_total",
            "Total number of API errors",
            ["exchange", "endpoint", "error_type"]
        )
        
        # 系统指标
        self.metrics["strategy_active"] = Gauge(
            "strategy_active",
            "Whether the strategy is active",
            ["strategy_id"]
        )
    
    def _start_server(self):
        """启动指标服务器"""
        if not PROMETHEUS_AVAILABLE:
            return
        
        # 检查是否启用
        if not self.config.get("prometheus", {}).get("enabled", False):
            self.logger.info("Prometheus指标服务器未启用")
            return
        
        # 获取端口
        port = self.config.get("prometheus", {}).get("port", 9090)
        
        try:
            # 启动服务器
            self.server = prom.start_http_server(port)
            self.logger.info(f"Prometheus指标服务器已启动，端口: {port}")
        except Exception as e:
            self.logger.error(f"启动Prometheus指标服务器失败: {e}")
    
    def record_order(self, account_id: str, symbol: str, side: str, order_type: str, amount: float):
        """记录订单指标
        
        Args:
            account_id: 账户ID
            symbol: 交易对符号
            side: 订单方向
            order_type: 订单类型
            amount: 订单数量
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["orders_total"].labels(
                account_id=account_id,
                symbol=symbol,
                side=side,
                type=order_type
            ).inc()
            
            self.metrics["order_amount_total"].labels(
                account_id=account_id,
                symbol=symbol,
                side=side
            ).inc(amount)
        except Exception as e:
            self.logger.error(f"记录订单指标失败: {e}")
    
    def update_account_balance(self, account_id: str, asset: str, balance: float):
        """更新账户余额指标
        
        Args:
            account_id: 账户ID
            asset: 资产符号
            balance: 余额
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["account_balance"].labels(
                account_id=account_id,
                asset=asset
            ).set(balance)
        except Exception as e:
            self.logger.error(f"更新账户余额指标失败: {e}")
    
    def update_account_position(self, account_id: str, symbol: str, side: str, amount: float):
        """更新账户持仓指标
        
        Args:
            account_id: 账户ID
            symbol: 交易对符号
            side: 持仓方向
            amount: 持仓数量
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["account_position"].labels(
                account_id=account_id,
                symbol=symbol,
                side=side
            ).set(amount)
        except Exception as e:
            self.logger.error(f"更新账户持仓指标失败: {e}")
    
    def update_account_leverage(self, account_id: str, leverage: float):
        """更新账户杠杆指标
        
        Args:
            account_id: 账户ID
            leverage: 杠杆率
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["account_leverage"].labels(
                account_id=account_id
            ).set(leverage)
        except Exception as e:
            self.logger.error(f"更新账户杠杆指标失败: {e}")
    
    def update_funding_rate(self, symbol: str, rate: float):
        """更新资金费率指标
        
        Args:
            symbol: 交易对符号
            rate: 资金费率
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["funding_rate"].labels(
                symbol=symbol
            ).set(rate)
        except Exception as e:
            self.logger.error(f"更新资金费率指标失败: {e}")
    
    def update_ticker_price(self, symbol: str, price: float):
        """更新行情价格指标
        
        Args:
            symbol: 交易对符号
            price: 价格
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["ticker_price"].labels(
                symbol=symbol
            ).set(price)
        except Exception as e:
            self.logger.error(f"更新行情价格指标失败: {e}")
    
    def observe_operation_duration(self, operation: str, account_id: str, duration: float):
        """观测操作耗时
        
        Args:
            operation: 操作名称
            account_id: 账户ID
            duration: 耗时（秒）
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["operation_duration"].labels(
                operation=operation,
                account_id=account_id
            ).observe(duration)
        except Exception as e:
            self.logger.error(f"观测操作耗时失败: {e}")
    
    def record_api_error(self, exchange: str, endpoint: str, error_type: str):
        """记录API错误
        
        Args:
            exchange: 交易所名称
            endpoint: API端点
            error_type: 错误类型
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["api_errors"].labels(
                exchange=exchange,
                endpoint=endpoint,
                error_type=error_type
            ).inc()
        except Exception as e:
            self.logger.error(f"记录API错误失败: {e}")
    
    def update_strategy_status(self, strategy_id: str, active: bool):
        """更新策略状态
        
        Args:
            strategy_id: 策略ID
            active: 是否激活
        """
        if not PROMETHEUS_AVAILABLE or not self.metrics:
            return
        
        try:
            self.metrics["strategy_active"].labels(
                strategy_id=strategy_id
            ).set(1 if active else 0)
        except Exception as e:
            self.logger.error(f"更新策略状态失败: {e}")


def setup_metrics(config: Dict[str, Any] = None) -> MetricsCollector:
    """设置指标收集器
    
    Args:
        config: 监控配置字典
        
    Returns:
        配置好的指标收集器
    """
    return MetricsCollector(config)
