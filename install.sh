#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 交互式安装向导（宝塔兼容版）
# ======================================================================
# 假设你已在宝塔里装好：MySQL / Redis / Python 3.11+ / Node 20+
# 并且已在宝塔里建好数据库、拿到连接信息
#
# 本脚本只做：
#   1. 交互式收集配置（数据库地址、域名、密码等）
#   2. 生成两个密钥（Fernet / JWT）
#   3. 写入 backend/.env 和 frontend/.env
#   4. 建 venv、装依赖、跑 alembic 迁移
#   5. 建前端 build
#   6. 引导用户创建第一个管理员
#
# 运行完成后直接 ./start.sh 即可启动全部服务。
#
# 用法（在项目根目录执行）：
#   chmod +x install.sh start.sh stop.sh
#   ./install.sh
# ======================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT_DIR/backend"
FRONTEND="$ROOT_DIR/frontend"
BACKEND_ENV="$BACKEND/.env"
FRONTEND_ENV="$FRONTEND/.env"

echo "========================================"
echo " luogu-archive 安装向导"
echo "========================================"
echo "本脚本将交互式收集配置并生成 .env。"
echo "如果已有 .env 且不想重装，直接运行 ./start.sh 即可。"
echo ""

# ---------- 0. 前置检查 ----------
need() {
    command -v "$1" >/dev/null 2>&1 || { echo "!! 缺少 $1，请在宝塔里安装"; exit 1; }
}

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
    echo "!! 未找到 Python 3.11+，请在宝塔里装 Python 3.11 或更高"
    exit 1
fi
echo "使用 Python: $PYBIN ($("$PYBIN" --version))"

need node
need npm
if ! command -v pnpm >/dev/null 2>&1; then
    echo ">>> 未检测到 pnpm，用 npm 安装一个全局 pnpm"
    npm install -g pnpm
fi
need pnpm
echo "Node: $(node -v)，pnpm: $(pnpm -v)"
echo ""

# ---------- 1. 交互收集 ----------
ask() {
    # ask <变量名> <提示语> [默认值]
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

echo "---- 数据库（宝塔 MySQL）----"
ask DB_HOST "MySQL 主机" "127.0.0.1"
ask DB_PORT "MySQL 端口" "3306"
ask DB_NAME "数据库名" "luogu_archive"
ask DB_USER "数据库用户名" "luogu_archive"
ask_secret DB_PASSWORD "数据库密码"
echo ""

echo "---- Redis（宝塔 Redis）----"
ask REDIS_URL "Redis 连接串" "redis://127.0.0.1:6379/0"
echo ""

echo "---- 站点 ----"
ask SITE_DOMAIN "站点域名（不带 https://，例如 archive.example.com）"
ask APP_ENV "运行环境 (development/staging/production)" "production"
echo ""

echo "---- 爬虫 ----"
ask CRAWLER_BASE_URL "爬取目标域名" "https://luogu.com"
ask CRAWLER_CONTACT_EMAIL "User-Agent 里的联系邮箱"
echo ""

echo "---- SMTP（发邮箱验证）----"
ask SMTP_HOST "SMTP 主机（留空跳过，将来在 .env 手改）" ""
SMTP_PORT="" SMTP_USER="" SMTP_PASSWORD="" SMTP_FROM="" SMTP_USE_TLS="true"
if [[ -n "$SMTP_HOST" ]]; then
    ask SMTP_PORT "SMTP 端口" "587"
    ask SMTP_USER "SMTP 用户名"
    ask_secret SMTP_PASSWORD "SMTP 密码"
    ask SMTP_FROM "发件人地址" "$SMTP_USER"
fi
echo ""

echo "---- 人机验证（可选，留空跳过）----"
ask CAPTCHA_SITE_KEY "Turnstile Site Key" ""
CAPTCHA_SECRET=""
if [[ -n "$CAPTCHA_SITE_KEY" ]]; then
    ask_secret CAPTCHA_SECRET "Turnstile Secret"
fi
echo ""

echo "---- 服务监听端口（绑 127.0.0.1，由宝塔 Nginx 反代）----"
ask BACKEND_PORT "后端 FastAPI 端口" "8000"
ask FRONTEND_PORT "前端 Nuxt 端口" "3000"
echo ""

# ---------- 2. 生成密钥 ----------
echo ">>> 生成 Fernet / JWT 密钥"
FERNET_KEY=$("$PYBIN" -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
JWT_SECRET=$("$PYBIN" -c "import secrets;print(secrets.token_hex(32))")

# ---------- 3. 写 backend/.env ----------
echo ">>> 写入 $BACKEND_ENV"
cat > "$BACKEND_ENV" <<EOF
# ==== 由 install.sh 生成于 $(date -Iseconds) ====

APP_NAME=luogu-archive
APP_ENV=$APP_ENV
APP_DEBUG=$([ "$APP_ENV" = "production" ] && echo false || echo true)
APP_LOG_LEVEL=INFO
APP_TIMEZONE=Asia/Shanghai

# Web 服务
WEB_HOST=127.0.0.1
WEB_PORT=$BACKEND_PORT
WEB_PUBLIC_ORIGIN=https://$SITE_DOMAIN
WEB_CORS_ORIGINS=https://$SITE_DOMAIN

# MySQL
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Redis
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

# 陶片合并窗口
JUDGEMENT_GROUP_TIME_WINDOW_SEC=1800

# 管理员
ADMIN_2FA_ISSUER=LuoguArchive
ADMIN_SESSION_MAX_AGE_SEC=3600
ADMIN_TOTP_ENCRYPTION_KEY=$FERNET_KEY

# JWT
JWT_SECRET=$JWT_SECRET
JWT_ACCESS_TTL_SEC=900
JWT_REFRESH_TTL_SEC=604800

# 邮件
SMTP_HOST=$SMTP_HOST
SMTP_PORT=${SMTP_PORT:-587}
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
SMTP_FROM=${SMTP_FROM:-noreply@example.com}
SMTP_USE_TLS=$SMTP_USE_TLS

# 人机验证
CAPTCHA_PROVIDER=$([ -n "$CAPTCHA_SITE_KEY" ] && echo turnstile || echo none)
CAPTCHA_SITE_KEY=$CAPTCHA_SITE_KEY
CAPTCHA_SECRET=$CAPTCHA_SECRET
CAPTCHA_TRIGGER_SAVE_PER_MIN=3
CAPTCHA_TRIGGER_SAVE_PER_10MIN=10
CAPTCHA_TRIGGER_PAGE_PER_HOUR=600

# 保存按钮
SAVE_IP_WINDOW_SEC=60
SAVE_IP_WINDOW_MAX=5
SAVE_IP_HOUR_BREAKER_THRESHOLD=10
SAVE_IP_HOUR_BREAKER_COOLDOWN_SEC=3600

# 图片镜像
IMAGE_MIRROR_DIR=$ROOT_DIR/data/image_mirror
IMAGE_MIRROR_PUBLIC_PREFIX=/static/img
IMAGE_MIRROR_MAX_SIZE_MB=20

DATA_DIR=$ROOT_DIR/data
EOF

mkdir -p "$ROOT_DIR/data/image_mirror"
chmod 600 "$BACKEND_ENV"

# ---------- 4. 写 frontend/.env ----------
echo ">>> 写入 $FRONTEND_ENV"
cat > "$FRONTEND_ENV" <<EOF
NUXT_API_INTERNAL_URL=http://127.0.0.1:$BACKEND_PORT
NUXT_PUBLIC_API_BASE_URL=https://$SITE_DOMAIN
NUXT_PUBLIC_CAPTCHA_PROVIDER=$([ -n "$CAPTCHA_SITE_KEY" ] && echo turnstile || echo none)
NUXT_PUBLIC_CAPTCHA_SITE_KEY=$CAPTCHA_SITE_KEY
PORT=$FRONTEND_PORT
HOST=127.0.0.1
EOF

# ---------- 5. Python venv + 依赖 ----------
echo ">>> 创建 Python 虚拟环境（backend/.venv）"
cd "$BACKEND"
if [ ! -d .venv ]; then
    if ! "$PYBIN" -m venv .venv 2>&1; then
        echo ""
        echo "!! 创建 venv 失败。Ubuntu 24+ 需要先装 venv 包："
        echo "   sudo apt install -y python3.12-venv python3.12-dev build-essential"
        echo "   然后 rm -rf backend/.venv，重跑 ./install.sh"
        exit 1
    fi
fi
if [ ! -f .venv/bin/activate ]; then
    echo "!! .venv/bin/activate 不存在，venv 创建不完整。"
    echo "   sudo apt install -y python3.12-venv python3.12-dev build-essential"
    echo "   然后 rm -rf backend/.venv，重跑 ./install.sh"
    exit 1
fi
. .venv/bin/activate
pip install -U pip wheel setuptools >/dev/null
echo ">>> 安装后端依赖"
pip install -e . >/dev/null 2>&1 || pip install -e .
deactivate

# ---------- 6. 数据库迁移 ----------
echo ">>> 尝试连接 MySQL 并跑迁移"
cd "$BACKEND"
. .venv/bin/activate
if ! alembic upgrade head; then
    echo ""
    echo "!! 数据库迁移失败。"
    echo "   请确认宝塔 MySQL 里已建好库 '$DB_NAME' 并授权给 '$DB_USER'，"
    echo "   可用宝塔面板 → 数据库 → 新增。"
    echo "   修复后，再运行：./install.sh"
    deactivate
    exit 1
fi
deactivate

# ---------- 7. 前端依赖 + 构建 ----------
echo ">>> 安装前端依赖（pnpm install）"
cd "$FRONTEND"
# 第一次没 lockfile 会报 ERR_PNPM_NO_LOCKFILE，兜底用普通 install
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
echo ">>> 构建前端（pnpm build）"
pnpm build

# ---------- 8. 引导创建管理员 ----------
cd "$BACKEND"
. .venv/bin/activate
ADMIN_CNT=$(python -c "
import asyncio
from sqlalchemy import func, select
from app.core.db import db_session
from app.models.admin import Admin
async def main():
    async with db_session() as s:
        print(int((await s.execute(select(func.count()).select_from(Admin))).scalar_one()))
asyncio.run(main())
")
if [[ "$ADMIN_CNT" -eq 0 ]]; then
    echo ""
    echo ">>> 还没有管理员，交互式创建："
    python -m scripts.create_admin
    echo ""
    echo "** TOTP secret 只显示一次，请立即添加到 Authenticator 应用 **"
fi
deactivate

# ---------- 9. 完成 ----------
cd "$ROOT_DIR"
echo ""
echo "======================================"
echo " ✔ 安装完成"
echo "======================================"
echo ""
echo " 下一步：./start.sh 启动所有服务"
echo ""
echo " 宝塔 Nginx 反代配置参考：docs/BAOTA.md"
echo "======================================"
