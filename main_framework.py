"""
框架启动入口 - 仅启动通用网关
"""
import uvicorn
from api.mcp_http_server import app


def main():
    """启动HTTP服务"""
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )


if __name__ == "__main__":
    main()
