#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 一键启动（宝塔兼容版）
# ======================================================================
# 所有服务在后台运行，PID 写到 ./run/，日志写到 ./logs/
# 启动前先跑过 ./install.sh 生成 .env 并装好依赖
#
# 启动列表：
#   - backend  FastAPI (uvicorn)        监听 127.0.0.1:8000
#   - worker   Dramatiq 消费 4 个队列
#   - scheduler  APScheduler 定时任务
#   - frontend  Nuxt 生产 node 服务      监听 127.0.0.1:3000
#
# 然后在宝塔 Nginx 里把域名反代到这两个端口即可（详见 docs/BAOTA.md）
#
# 用法：
#   ./start.sh             启动全部
#   ./start.sh backend     只启动 backend
#   ./start.sh status      查看状态
# ======================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT_DIR/backend"
FRONTEND="$ROOT_DIR/frontend"
RUN="$ROOT_DIR/run"
LOGS="$ROOT_DIR/logs"
PY="$BACKEND/.venv/bin/python"
DRAMATIQ="$BACKEND/.venv/bin/dramatiq"
UVICORN="$BACKEND/.venv/bin/uvicorn"

mkdir -p "$RUN" "$LOGS"

# ---------- 前置检查 ----------
[ -f "$BACKEND/.env" ] || { echo "!! 未找到 $BACKEND/.env，先跑 ./install.sh" >&2; exit 1; }
[ -x "$PY" ] || { echo "!! 未找到 venv，先跑 ./install.sh" >&2; exit 1; }
[ -d "$FRONTEND/.output" ] || { echo "!! 前端未构建，先跑 ./install.sh 或 (cd frontend && pnpm build)" >&2; exit 1; }

# 从 .env 读端口（简单 grep）
get_env() {
    grep -E "^$1=" "$BACKEND/.env" | head -1 | cut -d= -f2-
}
BACKEND_PORT=$(get_env WEB_PORT); BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=$(grep -E "^PORT=" "$FRONTEND/.env" 2>/dev/null | head -1 | cut -d= -f2)
FRONTEND_PORT=${FRONTEND_PORT:-3000}

# ---------- 启停工具 ----------
pidfile() { echo "$RUN/$1.pid"; }
logfile() { echo "$LOGS/$1.log"; }

is_running() {
    local pf="$(pidfile "$1")"
    [ -f "$pf" ] || return 1
    local pid=$(cat "$pf")
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_one() {
    local name="$1"; shift
    if is_running "$name"; then
        echo "  [$name] 已在运行 (pid $(cat "$(pidfile "$name")"))"
        return
    fi
    echo "  [$name] 启动..."
    # 用 nohup + & 把进程放入后台；setsid 保证脱离终端
    setsid "$@" >> "$(logfile "$name")" 2>&1 < /dev/null &
    echo $! > "$(pidfile "$name")"
    sleep 1
    if is_running "$name"; then
        echo "  [$name] ✓ pid=$(cat "$(pidfile "$name")")  日志 $(logfile "$name")"
    else
        echo "  [$name] ✗ 启动失败，查看 $(logfile "$name")"
        return 1
    fi
}

# ---------- 端口占用检测 ----------
# 返回 0 = 占用 / 返回 1 = 空闲
port_in_use() {
    local port="$1"
    ss -tln 2>/dev/null | awk '{print $4}' | grep -Eq ":${port}\$"
}

check_port_free() {
    local name="$1" port="$2"
    if port_in_use "$port"; then
        echo "  [$name] ✗ 端口 $port 已被占用"
        ss -tlnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print "         占用进程: "$0}'
        echo "         用 'kill <pid>' 杀掉旧进程，或改 .env 的端口号"
        return 1
    fi
    return 0
}

# ---------- 各服务启动命令 ----------
start_backend() {
    check_port_free backend "$BACKEND_PORT" || return 1
    cd "$BACKEND"
    start_one backend "$UVICORN" app.main:app \
        --host 127.0.0.1 --port "$BACKEND_PORT" --workers 2
}

start_worker() {
    cd "$BACKEND"
    start_one worker "$DRAMATIQ" \
        app.tasks.actors.crawl \
        --queues crawler.hi crawler.mid crawler.low \
        --processes 1 --threads 4
}

start_scheduler() {
    cd "$BACKEND"
    start_one scheduler "$PY" -m app.scheduler
}

start_frontend() {
    check_port_free frontend "$FRONTEND_PORT" || return 1
    cd "$FRONTEND"
    # 读前端 .env 作为环境
    set -a; source "$FRONTEND/.env"; set +a
    start_one frontend /usr/bin/env node "$FRONTEND/.output/server/index.mjs"
}

# ---------- 状态 ----------
status() {
    for s in backend worker scheduler frontend; do
        if is_running "$s"; then
            echo "  [$s] ✓ running (pid $(cat "$(pidfile "$s")"))"
        else
            echo "  [$s] ✗ stopped"
        fi
    done
}

# ---------- 主逻辑 ----------
cmd="${1:-all}"
case "$cmd" in
    all)
        echo ">>> 启动 luogu-archive"
        start_backend
        start_worker
        start_scheduler
        start_frontend
        echo ""
        echo "监听端口："
        echo "  后端  127.0.0.1:$BACKEND_PORT"
        echo "  前端  127.0.0.1:$FRONTEND_PORT"
        echo ""
        echo "请在宝塔 Nginx 里把域名反代到前端端口（API 走 /api/ 反代到后端）。"
        echo "具体 nginx 片段见 docs/BAOTA.md"
        ;;
    backend)   start_backend ;;
    worker)    start_worker ;;
    scheduler) start_scheduler ;;
    frontend)  start_frontend ;;
    status)    status ;;
    *)
        echo "用法: $0 [all|backend|worker|scheduler|frontend|status]"
        exit 1
        ;;
esac
