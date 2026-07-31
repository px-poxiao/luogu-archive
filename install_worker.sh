#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 远程 worker 一键安装
# ======================================================================
# 用途：在新买的 VPS 上跑这个，把它接入中心机的爬虫网络。
# 工作内容：
#   1. 检查/安装 Python 3.12 venv（Ubuntu 22+/Debian 12 适用）
#   2. 交互式收集中心机 redis / mysql / 密钥信息
#   3. 写 backend/.env，给 NODE_ID 一个唯一值
#   4. 装后端依赖，验证 redis / mysql 连接
#   5. （可选）启动 worker
#
# 前提：
#   - 中心机的 redis 已加密码 + 0.0.0.0 监听 + 防火墙白名单本机 IP
#   - 中心机的 mysql 已 GRANT ... TO 'luogu_archive'@'本机IP' + 防火墙白名单
#   - 这台 VPS 已 git clone / scp 整个项目（至少 backend/ 目录 + start_worker.sh）
#
# 用法：
#   chmod +x install_worker.sh start_worker.sh
#   ./install_worker.sh
# ======================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT_DIR/backend"
BACKEND_ENV="$BACKEND/.env"

echo "================================================="
echo " luogu-archive 远程 worker 安装"
echo "================================================="
echo ""

# ---------- 0. Python 检查 ----------
PYBIN=""
for c in python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
        ver=$("$c" -c 'import sys;print(sys.version_info[:2])' 2>/dev/null || echo "(0,0)")
        case "$ver" in
            *"(3, 11)"*|*"(3, 12)"*|*"(3, 13)"*) PYBIN="$c"; break ;;
        esac
    fi
done
if [[ -z "$PYBIN" ]]; then
    echo "!! 没找到 Python 3.11+。Ubuntu/Debian 装一下："
    echo "   apt install -y python3.12 python3.12-venv python3.12-dev build-essential"
    exit 1
fi
echo "Python: $PYBIN ($("$PYBIN" --version))"
echo ""

# ---------- 1. 交互收集 ----------
ask() {
    local var="$1" prompt="$2" default="${3:-}"
    local val
    if [[ -n "$default" ]]; then
        read -rp "$prompt [$default]: " val
        val="${val:-$default}"
    else
        read -rp "$prompt: " val
    fi
    eval "$var=\$val"
}

ask_secret() {
    local var="$1" prompt="$2"
    local val
    read -rsp "$prompt: " val
    echo
    eval "$var=\$val"
}

DEFAULT_NODE_ID="worker-$(hostname -s 2>/dev/null || echo unknown)-$(date +%s | tail -c5)"

echo "---- 节点身份 ----"
echo "（每台 worker 必须唯一。建议格式 worker-厂商-地域-编号，例如 worker-tencent-sh-01）"
ask NODE_ID "本机 NODE_ID" "$DEFAULT_NODE_ID"
echo ""

echo "---- 中心机 Redis（broker + 限流 / 熔断状态共享）----"
ask REDIS_HOST "Redis 主机（中心机公网 IP 或域名）"
ask REDIS_PORT "Redis 端口" "6379"
ask_secret REDIS_PASSWORD "Redis 密码（中心机 requirepass 设的）"
ask REDIS_DB "Redis DB 编号" "0"
# 拼 URL，密码做 url-encode（简单粗暴：用户名留空，密码原样塞）
REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
echo ""

echo "---- 中心机 MySQL（写 crawl_tasks 等表）----"
ask DB_HOST "MySQL 主机（中心机公网 IP 或域名）"
ask DB_PORT "MySQL 端口" "3306"
ask DB_NAME "数据库名" "luogu_archive"
ask DB_USER "数据库用户名" "luogu_archive"
ask_secret DB_PASSWORD "数据库密码"
echo ""

echo "---- 共享密钥（必须跟中心机 .env 一致）----"
echo "  Cookie 池用 ADMIN_TOTP_ENCRYPTION_KEY 解密，不一致 → cookie 解密失败"
echo "  JWT_SECRET 用于签发管理员令牌，worker 不签发但要保持一致"
ask_secret ADMIN_TOTP_ENCRYPTION_KEY "ADMIN_TOTP_ENCRYPTION_KEY（中心机 .env 同名值）"
ask_secret JWT_SECRET "JWT_SECRET（中心机 .env 同名值）"
echo ""

echo "---- 爬虫出口（可选定制）----"
ask CRAWLER_BASE_URL "默认目标域名" "https://luogu.com"
ask CRAWLER_CONTACT_EMAIL "User-Agent 联系邮箱" "archive-bot@example.com"
echo ""

echo "---- 自动启动 ----"
ask AUTO_START "安装完是否立即启动 worker？(y/n)" "y"
echo ""

# ---------- 2. 写 backend/.env ----------
echo ">>> 写入 $BACKEND_ENV"
mkdir -p "$BACKEND"

cat > "$BACKEND_ENV" <<EOF
# ==== 由 install_worker.sh 生成于 $(date -Iseconds) ====
# 远程 worker 配置。本机不跑 backend/frontend/scheduler，只跑资源队列 worker。

APP_NAME=luogu-archive-worker
APP_ENV=production
APP_DEBUG=false
APP_LOG_LEVEL=INFO
APP_TIMEZONE=Asia/Shanghai

# 节点身份（多 worker 必须唯一）
NODE_ID=$NODE_ID

# Web 字段：worker 不监听 HTTP，但 config.py 要这些字段才能加载
WEB_HOST=127.0.0.1
WEB_PORT=8000
WEB_PUBLIC_ORIGIN=http://127.0.0.1:8000
WEB_CORS_ORIGINS=http://127.0.0.1:8000

# 中心机 MySQL
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5

# 中心机 Redis
REDIS_URL=$REDIS_URL

# 爬虫
CRAWLER_BASE_URL=$CRAWLER_BASE_URL
CRAWLER_FALLBACK_BASE_URL=https://www.luogu.com.cn
CRAWLER_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36
CRAWLER_CONTACT_EMAIL=$CRAWLER_CONTACT_EMAIL
CRAWLER_ANON_RATE_PER_SEC=0.33
CRAWLER_AUTH_RATE_PER_SEC=0.17
CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC=5
CRAWLER_AUTH_QPH_PER_ACCOUNT=300
CRAWLER_BREAKER_COOLDOWN_SEC=300
CRAWLER_GLOBAL_BREAKER_NODE_THRESHOLD=3
CRAWLER_TASK_LOCK_TTL_SEC=30
CRAWLER_REQUEST_TIMEOUT_SEC=15

JUDGEMENT_GROUP_TIME_WINDOW_SEC=1800

# 共享密钥（必须跟中心机一致）
ADMIN_2FA_ISSUER=LuoguArchive
ADMIN_SESSION_MAX_AGE_SEC=3600
ADMIN_TOTP_ENCRYPTION_KEY=$ADMIN_TOTP_ENCRYPTION_KEY
JWT_SECRET=$JWT_SECRET
JWT_ACCESS_TTL_SEC=900
JWT_REFRESH_TTL_SEC=604800

# 邮件 / 验证码 worker 用不到，保留默认避免 config 加载报错
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@example.com
SMTP_USE_TLS=true

CAPTCHA_PROVIDER=none
CAPTCHA_SITE_KEY=
CAPTCHA_SECRET=
CAPTCHA_TRIGGER_SAVE_PER_MIN=3
CAPTCHA_TRIGGER_SAVE_PER_10MIN=10
CAPTCHA_TRIGGER_PAGE_PER_HOUR=600

SAVE_IP_WINDOW_SEC=60
SAVE_IP_WINDOW_MAX=5
SAVE_IP_HOUR_BREAKER_THRESHOLD=10
SAVE_IP_HOUR_BREAKER_COOLDOWN_SEC=3600

DATA_DIR=$ROOT_DIR/data
IMAGE_MIRROR_DIR=$ROOT_DIR/data/image_mirror
IMAGE_MIRROR_PUBLIC_PREFIX=/static/img
IMAGE_MIRROR_MAX_SIZE_MB=20
EOF

mkdir -p "$ROOT_DIR/data/image_mirror"
chmod 600 "$BACKEND_ENV"

# ---------- 3. venv + 依赖 ----------
echo ""
echo ">>> 创建 venv + 装依赖"
cd "$BACKEND"
if [ ! -d .venv ]; then
    if ! "$PYBIN" -m venv .venv 2>&1; then
        echo "!! 创建 venv 失败。装一下："
        echo "   apt install -y python3.12-venv python3.12-dev build-essential"
        exit 1
    fi
fi
. .venv/bin/activate
pip install -U pip wheel setuptools >/dev/null
pip install -e . 2>&1 | tail -5
deactivate

# ---------- 4. 连接验证 ----------
echo ""
echo ">>> 验证中心机连接"
cd "$BACKEND"
. .venv/bin/activate

# Redis ping
REDIS_OK=$(REDIS_URL_CHECK="$REDIS_URL" python - <<'PY' 2>&1 || true
import os, asyncio
from redis.asyncio import from_url

async def main():
    r = from_url(os.environ["REDIS_URL_CHECK"])
    try:
        pong = await r.ping()
        print("REDIS_OK" if pong else "REDIS_FAIL")
    except Exception as e:
        print(f"REDIS_ERR: {e}")
    finally:
        await r.aclose()

asyncio.run(main())
PY
)
echo "  $REDIS_OK"

# MySQL connect
DB_OK=$(
    DB_URL="mysql+aiomysql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME" \
    python - <<'PY' 2>&1 || true
import os, asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DB_URL"])
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("DB_OK")
    except Exception as e:
        print(f"DB_ERR: {e}")
    finally:
        await engine.dispose()

asyncio.run(main())
PY
)
echo "  $DB_OK"
deactivate

if [[ "$REDIS_OK" != REDIS_OK* || "$DB_OK" != DB_OK* ]]; then
    echo ""
    echo "!! 连接验证失败，启动会有问题。检查："
    echo "   - 中心机防火墙是否放行了本机的公网 IP（curl ifconfig.me 取一下）"
    echo "   - Redis 是否 bind 0.0.0.0、requirepass 是否正确"
    echo "   - MySQL 是否 GRANT ... TO '$DB_USER'@'<本机 IP 或 %>'"
    echo ""
    read -rp "仍要继续启动吗？(y/n) " GO_ANYWAY
    if [[ "$GO_ANYWAY" != "y" && "$GO_ANYWAY" != "Y" ]]; then
        exit 1
    fi
fi

# ---------- 5. 启动 ----------
echo ""
echo "================================================="
echo " ✔ 安装完成"
echo "================================================="
echo "  节点 ID: $NODE_ID"
echo "  Redis:   $REDIS_HOST:$REDIS_PORT/$REDIS_DB"
echo "  MySQL:   $DB_HOST:$DB_PORT/$DB_NAME"
echo "================================================="

if [[ "$AUTO_START" == "y" || "$AUTO_START" == "Y" ]]; then
    echo ">>> 启动 worker"
    if [ -x "$ROOT_DIR/start_worker.sh" ]; then
        "$ROOT_DIR/start_worker.sh"
        echo ""
        echo "  日志：tail -f $ROOT_DIR/logs/worker.log"
    else
        echo "!! 未找到 start_worker.sh，请手动 chmod +x 后运行"
    fi
else
    echo ""
    echo "稍后手动启动：./start_worker.sh"
fi
