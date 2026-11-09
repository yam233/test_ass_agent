#!/bin/bash
# Ear_test_agent 服务管理脚本
# 用途：启动/停止/重启服务（后台守护进程模式）
# 使用方法：
#   ./start_server.sh start   # 启动服务
#   ./start_server.sh stop    # 停止服务
#   ./start_server.sh restart # 重启服务
#   ./start_server.sh status  # 查看服务状态
#   ./start_server.sh logs    # 查看日志
#   ./start_server.sh follow  # 实时查看日志

set -e  # 遇到错误立即退出

# 获取脚本所在目录并切换到项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 配置
SERVICE_NAME="Ear_test_agent"
PID_FILE=".local_main.pid"
LOG_FILE="logs/server.log"
PORT="${PORT:-8002}"
HOST="${HOST:-127.0.0.1}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN=python3
AGENT_APP="${AGENT_APP:-api.offline_server:app}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_separator() {
    echo "============================================================"
}

# 检查服务是否运行
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            return 0  # 运行中
        else
            rm -f "$PID_FILE"
            return 1  # 未运行
        fi
    fi
    return 1  # 未运行
}

# 获取PID
get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

# 启动服务
start_service() {
    print_separator
    print_info "🚀 启动 $SERVICE_NAME 服务"
    print_separator
    
    # 检查是否已经运行
    if is_running; then
        PID=$(get_pid)
        print_warning "服务已在运行 (PID: $PID)"
        print_info "如需重启，请运行: $0 restart"
        exit 1
    fi
    
    # 1. 检查 Python 环境
    print_info "检查 Python 环境..."
    if ! command -v "$PYTHON_BIN" &> /dev/null; then
        print_error "未找到 python3，请先安装 Python 3.10+"
        exit 1
    fi
    
    PYTHON_VERSION=$("$PYTHON_BIN" --version 2>&1 | awk '{print $2}')
    print_success "Python 版本: $PYTHON_VERSION"
    
    # 2. 检查依赖
    print_info "检查依赖包..."
    MISSING_DEPS=()
    
    if ! "$PYTHON_BIN" -c "import fastapi" 2>/dev/null; then
        MISSING_DEPS+=("fastapi")
    fi
    
    if ! "$PYTHON_BIN" -c "import uvicorn" 2>/dev/null; then
        MISSING_DEPS+=("uvicorn")
    fi
    
    
    if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
        print_error "缺少依赖包: ${MISSING_DEPS[*]}"
        print_info "请运行: $PYTHON_BIN -m pip install -r requirements-offline.txt"
        exit 1
    fi
    
    print_success "依赖检查通过"
    
    # 3. 检查配置文件
    print_info "检查配置文件..."
    
    if [ ! -f ".env" ]; then
        print_warning ".env 文件不存在，将使用代码中的默认配置"
    fi
    
    if [ ! -f "config/framework/agent_config.json" ]; then
        print_error "配置文件不存在: config/framework/agent_config.json"
        exit 1
    fi
    
    print_success "配置文件检查通过"
    
    # 4. 加载环境变量
    print_info "加载环境变量..."
    if [ -f ".env" ]; then
        # 导出 .env 中的环境变量
        set -a
        source .env
        set +a
        print_success "环境变量已加载"
    else
        print_warning ".env 文件不存在，将使用默认配置"
    fi

    # 4.1 校验企微关键变量（仅提示，不阻断启动）
    print_info "检查企微环境变量..."
    WECOM_MISSING=()
    [ -z "${WECOM_TOKEN:-}" ] && WECOM_MISSING+=("WECOM_TOKEN")
    [ -z "${WECOM_ENCODING_AES_KEY:-}" ] && WECOM_MISSING+=("WECOM_ENCODING_AES_KEY")
    [ -z "${WECOM_CORP_ID:-}" ] && WECOM_MISSING+=("WECOM_CORP_ID")
    [ -z "${WECOM_AGENT_ID:-}" ] && WECOM_MISSING+=("WECOM_AGENT_ID")
    [ -z "${WECOM_SECRET:-}" ] && WECOM_MISSING+=("WECOM_SECRET")

    if [ ${#WECOM_MISSING[@]} -gt 0 ]; then
        print_warning "企微变量未完整配置: ${WECOM_MISSING[*]}"
        print_warning "若需启用企微回调，请补齐 .env 后重启服务"
    else
        print_success "企微变量检查通过"
    fi
    
    # 5. 创建日志目录
    mkdir -p logs
    
    # 6. 检查端口占用
    if command -v lsof &> /dev/null; then
        PORT_PID=$(lsof -ti:$PORT 2>/dev/null || true)
        if [ ! -z "$PORT_PID" ]; then
            print_error "端口 $PORT 已被占用 (PID: $PORT_PID)，请换 PORT 或手动停止对应服务"
            exit 1
        fi
    fi
    
    # 7. 设置环境变量
    export DEBUG_MODE=true
    export PYTHONPATH=$PWD

    # 8. 启动服务（后台守护进程）
    print_separator
    print_info "启动服务（后台守护进程模式）..."
    echo ""
    echo "🎁 $SERVICE_NAME MCP HTTP 服务器"
    echo "=================================================="
    echo "端口: $PORT"
    echo "地址: http://$HOST:$PORT"
    echo "API文档: http://localhost:$PORT/docs"
    echo "健康检查: http://localhost:$PORT/"
    echo "日志文件: $LOG_FILE"
    echo "=================================================="
    echo ""
    
    # 使用 nohup 启动后台守护进程
    nohup "$PYTHON_BIN" -m uvicorn "$AGENT_APP" \
        --host "$HOST" \
        --port "$PORT" \
        --log-level info \
        > "$LOG_FILE" 2>&1 &
    
    PID=$!
    echo "$PID" > "$PID_FILE"
    
    # 等待进程启动
    sleep 1
    
    # 验证进程是否存在
    if ! kill -0 "$PID" 2>/dev/null; then
        print_error "服务进程启动失败"
        print_info "查看日志: tail -f $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
    
    print_info "进程 PID: $PID"
    
    # 等待服务初始化
    print_info "等待服务初始化..."
    sleep 3
    
    # 健康检查（重试机制）
    MAX_RETRIES=10
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s "http://localhost:$PORT/" > /dev/null 2>&1; then
            print_success "服务启动成功！"
            break
        fi
        
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            print_info "等待中... ($RETRY_COUNT/$MAX_RETRIES)"
            sleep 2
        fi
    done
    
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        print_error "服务启动失败或超时"
        print_info "查看日志: tail -f $LOG_FILE"
        print_warning "服务进程仍在运行，请手动检查"
        exit 1
    fi
    
    # 显示服务信息
    print_separator
    print_success "✅ 服务启动完成！（后台守护进程模式）"
    print_separator
    echo ""
    echo "📋 服务信息:"
    echo "  🔹 服务名称: $SERVICE_NAME"
    echo "  🔹 进程 PID: $PID"
    echo "  🔹 服务地址: http://localhost:$PORT"
    echo "  🔹 API 文档: http://localhost:$PORT/docs"
    echo "  🔹 日志文件: $LOG_FILE"
    echo "  🔹 企微回调: ${WECOM_CORP_ID:+已配置}${WECOM_CORP_ID:-未配置}"
    echo ""
    echo "🧪 测试命令:"
    echo "  curl -X POST http://localhost:$PORT/agent/execute \\"
    echo "    -H \"Content-Type: application/json\" \\"
    echo "    -d '{\"business_code\": \"ear_test\", \"user_input\": \"查询用户9075333的信息\"}'"
    echo ""
    echo "📝 管理命令:"
    echo "  $0 status         # 查看服务状态"
    echo "  $0 logs           # 查看最近日志"
    echo "  $0 follow         # 实时查看日志"
    echo "  $0 stop           # 停止服务"
    echo "  $0 restart        # 重启服务"
    echo ""
    print_separator
    print_success "✨ 服务已在后台运行，可以安全退出终端"
    print_info "💡 提示: SSH 断开连接后服务将继续运行"
}

# 停止服务
stop_service() {
    print_separator
    print_info "🛑 停止 $SERVICE_NAME 服务"
    print_separator
    
    if ! is_running; then
        print_warning "服务未运行"
        
        # 清理残留进程
        if command -v lsof &> /dev/null; then
            PORT_PID=$(lsof -ti:$PORT 2>/dev/null || true)
            if [ ! -z "$PORT_PID" ]; then
                print_info "发现端口 $PORT 上的残留进程 (PID: $PORT_PID)，正在清理..."
                kill "$PORT_PID" 2>/dev/null && print_success "已清理残留进程" || true
            fi
        fi
        
        return 0
    fi
    
    PID=$(get_pid)
    print_info "停止服务进程 (PID: $PID)..."
    
    # 优雅停止（SIGTERM）
    if kill "$PID" 2>/dev/null; then
        # 等待进程退出
        for i in {1..10}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                print_success "服务已停止"
                rm -f "$PID_FILE"
                return 0
            fi
            sleep 1
        done
        
        # 强制停止（SIGKILL）
        print_warning "进程未响应，强制停止..."
        kill -9 "$PID" 2>/dev/null || true
        sleep 1
    fi
    
    # 清理 PID 文件
    rm -f "$PID_FILE"
    
    # 验证是否停止
    if kill -0 "$PID" 2>/dev/null; then
        print_error "无法停止服务进程"
        exit 1
    else
        print_success "服务已停止"
    fi
}

# 查看服务状态
check_status() {
    print_separator
    print_info "📊 $SERVICE_NAME 服务状态"
    print_separator
    
    if is_running; then
        PID=$(get_pid)
        print_success "服务状态: 运行中"
        echo ""
        echo "📍 基本信息:"
        echo "  进程 PID: $PID"
        echo "  服务地址: http://localhost:$PORT"
        echo "  API 文档: http://localhost:$PORT/docs"
        echo ""
        
        # 健康检查
        echo "🏥 健康检查:"
        if curl -s "http://localhost:$PORT/" > /dev/null 2>&1; then
            echo "  ✅ 服务响应正常"
        else
            echo "  ⚠️  服务无响应（可能正在启动或异常）"
        fi
        echo ""
        
        # 进程信息
        if command -v ps &> /dev/null; then
            echo "🔧 进程信息:"
            ps -p "$PID" -o pid,ppid,%cpu,%mem,etime,cmd 2>/dev/null | tail -n +2 | sed 's/^/  /' || echo "  无法获取进程信息"
            echo ""
        fi
        
        # 日志信息
        if [ -f "$LOG_FILE" ]; then
            LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
            LOG_LINES=$(wc -l < "$LOG_FILE")
            echo "� 日志信息:"
            echo "  文件路径: $LOG_FILE"
            echo "  文件大小: $LOG_SIZE"
            echo "  日志行数: $LOG_LINES"
            echo ""
        fi
        
        print_separator
        return 0
    else
        print_warning "服务状态: 未运行"
        echo ""
        echo "💡 提示: 运行 '$0 start' 启动服务"
        print_separator
        return 1
    fi
}

# 查看日志
view_logs() {
    local lines=${1:-50}
    
    print_separator
    print_info "📝 查看最近 $lines 行日志"
    print_separator
    
    if [ -f "$LOG_FILE" ]; then
        tail -n "$lines" "$LOG_FILE"
    else
        print_warning "日志文件不存在: $LOG_FILE"
    fi
}

# 实时查看日志
follow_logs() {
    print_separator
    print_info "📝 实时查看日志 (按 Ctrl+C 退出)"
    print_separator
    
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        print_warning "日志文件不存在: $LOG_FILE"
        print_info "等待日志文件创建..."
        
        # 等待日志文件创建
        while [ ! -f "$LOG_FILE" ]; do
            sleep 1
        done
        
        tail -f "$LOG_FILE"
    fi
}

# 重启服务
restart_service() {
    print_info "🔄 重启服务..."
    stop_service
    sleep 2
    start_service
}

# 显示帮助信息
show_help() {
    echo "使用方法: $0 {start|stop|restart|status|logs|follow}"
    echo ""
    echo "命令说明:"
    echo "  start          启动服务（后台守护进程）"
    echo "  stop           停止服务"
    echo "  restart        重启服务"
    echo "  status         查看服务状态"
    echo "  logs [N]       查看最近N行日志（默认50行）"
    echo "  follow         实时查看日志"
    echo ""
    echo "示例:"
    echo "  $0 start       # 启动服务"
    echo "  $0 status      # 查看状态"
    echo "  $0 logs 100    # 查看最近100行日志"
    echo "  $0 follow      # 实时查看日志"
    echo "  $0 restart     # 重启服务"
    echo "  $0 stop        # 停止服务"
}

# 主函数
main() {
    local command=${1:-}
    
    if [ -z "$command" ]; then
        show_help
        exit 1
    fi
    
    case "$command" in
        start)
            start_service
            ;;
        stop)
            stop_service
            ;;
        restart)
            restart_service
            ;;
        status)
            check_status
            ;;
        logs)
            view_logs "${2:-50}"
            ;;
        follow)
            follow_logs
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $command"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
