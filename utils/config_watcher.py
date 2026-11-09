"""
配置文件监听器

监听配置文件变化，自动重新加载配置
"""
import os
import time
import threading
import logging
from typing import Dict, Callable, Any
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


logger = logging.getLogger(__name__)


class ConfigFileHandler(FileSystemEventHandler):
    """配置文件变更处理器"""
    
    def __init__(self, callback: Callable[[str], None]):
        """
        初始化
        
        Args:
            callback: 配置变更回调函数
        """
        self.callback = callback
        self.last_modified = {}
        self.debounce_seconds = 1  # 防抖时间
    
    def on_modified(self, event: FileModifiedEvent):
        """
        文件修改事件处理
        
        Args:
            event: 文件系统事件
        """
        if event.is_directory:
            return
        
        # 只处理 JSON 配置文件
        if not event.src_path.endswith('.json'):
            return
        
        # 防抖处理（避免重复触发）
        current_time = time.time()
        last_time = self.last_modified.get(event.src_path, 0)
        
        if current_time - last_time < self.debounce_seconds:
            return
        
        self.last_modified[event.src_path] = current_time
        
        # 触发回调
        logger.info(f"检测到配置文件变更: {event.src_path}")
        try:
            self.callback(event.src_path)
        except Exception as e:
            logger.error(f"配置重载失败: {e}", exc_info=True)


class ConfigWatcher:
    """配置监听器"""
    
    def __init__(self):
        """初始化配置监听器"""
        self.observer = Observer()
        self.watched_paths = set()
        self.callbacks = {}
        self.is_running = False
    
    def watch(self, path: str, callback: Callable[[str], None]):
        """
        监听配置目录
        
        Args:
            path: 配置目录路径
            callback: 配置变更回调函数
        """
        if not os.path.exists(path):
            logger.warning(f"配置目录不存在: {path}")
            return
        
        if path in self.watched_paths:
            logger.info(f"配置目录已在监听中: {path}")
            return
        
        # 创建事件处理器
        event_handler = ConfigFileHandler(callback)
        
        # 添加监听
        self.observer.schedule(event_handler, path, recursive=True)
        self.watched_paths.add(path)
        self.callbacks[path] = callback
        
        logger.info(f"开始监听配置目录: {path}")
    
    def start(self):
        """启动监听"""
        if self.is_running:
            logger.warning("配置监听器已在运行中")
            return
        
        if not self.watched_paths:
            logger.warning("没有配置目录需要监听")
            return
        
        self.observer.start()
        self.is_running = True
        logger.info("配置监听器已启动")
    
    def stop(self):
        """停止监听"""
        if not self.is_running:
            return
        
        self.observer.stop()
        self.observer.join()
        self.is_running = False
        logger.info("配置监听器已停止")
    
    def reload_all(self):
        """重新加载所有配置"""
        logger.info("手动重新加载所有配置")
        for path, callback in self.callbacks.items():
            try:
                # 触发所有配置文件的重载
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file.endswith('.json'):
                            file_path = os.path.join(root, file)
                            callback(file_path)
            except Exception as e:
                logger.error(f"配置重载失败 ({path}): {e}", exc_info=True)


# 全局配置监听器实例
_config_watcher = None


def get_config_watcher() -> ConfigWatcher:
    """
    获取全局配置监听器实例
    
    Returns:
        ConfigWatcher 实例
    """
    global _config_watcher
    if _config_watcher is None:
        _config_watcher = ConfigWatcher()
    return _config_watcher


def start_config_watching(paths: list, callback: Callable[[str], None]):
    """
    启动配置监听
    
    Args:
        paths: 配置目录列表
        callback: 配置变更回调函数
    """
    watcher = get_config_watcher()
    
    for path in paths:
        watcher.watch(path, callback)
    
    watcher.start()


def stop_config_watching():
    """停止配置监听"""
    watcher = get_config_watcher()
    watcher.stop()


def reload_all_configs():
    """重新加载所有配置"""
    watcher = get_config_watcher()
    watcher.reload_all()
