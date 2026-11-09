"""
统一日志配置

提供结构化日志、日志轮转、日志级别动态调整等功能
"""
import logging
import logging.handlers
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录
        
        Args:
            record: 日志记录
            
        Returns:
            格式化后的日志字符串
        """
        # 基础日志信息
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # 添加额外字段
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        
        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器（用于控制台）"""
    
    # 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录（带颜色）
        
        Args:
            record: 日志记录
            
        Returns:
            格式化后的日志字符串
        """
        # 添加颜色
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        # 格式化
        record.levelname = f"{color}{record.levelname}{reset}"
        
        return super().format(record)


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_file: str = "app.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    enable_console: bool = True,
    enable_file: bool = True,
    enable_structured: bool = False
):
    """
    配置日志系统
    
    Args:
        log_level: 日志级别
        log_dir: 日志目录
        log_file: 日志文件名
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的日志文件数量
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件输出
        enable_structured: 是否使用结构化日志格式
    """
    # 创建日志目录
    if enable_file and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有处理器
    root_logger.handlers.clear()
    
    # 控制台处理器
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper()))
        
        if enable_structured:
            console_formatter = StructuredFormatter()
        else:
            console_formatter = ColoredFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # 文件处理器（带轮转）
    if enable_file:
        log_path = os.path.join(log_dir, log_file)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        
        if enable_structured:
            file_formatter = StructuredFormatter()
        else:
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(funcName)s:%(lineno)d - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # 记录日志配置
    logging.info(
        f"日志系统已配置 - 级别: {log_level}, "
        f"控制台: {enable_console}, "
        f"文件: {enable_file}, "
        f"结构化: {enable_structured}"
    )


def set_log_level(level: str):
    """
    动态设置日志级别
    
    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    for handler in root_logger.handlers:
        handler.setLevel(getattr(logging, level.upper()))
    
    logging.info(f"日志级别已更新为: {level}")


def get_logger(name: str) -> logging.Logger:
    """
    获取日志器
    
    Args:
        name: 日志器名称
        
    Returns:
        Logger 实例
    """
    return logging.getLogger(name)


class LogContext:
    """日志上下文管理器"""
    
    def __init__(self, logger: logging.Logger, **kwargs):
        """
        初始化日志上下文
        
        Args:
            logger: 日志器
            **kwargs: 上下文字段
        """
        self.logger = logger
        self.context = kwargs
    
    def __enter__(self):
        """进入上下文"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        if exc_type:
            self.logger.error(
                f"异常: {exc_val}",
                extra={"context": self.context},
                exc_info=True
            )
    
    def info(self, msg: str, **kwargs):
        """记录 INFO 日志"""
        extra = {"context": {**self.context, **kwargs}}
        self.logger.info(msg, extra=extra)
    
    def warning(self, msg: str, **kwargs):
        """记录 WARNING 日志"""
        extra = {"context": {**self.context, **kwargs}}
        self.logger.warning(msg, extra=extra)
    
    def error(self, msg: str, **kwargs):
        """记录 ERROR 日志"""
        extra = {"context": {**self.context, **kwargs}}
        self.logger.error(msg, extra=extra)


def log_context(logger: logging.Logger, **kwargs) -> LogContext:
    """
    创建日志上下文
    
    Args:
        logger: 日志器
        **kwargs: 上下文字段
        
    Returns:
        LogContext 实例
    
    Example:
        with log_context(logger, user_id=123, skill="execute_gift_issue"):
            # 执行代码
            pass
    """
    return LogContext(logger, **kwargs)
