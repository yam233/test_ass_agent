"""
数据库与本地脚本路径配置

安全说明：
- 数据库配置已迁移到 config/framework/database_config.json
- 敏感信息统一在配置文件中管理
- 配置文件可以推送到远程仓库（内部项目）
"""
from utils.env_loader import get_env_str, get_env_int, get_env_bool
from utils.config_loader import ConfigLoader


def _load_llm_defaults():
    """从框架配置读取 LLM 默认值（单一配置来源）"""
    try:
        cfg = ConfigLoader.load_framework_config("agent_config.json")
        llm = cfg.get("llm", {})
        return {
            "api_key": llm.get("api_key"),
            "model": llm.get("model"),
            "base_url": llm.get("api_base"),
        }
    except Exception:
        return {"api_key": None, "model": None, "base_url": None}


_llm_defaults = _load_llm_defaults()

# ============ 数据库配置 ============
DB_CONFIG = {
    "host": get_env_str("DB_HOST", "localhost"),
    "port": get_env_int("DB_PORT", 3306),
    "user": get_env_str("DB_USER", "live_service"),
    "password": get_env_str("DB_PASSWORD", required=True),  # 必填，从环境变量读取
    "database": get_env_str("DB_DATABASE", "example_db"),
    "charset": get_env_str("DB_CHARSET", "utf8mb3")
}

# 用户数据库配置（用于验证用户ID）
USER_DB_CONFIG = {
    "host": get_env_str("USER_DB_HOST", "localhost"),
    "port": get_env_int("USER_DB_PORT", 3306),
    "user": get_env_str("USER_DB_USER", "testops_sso"),
    "password": get_env_str("USER_DB_PASSWORD", required=True),  # 必填，从环境变量读取
    "database": get_env_str("USER_DB_DATABASE", "example_db"),
    "charset": get_env_str("USER_DB_CHARSET", "utf8mb3")
}

# ============ MongoDB 配置 ============
# 优先使用连接字符串，如果未设置则使用独立参数
_mongo_connection_string = get_env_str("MONGO_CONNECTION_STRING", "")

if _mongo_connection_string:
    MONGO_CONFIG = {
        "connection_string": _mongo_connection_string,
        "host": get_env_str("MONGO_HOST", "localhost"),
        "port": get_env_int("MONGO_PORT", 3717),
        "username": get_env_str("MONGO_USERNAME", "pma"),
        "password": get_env_str("MONGO_PASSWORD", required=True),  # 必填，从环境变量读取
        "database": get_env_str("MONGO_DATABASE", "fm"),
        "auth_source": get_env_str("MONGO_AUTH_SOURCE", "admin")
    }
else:
    MONGO_CONFIG = {
        "connection_string": "",
        "host": get_env_str("MONGO_HOST", "localhost"),
        "port": get_env_int("MONGO_PORT", 3717),
        "username": get_env_str("MONGO_USERNAME", "pma"),
        "password": get_env_str("MONGO_PASSWORD", required=True),  # 必填，从环境变量读取
        "database": get_env_str("MONGO_DATABASE", "fm"),
        "auth_source": get_env_str("MONGO_AUTH_SOURCE", "admin")
    }

# MongoDB集合配置（注意：配置中有 prefix: 'test_'，所以实际集合名是 test_gifts、test_rooms 和 test_user_items）
MONGO_COLLECTIONS = {
    "gifts": "test_gifts",  # 礼物集合（前缀已包含在集合名中）
    "rooms": "test_rooms",  # 直播间集合（前缀已包含在集合名中）
    "user_items": "test_user_items"  # 用户背包物品集合（前缀已包含在集合名中）
}


# ============ Redis 配置 ============
REDIS_CONFIG = {
    "host": get_env_str("REDIS_HOST", "internal.example.invalid"),
    "port": get_env_int("REDIS_PORT", 6379),
    "password": get_env_str("REDIS_PASSWORD", required=True),  # 必填，从环境变量读取
    "db": get_env_int("REDIS_DB", 0),
}

# Redis Manager Cookie配置（用于查询验证码）
# 获取方法：登录 https://internal.example.invalid/app/redis-manager/console 后，从浏览器开发者工具中复制Cookie
# 也可以通过环境变量 REDIS_MANAGER_COOKIE 设置
REDIS_MANAGER_COOKIE = get_env_str("REDIS_MANAGER_COOKIE", "")

# ============ 本地路径配置 ============
# 本地 testops_test 项目根目录（用于运行测试脚本）
testops_TEST_ROOT = get_env_str("testops_TEST_ROOT", "/Users/yy/testops_test")

# phpMyAdmin / Mongo 管理入口（仅供参考）
# https://internal.example.invalid/app/pma/index.php?route=/table/search&db=example_db&table=live_custom
# 用户表：https://internal.example.invalid/app/pma/index.php?route=/table/sql&db=example_db&table=m_user
# 礼物：https://internal.example.invalid/app/adminmongo/app/UAT/fm/test_gifts/view/1
# 直播间：https://internal.example.invalid/app/adminmongo/app/UAT/fm/test_rooms/view/1
# 用户背包：https://internal.example.invalid/app/adminmongo/app/UAT/fm/test_user_items/view/1


# ============ Grafana 配置 ============
GRAFANA_CONFIG = {
    "username": get_env_str("GRAFANA_USERNAME", required=True),  # 必填，从环境变量读取
    "password": get_env_str("GRAFANA_PASSWORD", required=True),  # 必填，从环境变量读取
}

# ============ 企微机器人配置 ============
WECOM_CONFIG = {
    # ============ 回调配置（Webhook回调模式，必填）============
    "token": get_env_str("WECOM_TOKEN", ""),
    "encoding_aes_key": get_env_str("WECOM_ENCODING_AES_KEY", ""),
    
    # ============ 机器人配置 ============
    "bot_name": get_env_str("WECOM_BOT_NAME", "Ear"),
    
    # ============ 发送消息配置 ============
    "webhook_url": get_env_str("WECOM_WEBHOOK_URL", required=True),  # 必填，从环境变量读取
    
    # ============ 模型配置（可选）============
    "agent_config": {
        "type": get_env_str("LLM_TYPE", "openai"),
        "base_url": get_env_str("LLM_BASE_URL", _llm_defaults["base_url"]),
        "api_key": get_env_str("LLM_API_KEY", _llm_defaults["api_key"]),
        "model": get_env_str("LLM_MODEL", _llm_defaults["model"])
    }
}


# ============ 测试工具配置 ============
# 测试工具平台（发钻石）：host 必填，sid 可选（若填则不再通过 Socket.IO 拉取）
# 发钻石可走测试平台或自定义接口，具体参数见下方 TEST_TOOL_CONFIG
TEST_TOOL_CONFIG = {
    "host": get_env_str("TEST_TOOL_HOST", "http://internal.example.invalid/"),
    "sid": get_env_str("TEST_TOOL_SID", None),
    "diamond_provider": get_env_str("TEST_TOOL_DIAMOND_PROVIDER", "test_platform"),
    "diamond_custom_url": get_env_str("TEST_TOOL_DIAMOND_CUSTOM_URL", None),
    "diamond_custom_method": get_env_str("TEST_TOOL_DIAMOND_CUSTOM_METHOD", "POST"),
    "diamond_custom_headers": None,  # 可通过环境变量设置 JSON 格式
}
