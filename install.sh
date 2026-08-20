#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 交互式安装向导（宝塔 / Ubuntu / Dev Container 兼容版）
# ======================================================================
# 假设已安装：
#   MySQL / Redis / Python 3.11+ / Node 22+
#
# 本脚本负责：
#   1. 检查运行环境
#   2. 收集数据库配置
#   3. 自动创建数据库和应用数据库用户
#   4. 支持 Ubuntu/Debian MySQL root auth_socket
#   5. 生成 Fernet / JWT 密钥
#   6. 写入 backend/.env 和 frontend/.env
#   7. 创建 Python venv 并安装依赖
#   8. 执行基线数据库迁移
#   9. 将 Alembic 标记到 head
#  10. 安装并构建前端
#  11. 引导创建第一个管理员
# ======================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT_DIR/backend"
FRONTEND="$ROOT_DIR/frontend"
BACKEND_ENV="$BACKEND/.env"
FRONTEND_ENV="$FRONTEND/.env"

# 当前项目采用的数据库基线迁移。
BASE_MIGRATION="20260510_0001"

echo "========================================"
echo " luogu-archive 安装向导"
echo "========================================"
echo "本脚本将交互式收集配置并生成 .env。"
echo "如果已有 .env 且不想重装，直接运行 ./start.sh 即可。"
echo ""

if [[ -f "$BACKEND_ENV" || -f "$FRONTEND_ENV" ]]; then
    echo ">>> 检测到已有 .env ，请确认是否覆盖"
    if [[ -f "$BACKEND_ENV" ]]; then
        echo "  - $BACKEND_ENV"
    fi
    if [[ -f "$FRONTEND_ENV" ]]; then
        echo "  - $FRONTEND_ENV"
    fi
    read -rp "覆盖现有配置？[y/N]: " OVERWRITE_EXISTING
    case "${OVERWRITE_EXISTING:-N}" in
        [Yy]|[Yy][Ee][Ss])
            ;;
        *)
            echo "已跳过安装，保留现有 .env 配置。"
            exit 0
            ;;
    esac
fi

# ---------- 0. 基础函数 ----------

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo ""
        echo "!! 缺少 $1，请先安装。"
        exit 1
    }
}

ask() {
    local var="$1"
    local prompt="$2"
    local default="${3:-}"
    local val

    if [[ -n "$default" ]]; then
        read -rp "$prompt [$default]: " val
        val="${val:-$default}"
    else
        read -rp "$prompt: " val
    fi

    printf -v "$var" '%s' "$val"
}

ask_secret() {
    local var="$1"
    local prompt="$2"
    local val

    read -rsp "$prompt: " val
    echo

    printf -v "$var" '%s' "$val"
}

# 确保 .env 值能安全写回文件。
# 需要转义反斜杠、双引号、美元符号和换行。
dotenv_escape() {
    local value="${1}"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//\$/\\$}"
    value="${value//$'\n'/\\n}"
    printf '%s' "$value"
}

# SQL 字符串转义。
# 这里主要用于数据库名、用户名和密码。
mysql_escape_string() {
    local value="$1"

    value="${value//\\/\\\\}"
    value="${value//\'/\'\'}"

    printf '%s' "$value"
}

# SQL 标识符转义。
mysql_escape_identifier() {
    local value="$1"

    value="${value//\`/\`\`}"

    printf '%s' "$value"
}

# ---------- 1. 前置检查 ----------

echo ">>> 检查运行环境"

PYBIN=""

for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
        ver=$(
            "$c" -c 'import sys;print(sys.version_info[:2])' 2>/dev/null \
            || echo "(0,0)"
        )

        case "$ver" in
            *"(3, 11)"*|*"(3, 12)"*|*"(3, 13)"*)
                PYBIN="$c"
                break
                ;;
        esac
    fi
done

if [[ -z "$PYBIN" ]]; then
    echo ""
    echo "!! 未找到 Python 3.11+。"
    echo "   请安装 Python 3.11 或更高版本。"
    exit 1
fi

need node
need npm
need mysql

echo "使用 Python: $PYBIN"
"$PYBIN" --version

echo "Node: $(node -v)"
echo "npm: $(npm -v)"

if ! command -v pnpm >/dev/null 2>&1; then
    echo ""
    echo ">>> 未检测到 pnpm，用 npm 安装全局 pnpm"
    npm install -g pnpm
fi

need pnpm

echo "pnpm: $(pnpm -v)"
echo ""

# ---------- 2. 数据库配置 ----------

echo "========================================"
echo " 数据库配置"
echo "========================================"
echo ""
echo "安装脚本会自动创建数据库和应用用户。"
echo "你不需要提前手动创建 luogu_archive 用户。"
echo ""

ask DB_HOST "MySQL 主机" "127.0.0.1"
ask DB_PORT "MySQL 端口" "3306"
ask DB_NAME "数据库名" "luogu_archive"
ask DB_USER "应用数据库用户名" "luogu_archive"
ask_secret DB_PASSWORD "应用数据库密码"

echo ""
echo "---- MySQL 管理员账号 ----"
echo "该账号仅用于创建数据库、创建应用用户和授权。"
echo "管理员密码不会写入 backend/.env。"
echo ""

MYSQL_ADMIN_USER="root"
MYSQL_ADMIN_PASSWORD=""
MYSQL_ADMIN_MODE=""

# 本机 MySQL 如果使用 auth_socket，优先使用 sudo mysql。
if [[ "$DB_HOST" == "127.0.0.1" || "$DB_HOST" == "localhost" ]]; then
    echo ">>> 检测本机 MySQL root socket 登录"

    if sudo -n mysql --protocol=socket -e "SELECT 1;" >/dev/null 2>&1; then
        MYSQL_ADMIN_MODE="sudo"
        echo "✔ 检测到 sudo mysql 可用，将使用 Unix socket 管理 MySQL。"
        echo ""
    else
        echo ">>> 当前 sudo 需要密码或 root socket 登录不可用。"
        echo ""
        ask MYSQL_ADMIN_USER "MySQL 管理员用户名" "root"
        ask_secret MYSQL_ADMIN_PASSWORD "MySQL 管理员密码"
    fi
else
    echo ">>> 当前为远程 MySQL，需要管理员账号密码。"
    ask MYSQL_ADMIN_USER "MySQL 管理员用户名" "root"
    ask_secret MYSQL_ADMIN_PASSWORD "MySQL 管理员密码"
fi

# ---------- 3. MySQL 管理员连接函数 ----------

mysql_admin() {
    if [[ "$MYSQL_ADMIN_MODE" == "sudo" ]]; then
        sudo mysql \
            --protocol=socket \
            "$@"
    else
        MYSQL_PWD="$MYSQL_ADMIN_PASSWORD" \
            mysql \
            -h "$DB_HOST" \
            -P "$DB_PORT" \
            -u "$MYSQL_ADMIN_USER" \
            "$@"
    fi
}

echo ""
echo ">>> 测试 MySQL 管理员连接"

if [[ "$MYSQL_ADMIN_MODE" == "sudo" ]]; then
    if ! sudo mysql --protocol=socket -e "SELECT 1;" >/dev/null 2>&1; then
        echo ""
        echo "!! sudo mysql 连接失败。"
        echo "   请确认当前用户可以通过 sudo 管理 MySQL。"
        exit 1
    fi

    echo "✔ MySQL 管理员连接成功（sudo / Unix socket）"
else
    if ! MYSQL_PWD="$MYSQL_ADMIN_PASSWORD" \
        mysql \
        -h "$DB_HOST" \
        -P "$DB_PORT" \
        -u "$MYSQL_ADMIN_USER" \
        -e "SELECT 1;" >/dev/null 2>&1; then

        echo ""
        echo "!! MySQL 管理员连接失败，请检查："
        echo "   主机：$DB_HOST"
        echo "   端口：$DB_PORT"
        echo "   管理员用户名：$MYSQL_ADMIN_USER"
        echo "   管理员密码"
        exit 1
    fi

    MYSQL_ADMIN_MODE="password"

    echo "✔ MySQL 管理员连接成功"
fi

# ---------- 4. 创建数据库和应用用户 ----------

echo ""
echo ">>> 创建数据库和应用用户"

DB_NAME_SQL="$(mysql_escape_identifier "$DB_NAME")"
DB_USER_SQL="$(mysql_escape_string "$DB_USER")"
DB_PASSWORD_SQL="$(mysql_escape_string "$DB_PASSWORD")"

if [[ "$DB_HOST" == "127.0.0.1" || "$DB_HOST" == "localhost" ]]; then
    DB_USER_HOSTS=("localhost" "127.0.0.1")
else
    DB_USER_HOSTS=("$DB_HOST" "%")
fi

mysql_admin <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME_SQL\`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
SQL

for db_user_host in "${DB_USER_HOSTS[@]}"; do
    mysql_admin <<SQL
CREATE USER IF NOT EXISTS '$DB_USER_SQL'@'$db_user_host'
    IDENTIFIED BY '$DB_PASSWORD_SQL';

ALTER USER '$DB_USER_SQL'@'$db_user_host'
    IDENTIFIED BY '$DB_PASSWORD_SQL';

GRANT ALL PRIVILEGES
    ON \`$DB_NAME_SQL\`.*
    TO '$DB_USER_SQL'@'$db_user_host';
SQL
done

mysql_admin <<SQL
FLUSH PRIVILEGES;
SQL

echo "✔ 数据库创建/确认完成：$DB_NAME"
echo "✔ 应用用户创建/更新完成：$DB_USER"

# ---------- 5. 测试应用数据库连接 ----------

echo ""
echo ">>> 测试应用数据库连接"

if ! MYSQL_PWD="$DB_PASSWORD" \
    mysql \
    -h "$DB_HOST" \
    -P "$DB_PORT" \
    -u "$DB_USER" \
    "$DB_NAME" \
    -e "SELECT 1;" >/dev/null 2>&1; then

    echo ""
    echo "!! 应用数据库连接失败。"
    echo ""
    echo "当前配置："
    echo "  主机：$DB_HOST"
    echo "  端口：$DB_PORT"
    echo "  数据库：$DB_NAME"
    echo "  用户：$DB_USER"
    echo ""
    echo "请检查应用数据库用户权限和密码。"
    exit 1
fi

echo "✔ 应用数据库连接成功"

echo ""

# ---------- 6. Redis ----------

echo "---- Redis（宝塔 Redis / 本机 Redis）----"

ask REDIS_URL "Redis 连接串" "redis://127.0.0.1:6379/0"

echo ""

# ---------- 7. 站点 ----------

echo "---- 站点 ----"

ask SITE_DOMAIN \
    "站点域名（不带 https://，例如 archive.example.com）"

ask APP_ENV \
    "运行环境 (development/staging/production)" \
    "production"

echo ""

# ---------- 8. 爬虫 ----------

echo "---- 爬虫 ----"

ask CRAWLER_BASE_URL \
    "爬取目标域名" \
    "https://luogu.com"

ask CRAWLER_CONTACT_EMAIL \
    "User-Agent 里的联系邮箱"

echo ""

# ---------- 9. SMTP ----------

echo "---- SMTP（发邮箱验证）----"

ask SMTP_HOST \
    "SMTP 主机（留空跳过，将来在 .env 手改）" \
    ""

SMTP_PORT=""
SMTP_USER=""
SMTP_PASSWORD=""
SMTP_FROM=""
SMTP_USE_TLS="true"

if [[ -n "$SMTP_HOST" ]]; then
    ask SMTP_PORT "SMTP 端口" "587"
    ask SMTP_USER "SMTP 用户名"
    ask_secret SMTP_PASSWORD "SMTP 密码"
    ask SMTP_FROM "发件人地址" "$SMTP_USER"
fi

echo ""

# ---------- 10. CAPTCHA ----------

echo "---- 人机验证（可选，留空跳过）----"

ask CAPTCHA_SITE_KEY "Turnstile Site Key" ""

CAPTCHA_SECRET=""

if [[ -n "$CAPTCHA_SITE_KEY" ]]; then
    ask_secret CAPTCHA_SECRET "Turnstile Secret"
fi

echo ""

# ---------- 11. 服务端口 ----------

echo "---- 服务监听端口（绑 127.0.0.1，由宝塔 Nginx 反代）----"

ask BACKEND_PORT "后端 FastAPI 端口" "8000"
ask FRONTEND_PORT "前端 Nuxt 端口" "3000"

echo ""

# ---------- 12. 生成密钥 ----------

echo ">>> 生成 Fernet / JWT 密钥"

FERNET_KEY=$(
    "$PYBIN" -c \
    "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
)

JWT_SECRET=$(
    "$PYBIN" -c \
    "import secrets;print(secrets.token_hex(32))"
)

# ---------- 13. 写 backend/.env ----------

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
WEB_PUBLIC_ORIGIN="https://$SITE_DOMAIN"
WEB_CORS_ORIGINS="https://$SITE_DOMAIN"

# MySQL
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_USER=$DB_USER
DB_PASSWORD="$(dotenv_escape "$DB_PASSWORD")"
DB_NAME=$DB_NAME
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Redis
REDIS_URL="$(dotenv_escape "$REDIS_URL")"

# 爬虫
CRAWLER_BASE_URL="$(dotenv_escape "$CRAWLER_BASE_URL")"
CRAWLER_FALLBACK_BASE_URL="https://www.luogu.com.cn"
CRAWLER_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36"
CRAWLER_CONTACT_EMAIL="$(dotenv_escape "$CRAWLER_CONTACT_EMAIL")"
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
ADMIN_TOTP_ENCRYPTION_KEY="$(dotenv_escape "$FERNET_KEY")"

# JWT
JWT_SECRET="$(dotenv_escape "$JWT_SECRET")"
JWT_ACCESS_TTL_SEC=900
JWT_REFRESH_TTL_SEC=604800

# 邮件
SMTP_HOST="$(dotenv_escape "$SMTP_HOST")"
SMTP_PORT=${SMTP_PORT:-587}
SMTP_USER="$(dotenv_escape "$SMTP_USER")"
SMTP_PASSWORD="$(dotenv_escape "$SMTP_PASSWORD")"
SMTP_FROM="$(dotenv_escape "${SMTP_FROM:-noreply@example.com}")"
SMTP_USE_TLS=$SMTP_USE_TLS

# 人机验证
CAPTCHA_PROVIDER=$([ -n "$CAPTCHA_SITE_KEY" ] && echo turnstile || echo none)
CAPTCHA_SITE_KEY="$(dotenv_escape "$CAPTCHA_SITE_KEY")"
CAPTCHA_SECRET="$(dotenv_escape "$CAPTCHA_SECRET")"
CAPTCHA_TRIGGER_SAVE_PER_MIN=3
CAPTCHA_TRIGGER_SAVE_PER_10MIN=10
CAPTCHA_TRIGGER_PAGE_PER_HOUR=600

# 保存按钮
SAVE_IP_WINDOW_SEC=60
SAVE_IP_WINDOW_MAX=5
SAVE_IP_HOUR_BREAKER_THRESHOLD=10
SAVE_IP_HOUR_BREAKER_COOLDOWN_SEC=3600

# 图片镜像
IMAGE_MIRROR_DIR="$ROOT_DIR/data/image_mirror"
IMAGE_MIRROR_PUBLIC_PREFIX="/static/img"
IMAGE_MIRROR_MAX_SIZE_MB=20

DATA_DIR="$ROOT_DIR/data"
EOF

mkdir -p "$ROOT_DIR/data/image_mirror"

chmod 600 "$BACKEND_ENV"

echo "✔ backend/.env 已生成"

# ---------- 14. 写 frontend/.env ----------

echo ">>> 写入 $FRONTEND_ENV"

cat > "$FRONTEND_ENV" <<EOF
NUXT_API_INTERNAL_URL="http://127.0.0.1:$BACKEND_PORT"
NUXT_PUBLIC_API_BASE_URL="https://$SITE_DOMAIN"
NUXT_PUBLIC_CAPTCHA_PROVIDER=$([ -n "$CAPTCHA_SITE_KEY" ] && echo turnstile || echo none)
NUXT_PUBLIC_CAPTCHA_SITE_KEY="$(dotenv_escape "$CAPTCHA_SITE_KEY")"
PORT="$FRONTEND_PORT"
HOST="127.0.0.1"
EOF

echo "✔ frontend/.env 已生成"

# ---------- 15. Python venv + 依赖 ----------

echo ""
echo ">>> 创建 Python 虚拟环境（backend/.venv）"

cd "$BACKEND"

if [[ ! -d .venv ]]; then
    if ! "$PYBIN" -m venv .venv 2>&1; then
        echo ""
        echo "!! 创建 venv 失败。"
        echo ""
        echo "Ubuntu 24.04 可以尝试："
        echo "  sudo apt install -y python3.12-venv python3.12-dev build-essential"
        echo ""
        echo "然后："
        echo "  rm -rf backend/.venv"
        echo "  bash install.sh"
        exit 1
    fi
fi

if [[ ! -f .venv/bin/activate ]]; then
    echo ""
    echo "!! .venv/bin/activate 不存在，venv 创建不完整。"
    echo ""
    echo "请尝试："
    echo "  sudo apt install -y python3.12-venv python3.12-dev build-essential"
    echo "  rm -rf backend/.venv"
    echo "  bash install.sh"
    exit 1
fi

. .venv/bin/activate

echo ">>> 更新 Python 构建工具"

pip install -U pip wheel setuptools >/dev/null

echo ">>> 安装后端依赖"

pip install -e . >/dev/null 2>&1 || pip install -e .

deactivate

# ---------- 16. Alembic 配置检查 ----------

echo ""
echo ">>> 检查 Alembic 配置"

if grep -q 'settings\.sync_database_url' "$BACKEND/alembic/env.py" 2>/dev/null; then
    echo "✔ 检测到 Alembic 使用同步数据库 URL"
else
    echo "!! 警告：alembic/env.py 未检测到 settings.sync_database_url"
    echo "   请确认项目 Alembic 配置正确。"
fi

# ---------- 17. 数据库迁移 ----------

echo ""
echo ">>> 初始化数据库迁移状态"
echo ""
echo "当前策略："
echo "  1. alembic upgrade $BASE_MIGRATION"
echo "  2. alembic stamp head"
echo ""
echo "不会执行 alembic upgrade head。"
echo ""

cd "$BACKEND"

. .venv/bin/activate

echo ">>> 执行基线迁移：$BASE_MIGRATION"

if ! alembic upgrade "$BASE_MIGRATION"; then
    echo ""
    echo "!! 基线数据库迁移失败。"
    echo ""
    echo "请确认："
    echo "  1. MySQL 已启动"
    echo "  2. 数据库 '$DB_NAME' 已创建"
    echo "  3. 用户 '$DB_USER' 有完整权限"
    echo "  4. backend/.env 中 DB_* 配置正确"
    echo "  5. backend/alembic/env.py 使用 settings.sync_database_url"
    echo ""
    deactivate
    exit 1
fi

echo ""
echo "✔ 基线迁移完成"

echo ""
echo ">>> 将 Alembic 直接标记到 head"

if ! alembic stamp head; then
    echo ""
    echo "!! alembic stamp head 失败。"
    deactivate
    exit 1
fi

echo ""
echo ">>> 当前 Alembic 版本："

alembic current

deactivate

# ---------- 18. 前端依赖 + 构建 ----------

echo ""
echo ">>> 安装前端依赖（pnpm install）"

cd "$FRONTEND"

if [[ -f pnpm-lock.yaml ]]; then
    pnpm install --frozen-lockfile 2>/dev/null || pnpm install
else
    pnpm install
fi

echo ""
echo ">>> 构建前端（pnpm build）"

pnpm build

# ---------- 19. 引导创建管理员 ----------

cd "$BACKEND"

. .venv/bin/activate

echo ""
echo ">>> 检查管理员数量"

ADMIN_CNT=$(
    python -c "
import asyncio
from sqlalchemy import func, select
from app.core.db import db_session
from app.models.admin import Admin

async def main():
    async with db_session() as s:
        print(
            int(
                (
                    await s.execute(
                        select(func.count()).select_from(Admin)
                    )
                ).scalar_one()
            )
        )

asyncio.run(main())
"
)

if [[ "$ADMIN_CNT" -eq 0 ]]; then
    echo ""
    echo ">>> 还没有管理员，交互式创建："

    python -m scripts.create_admin

    echo ""
    echo "** TOTP secret 只显示一次，请立即添加到 Authenticator 应用 **"
else
    echo ""
    echo ">>> 已存在管理员，跳过管理员创建。"
fi

deactivate

# ---------- 20. 完成 ----------

cd "$ROOT_DIR"

echo ""
echo "======================================"
echo " ✔ 安装完成"
echo "======================================"
echo ""
echo "数据库："
echo "  数据库：$DB_NAME"
echo "  用户：$DB_USER"
echo "  实际迁移到：$BASE_MIGRATION"
echo "  Alembic 状态：head"
echo ""
echo "下一步："
echo "  bash start.sh"
echo ""
echo "停止服务："
echo "  bash stop.sh"
echo ""
echo "宝塔 Nginx 反代配置参考："
echo "  docs/BAOTA.md"
echo ""
echo "======================================"