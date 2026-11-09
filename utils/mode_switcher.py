#!/usr/bin/env python3
"""
配置加载器 - 根据 DEBUG_MODE 自动选择配置文件
"""
import os
import json
import shutil
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def get_debug_mode() -> bool:
    """获取 DEBUG 模式状态"""
    debug_mode = os.getenv('DEBUG_MODE', 'false').lower()
    return debug_mode in ('true', '1', 'yes', 'on')


def load_mcp_servers_config(business_code: str = 'testops', force_reload: bool = False) -> dict:
    """
    加载 MCP 服务器配置
    
    Args:
        business_code: 业务代码
        force_reload: 强制重新加载环境变量
    
    Returns:
        MCP 服务器配置字典
    """
    if force_reload:
        # 重新加载环境变量
        load_dotenv(override=True)
    
    debug_mode = get_debug_mode()
    config_dir = Path(f'config/business/{business_code}')
    
    # 根据 DEBUG_MODE 选择配置文件
    if debug_mode:
        source_file = config_dir / 'mcp_servers.debug.json'
        mode_name = 'DEBUG'
    else:
        source_file = config_dir / 'mcp_servers.prod.json'
        mode_name = 'PRODUCTION'
    
    target_file = config_dir / 'mcp_servers.json'
    
    # 如果源文件存在，复制到目标文件
    if source_file.exists():
        shutil.copy(source_file, target_file)
        print(f"✓ 已加载 {mode_name} 模式配置: {source_file.name} -> {target_file.name}")
    else:
        print(f"⚠ 警告: {mode_name} 模式配置文件不存在: {source_file}")
    
    # 读取并返回配置
    if target_file.exists():
        with open(target_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"配置文件不存在: {target_file}")


def switch_mode(debug_mode: bool, business_code: str = 'testops'):
    """
    切换运行模式
    
    Args:
        debug_mode: True=DEBUG模式，False=生产模式
        business_code: 业务代码
    """
    # 更新 .env 文件
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 更新 DEBUG_MODE 行
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('DEBUG_MODE='):
                lines[i] = f'DEBUG_MODE={str(debug_mode).lower()}\n'
                updated = True
                break
        
        if updated:
            with open(env_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            print(f"✓ 已更新 .env 文件: DEBUG_MODE={str(debug_mode).lower()}")
    
    # 重新加载配置
    load_mcp_servers_config(business_code, force_reload=True)
    
    mode_name = 'DEBUG' if debug_mode else 'PRODUCTION'
    print(f"\n✓ 已切换到 {mode_name} 模式")
    
    if debug_mode:
        print("  - 用户信息查询: 本地数据库服务 (localhost:8004)")
        print("  - 需要启动: python3 mcp_servers/database_mcp_http_server.py")
    else:
        print("  - 用户信息查询: 远程 MCP 服务 (127.0.0.1:8002)")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode in ('debug', 'true', '1', 'on'):
            switch_mode(True)
        elif mode in ('prod', 'production', 'false', '0', 'off'):
            switch_mode(False)
        else:
            print(f"未知模式: {mode}")
            print("用法: python3 utils/config_loader.py [debug|prod]")
    else:
        # 显示当前模式
        debug_mode = get_debug_mode()
        mode_name = 'DEBUG' if debug_mode else 'PRODUCTION'
        print(f"当前模式: {mode_name}")
        print(f"DEBUG_MODE={str(debug_mode).lower()}")
        
        # 加载配置
        config = load_mcp_servers_config()
        user_info_server = config['mcp_servers']['user-info-server']
        print(f"\n用户信息服务:")
        print(f"  - URL: {user_info_server['base_url']}")
        print(f"  - 描述: {user_info_server['description']}")
        
        print("\n切换模式:")
        print("  python3 utils/config_loader.py debug   # 切换到 DEBUG 模式")
        print("  python3 utils/config_loader.py prod    # 切换到生产模式")
