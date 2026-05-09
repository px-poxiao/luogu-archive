#!/usr/bin/env bash
# ======================================================================
# luogu-archive · systemd + nginx + TLS 配置
# ======================================================================
# 运行方式（root/sudo）：
#   sudo bash /srv/luogu-archive/scripts/03-systemd-nginx.sh archive.example.com
# ======================================================================

set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
    echo "用法：$0 <你的域名>" >&2
    exit 1
fi

[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行本脚本" >&2; exit 1; }

SYS_HOME="/srv/luogu-archive"
SYSTEMD_SRC="$SYS_HOME/docs/systemd"

# ---------- 1. 复制 systemd units ----------
echo ">>> 安装 systemd unit"
for f in luogu-archive-web.service luogu-archive-worker@.service \
         luogu-archive-scheduler.service luogu-archive-frontend.service; do
    cp -v "$SYSTEMD_SRC/$f" /etc/systemd/system/
done
systemctl daemon-reload

# ---------- 2. 启动服务 ----------
echo ">>> 启动 Web / Frontend / Scheduler / 4 个 Worker"
systemctl enable --now luogu-archive-web
systemctl enable --now luogu-archive-frontend
systemctl enable --now luogu-archive-scheduler
systemctl enable --now luogu-archive-worker@hi
systemctl enable --now luogu-archive-worker@mid
systemctl enable --now luogu-archive-worker@low
systemctl enable --now luogu-archive-worker@feed

sleep 3
systemctl --no-pager --lines=0 status luogu-archive-web luogu-archive-frontend \
    luogu-archive-scheduler 'luogu-archive-worker@*' || true

# ---------- 3. nginx ----------
echo ">>> 配置 nginx"
NGINX_CONF="/etc/nginx/sites-available/luogu-archive"
cp "$SYS_HOME/docs/nginx.conf.example" "$NGINX_CONF"
sed -i "s/archive.example.com/${DOMAIN}/g" "$NGINX_CONF"

# 第一次还没 HTTPS 证书，先临时改成 listen 80 一段
# 我们用 certbot 的 --nginx 会自动补 443 段；但它要求 server_name 匹配且原配置有 listen 80。
# 简化：先删掉 443 段跑一次 certbot，然后再把完整配置还原。
TMP_CONF=$(mktemp)
cat > "$TMP_CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    root /var/www/html;
    location / { return 200 "bootstrap"; }
}
EOF
cp "$TMP_CONF" "$NGINX_CONF"
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/luogu-archive
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ---------- 4. Certbot 申请证书 ----------
echo ">>> 申请 Let's Encrypt 证书（需要 DNS 已指向本机 IP）"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email || {
    echo "!! certbot 失败（DNS 没生效？请手动跑 'certbot --nginx -d $DOMAIN'）"
}

# ---------- 5. 写入真正的 nginx 配置 ----------
echo ">>> 替换为完整 nginx 配置"
cp "$SYS_HOME/docs/nginx.conf.example" "$NGINX_CONF"
sed -i "s/archive.example.com/${DOMAIN}/g" "$NGINX_CONF"
nginx -t
systemctl reload nginx

# ---------- 6. 定时备份 ----------
echo ">>> 安装 MySQL 备份 cron"
chmod +x "$SYS_HOME/scripts/backup-mysql.sh"
CRON_LINE="0 3 * * * HOME=$SYS_HOME bash $SYS_HOME/scripts/backup-mysql.sh >> /var/log/luogu-archive-backup.log 2>&1"
( crontab -u luogu -l 2>/dev/null | grep -v backup-mysql.sh; echo "$CRON_LINE" ) | crontab -u luogu -

# ---------- 7. 健康检查 ----------
echo ""
echo ">>> 最终自检"
sleep 2
curl -sS -o /dev/null -w "  /healthz: HTTP %{http_code}\n" "https://${DOMAIN}/healthz" || true
curl -sS -o /dev/null -w "  /:        HTTP %{http_code}\n" "https://${DOMAIN}/" || true

echo ""
echo "========== 部署完成 =========="
echo ""
echo " 前台：  https://${DOMAIN}"
echo " 后台：  https://${DOMAIN}/admin/login"
echo ""
echo " 下一步必做："
echo "   1. 登录管理后台 → 爬取账号 → 录入一个洛谷 Cookie（仅犇犇用）"
echo "   2. 删除 $SYS_HOME/INIT_SECRETS.txt（已写入 .env，源文件保留有风险）"
echo ""
echo " 日志查看："
echo "   journalctl -u luogu-archive-web -f"
echo "   journalctl -u luogu-archive-worker@hi -f"
echo "   journalctl -u luogu-archive-scheduler -f"
echo "=============================="
