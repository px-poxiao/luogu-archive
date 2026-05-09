#!/usr/bin/env bash
# ======================================================================
# luogu-archive · 前端部署脚本
# ======================================================================
# 运行方式：sudo -u luogu bash /srv/luogu-archive/scripts/02-deploy-frontend.sh
# ======================================================================

set -euo pipefail

SYS_HOME="/srv/luogu-archive"
FRONT_DIR="$SYS_HOME/frontend"

cd "$FRONT_DIR"

# ---------- 1. 确保 .env ----------
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "!! 已创建 frontend/.env，请编辑："
        echo "   - NUXT_PUBLIC_API_BASE_URL=https://<你的域名>"
        echo "   - NUXT_PUBLIC_CAPTCHA_SITE_KEY=<Turnstile 站点 key>"
        echo "编辑完再跑本脚本。"
        exit 1
    else
        echo "!! frontend/.env.example 不存在" >&2
        exit 1
    fi
fi

# ---------- 2. 装依赖 + 构建 ----------
echo ">>> pnpm install"
pnpm install --frozen-lockfile || pnpm install

echo ">>> pnpm build"
pnpm build

echo ""
echo "========== 前端构建完成 =========="
echo " 产物在 $FRONT_DIR/.output/"
echo " 下一步："
echo "   sudo bash $SYS_HOME/scripts/03-systemd-nginx.sh <你的域名>"
echo "==================================="
