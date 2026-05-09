#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 后端部署脚本
# ======================================================================
# 前置：已跑过 00-bootstrap.sh，代码已上传到 /srv/luogu-archive/
# 运行方式：sudo -u luogu bash /srv/luogu-archive/scripts/01-deploy-backend.sh
# ======================================================================

set -euo pipefail

SYS_HOME="/srv/luogu-archive"
BACKEND_DIR="$SYS_HOME/backend"

cd "$BACKEND_DIR"

# ---------- 1. venv + 依赖 ----------
echo ">>> 创建 venv"
if [ ! -d .venv ]; then
    python3.12 -m venv .venv
fi
source .venv/bin/activate
pip install -U pip wheel setuptools
pip install -e .

# ---------- 2. 确保 .env 存在 ----------
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo ""
        echo "!! 已创建 .env。请立即编辑填入："
        echo "   - DB_PASSWORD (见 $SYS_HOME/INIT_SECRETS.txt)"
        echo "   - ADMIN_TOTP_ENCRYPTION_KEY"
        echo "   - JWT_SECRET"
        echo "   - CRAWLER_CONTACT_EMAIL"
        echo "   - CRAWLER_BASE_URL=https://luogu.com  (国外部署)"
        echo "   - WEB_PUBLIC_ORIGIN=https://<你的域名>"
        echo "   - WEB_CORS_ORIGINS=https://<你的域名>"
        echo "   - APP_ENV=production / APP_DEBUG=false"
        echo "   - SMTP_* (邮箱发送)"
        echo ""
        echo "编辑完成后重新运行本脚本。"
        exit 1
    else
        echo "!! .env.example 不存在，代码可能上传不完整" >&2
        exit 1
    fi
fi

# 简单校验 .env 没留占位符
for key in ADMIN_TOTP_ENCRYPTION_KEY JWT_SECRET DB_PASSWORD; do
    val=$(grep "^${key}=" .env | head -1 | cut -d= -f2-)
    if [[ -z "$val" || "$val" == *"change_me"* || "$val" == *"CHANGE_ME"* ]]; then
        echo "!! .env 里 $key 未设置 / 还是占位符" >&2
        exit 1
    fi
done

# ---------- 3. 数据库迁移 ----------
echo ">>> Alembic 迁移"
alembic upgrade head

# ---------- 4. 创建第一个管理员（若库里还没有）----------
ADMIN_COUNT=$(python -c "
import asyncio
from sqlalchemy import func, select
from app.core.db import db_session
from app.models.admin import Admin
async def main():
    async with db_session() as s:
        print(int((await s.execute(select(func.count()).select_from(Admin))).scalar_one()))
asyncio.run(main())
")
if [[ "$ADMIN_COUNT" -eq 0 ]]; then
    echo ""
    echo ">>> 当前没有管理员，下面请交互式创建第一个："
    python -m scripts.create_admin
    echo ""
    echo "!! TOTP secret 只会显示一次，请立即加入 Authy/Google Authenticator"
fi

# ---------- 5. 完成 ----------
deactivate
echo ""
echo "========== 后端部署完成 =========="
echo " 下一步："
echo "   sudo -u luogu bash $SYS_HOME/scripts/02-deploy-frontend.sh"
echo "   sudo bash $SYS_HOME/scripts/03-systemd-nginx.sh <你的域名>"
echo "==================================="
