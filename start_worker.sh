#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 远程 worker 启动脚本
# ======================================================================
# 在多机部署下，每台远程 worker 机只跑 dramatiq 消费爬虫任务，不跑
# backend / frontend / scheduler。中心机的 redis 必须可远程访问，
# 中心机的 mysql 也必须可远程访问（worker 要写 crawl_tasks 等表）。
#
# 部署清单（每台远程 worker 机）：
#   1. 装 python3.12 + venv + 依赖（同 install.sh 一样的步骤，但跳过 mysql/redis 安装）
#   2. 把 backend/ 目录拷过去，frontend/ 不需要
#   3. 在 backend/.env 里至少配：
#        NODE_ID=worker-tencent-sh-01      ← 唯一节点身份
#        REDIS_URL=redis://:密码@中心机 IP:6379/0
#        DB_HOST=中心机 IP
#        DB_USER=luogu_archive
#        DB_PASSWORD=...
#        DB_NAME=luogu_archive
#        ADMIN_TOTP_ENCRYPTION_KEY=...     ← 解密 cookie 必需，跟中心机一致
#        JWT_SECRET=...                    ← 跟中心机一致
#        WEB_PUBLIC_ORIGIN / WEB_CORS_ORIGINS 随便填，worker 不接 HTTP 请求
#   4. ./start_worker.sh
#
# 中心机的 redis / mysql 要做：
#   - redis 加密码 + bind 0.0.0.0 + 防火墙白名单 worker 公网 IP + 6379
#   - mysql 加 luogu_archive 用户的远程访问授权 + 3306 白名单
# ======================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT_DIR/backend"
RUN="$ROOT_DIR/run"
LOGS="$ROOT_DIR/logs"
PY="$BACKEND/.venv/bin/python"
DRAMATIQ="$BACKEND/.venv/bin/dramatiq"

mkdir -p "$RUN" "$LOGS"

[ -f "$BACKEND/.env" ] || { echo "!! 缺 $BACKEND/.env" >&2; exit 1; }
[ -x "$DRAMATIQ" ] || { echo "!! 缺 venv，先安装依赖" >&2; exit 1; }

NODE_ID=$(grep -E "^NODE_ID=" "$BACKEND/.env" | head -1 | cut -d= -f2-)
[ -n "$NODE_ID" ] || { echo "!! .env 必须有 NODE_ID（每台 worker 唯一）" >&2; exit 1; }
echo ">>> 启动远程 worker，节点 ID = $NODE_ID"

PIDFILE="$RUN/worker.pid"
LOGFILE="$LOGS/worker.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "  worker 已在运行 (pid $(cat "$PIDFILE"))"
    exit 0
fi

cd "$BACKEND"
setsid "$DRAMATIQ" \
    app.tasks.actors.crawl \
    --queues crawler.hi crawler.mid crawler.low crawler.feed \
    --processes 1 --threads 4 \
    >> "$LOGFILE" 2>&1 < /dev/null &
echo $! > "$PIDFILE"

sleep 1
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "  ✓ worker pid=$(cat "$PIDFILE")，日志 $LOGFILE"
else
    echo "  ✗ 启动失败，看 $LOGFILE"
    exit 1
fi
