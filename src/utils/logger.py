"""
日志工具模块

提供日志配置和管理功能
"""
import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, Any


def setup_logger(config: Dict[str, Any] = None) -> logging.Logger:
    """设置日志配置
    
    Args:
        config: 日志配置字典
        
    Returns:
        配置好的日志器
    """
    if config is None:
        config = {
            "level": "INFO",
            "file": "logs/strategy.log",
            "rotation": "1d",
            "retention": "30d"
        }
    
    # 获取根日志器
    logger = logging.getLogger()
    
    # 设置日志级别
    log_level = getattr(logging, config.get("level", "INFO"))
    logger.setLevel(log_level)
    
    # 清除已有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # 如果配置了文件日志，创建文件处理器
    log_file = config.get("file")
    if log_file:
        # 确保日志目录存在
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # 创建文件处理器
        rotation_interval = config.get("rotation", "1d")
        when, interval = _parse_rotation_interval(rotation_interval)
        
        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when=when,
            interval=interval,
            backupCount=_parse_retention_days(config.get("retention", "30d"))
        )
        file_handler.setLevel(log_level)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def _parse_rotation_interval(rotation_interval: str) -> tuple:
    """解析日志轮转间隔
    
    Args:
        rotation_interval: 轮转间隔字符串，如 "1d", "12h"
        
    Returns:
        轮转单位和间隔数的元组
    """
    if rotation_interval.endswith('d'):
        return 'D', int(rotation_interval[:-1])
    elif rotation_interval.endswith('h'):
        return 'H', int(rotation_interval[:-1])
    elif rotation_interval.endswith('m'):
        return 'M', int(rotation_interval[:-1])
    elif rotation_interval.endswith('s'):
        return 'S', int(rotation_interval[:-1])
    else:
        return 'D', 1  # 默认每天轮转


def _parse_retention_days(retention: str) -> int:
    """解析日志保留天数
    
    Args:
        retention: 保留天数字符串，如 "30d"
        
    Returns:
        保留的日志文件数量
    """
    if retention.endswith('d'):
        return int(retention[:-1])
    else:
        return 30  # 默认保留30天
