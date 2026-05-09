#!/usr/bin/env bash
# ======================================================================
# luogu-archive · Ubuntu 22.04 / 24.04 全新机器一键安装脚本
# ======================================================================
# 功能：
#   - 装系统依赖（MySQL 8 / Redis / nginx / certbot / Python 3.12 / Node 20 / pnpm）
#   - 创建业务用户 luogu
#   - 建数据库 + 数据库用户
#   - 写入备份所需的 ~/.my.cnf
#
# 运行方式（root 或 sudo）：
#   chmod +x 00-bootstrap.sh
#   sudo ./00-bootstrap.sh
#
# 运行后执行脚本里打印的"下一步"。本脚本不部署代码，代码在 01/02/03 脚本。
# ======================================================================

set -euo pipefail

# ---------- 参数 ----------
DB_NAME="${DB_NAME:-luogu_archive}"
DB_USER="${DB_USER:-luogu_archive}"
# 若 DB_PASSWORD 未设，脚本会生成一个强密码
DB_PASSWORD="${DB_PASSWORD:-}"

SYS_USER="${SYS_USER:-luogu}"
SYS_HOME="/srv/luogu-archive"

NODE_MAJOR="${NODE_MAJOR:-20}"

echo "========================================"
echo " luogu-archive 一键初始化"
echo "========================================"
[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行本脚本" >&2; exit 1; }

. /etc/os-release
echo "检测到系统：$PRETTY_NAME"

# ---------- 1. 系统更新 + 基础工具 ----------
echo ">>> 更新系统 + 装基础工具"
apt-get update -y
apt-get install -y --no-install-recommends \
    build-essential curl git ca-certificates pkg-config \
    software-properties-common gnupg lsb-release \
    ufw unzip jq

# ---------- 2. Python 3.12 ----------
echo ">>> 安装 Python 3.12"
if ! command -v python3.12 >/dev/null; then
    # Ubuntu 22.04 默认没有 3.12，需要 deadsnakes PPA
    if [[ "$VERSION_ID" == "22.04" ]]; then
        add-apt-repository -y ppa:deadsnakes/ppa
        apt-get update -y
    fi
    apt-get install -y python3.12 python3.12-venv python3.12-dev
fi
python3.12 --version

# ---------- 3. Node 20 + pnpm ----------
echo ">>> 安装 Node $NODE_MAJOR + pnpm"
if ! command -v node >/dev/null || [[ "$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)" -lt "$NODE_MAJOR" ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
fi
npm install -g pnpm
node --version
pnpm --version

# ---------- 4. MySQL 8 + Redis ----------
echo ">>> 安装 MySQL + Redis"
DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server redis-server

systemctl enable --now mysql
systemctl enable --now redis-server

# ---------- 5. nginx + certbot ----------
echo ">>> 安装 nginx + certbot"
apt-get install -y nginx certbot python3-certbot-nginx
systemctl enable --now nginx

# ---------- 6. 业务系统用户 ----------
echo ">>> 创建系统用户 $SYS_USER"
if ! id "$SYS_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$SYS_HOME" --shell /bin/bash "$SYS_USER"
fi
mkdir -p "$SYS_HOME" /var/www/luogu-archive/image_mirror
chown -R "$SYS_USER:$SYS_USER" "$SYS_HOME"
chown -R "$SYS_USER:www-data" /var/www/luogu-archive
chmod 775 /var/www/luogu-archive/image_mirror

# ---------- 7. 建数据库 ----------
echo ">>> 创建 MySQL 数据库 + 用户"
if [[ -z "$DB_PASSWORD" ]]; then
    DB_PASSWORD=$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-24)
    echo "已自动生成 DB_PASSWORD"
fi

mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\`
  DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL

# ---------- 8. 备份用 my.cnf（免密 mysqldump）----------
echo ">>> 写入 $SYS_HOME/.my.cnf（备份脚本用）"
cat > "$SYS_HOME/.my.cnf" <<EOF
[client]
user=$DB_USER
password=$DB_PASSWORD
host=127.0.0.1

[mysqldump]
user=$DB_USER
password=$DB_PASSWORD
host=127.0.0.1
EOF
chown "$SYS_USER:$SYS_USER" "$SYS_HOME/.my.cnf"
chmod 600 "$SYS_HOME/.my.cnf"

# ---------- 9. 生成两个密钥（Fernet + JWT）----------
echo ">>> 生成 ADMIN_TOTP_ENCRYPTION_KEY + JWT_SECRET"
FERNET_KEY=$(python3.12 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())" 2>/dev/null || \
             python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
JWT_SECRET=$(python3.12 -c "import secrets;print(secrets.token_hex(32))" 2>/dev/null || \
             python3 -c "import secrets;print(secrets.token_hex(32))")

# ---------- 10. 防火墙（只开 80/443/SSH）----------
echo ">>> 配置 ufw"
ufw allow OpenSSH || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
echo 'y' | ufw enable || true
ufw status

# ---------- 11. 输出关键信息（**务必截图保存**）----------
KEYS_FILE="$SYS_HOME/INIT_SECRETS.txt"
cat > "$KEYS_FILE" <<EOF
==============================================
luogu-archive 初始化密钥 —— 务必保管此文件
生成时间：$(date -Iseconds)
==============================================

DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD

ADMIN_TOTP_ENCRYPTION_KEY=$FERNET_KEY
JWT_SECRET=$JWT_SECRET

把上面内容粘贴到 backend/.env 对应字段。
此文件权限 600，仅 root 可读。用完后可删。
EOF
chmod 600 "$KEYS_FILE"

echo ""
echo "================================================================="
echo " ✔ 初始化完成"
echo "================================================================="
echo ""
echo " 1. 密钥已写入  $KEYS_FILE  （600 权限，用完删除）"
echo "    cat $KEYS_FILE"
echo ""
echo " 2. 下一步："
echo "    - 把代码上传到  $SYS_HOME/  （上传方式见 docs/DEPLOY.md 说明）"
echo "    - sudo -u $SYS_USER bash $SYS_HOME/scripts/01-deploy-backend.sh"
echo ""
echo "================================================================="
