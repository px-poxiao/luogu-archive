#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 一键停止
# ======================================================================
# 用法：
#   ./stop.sh           停全部
#   ./stop.sh backend   只停 backend
# ======================================================================

set -u

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN="$ROOT_DIR/run"

stop_one() {
    local name="$1"
    local pf="$RUN/$name.pid"
    if [ ! -f "$pf" ]; then
        echo "  [$name] 没有 pid 文件（未运行？）"
        return
    fi
    local pid=$(cat "$pf")
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        echo "  [$name] 进程不存在，清理 pid 文件"
        rm -f "$pf"
        return
    fi
    echo "  [$name] 发送 SIGTERM 到 pid $pid"
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        sleep 1
        kill -0 "$pid" 2>/dev/null || break
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "  [$name] 仍在运行，强制 SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
    fi
    # 同进程组也 kill 一下（setsid 启动的）
    kill -- -"$pid" 2>/dev/null || true
    rm -f "$pf"
    echo "  [$name] ✓ 已停止"
}

cmd="${1:-all}"
case "$cmd" in
    all)
        echo ">>> 停止 luogu-archive"
        for s in frontend scheduler worker backend; do
            stop_one "$s"
        done
        ;;
    backend|worker|scheduler|frontend)
        stop_one "$cmd"
        ;;
    *)
        echo "用法: $0 [all|backend|worker|scheduler|frontend]"
        exit 1
        ;;
esac
