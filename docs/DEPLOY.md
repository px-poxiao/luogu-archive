# 部署文档（Linux 裸机）

假设目标：Ubuntu 22.04 / Debian 12 服务器，**部署在中国大陆境外**（如 AWS Singapore / DigitalOcean / Vultr Tokyo）。

## 0. 前置

- 服务器规格建议：2 vCPU / 4 GB RAM / 50 GB 硬盘（含备份）
- 域名一个（如 `archive.example.com`），DNS A 记录指向服务器
- 邮件发送：推荐 SES / Resend / Postmark 做 SMTP relay
- 本地准备好 Fernet key + JWT secret（每个环境独一份）

## 1. 系统初始化

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential curl git ca-certificates pkg-config \
    mysql-server redis-server nginx certbot python3-certbot-nginx \
    python3.11 python3.11-venv python3.11-dev

# 添加业务用户
sudo adduser --system --group --home /srv/luogu-archive --shell /bin/bash luogu
```

## 2. MySQL 配置

```bash
sudo mysql_secure_installation

sudo mysql <<SQL
CREATE DATABASE luogu_archive DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'luogu_archive'@'localhost' IDENTIFIED BY '<强密码>';
GRANT ALL ON luogu_archive.* TO 'luogu_archive'@'localhost';
FLUSH PRIVILEGES;
SQL
```

## 3. Redis 配置

默认即可。如果对外暴露需改 `/etc/redis/redis.conf` 的 `bind` 和 `requirepass`。

## 4. 拉取代码 + Python 环境

```bash
sudo mkdir -p /srv/luogu-archive
sudo chown luogu:luogu /srv/luogu-archive
sudo -u luogu -i

cd /srv/luogu-archive
# 从你的私有仓库拉代码（这里是占位）
git clone <your-repo-url> .

cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 5. 后端 .env

```bash
cp .env.example .env
# 必须修改的字段：
#   APP_ENV=production
#   APP_DEBUG=false
#   DB_PASSWORD=<步骤 2 里的强密码>
#   ADMIN_TOTP_ENCRYPTION_KEY=<Fernet key>
#   JWT_SECRET=<64 位随机 hex>
#   CRAWLER_CONTACT_EMAIL=you@example.com         ← 必填真实邮箱
#   CRAWLER_BASE_URL=https://luogu.com             ← 国外环境切成 .com
#   WEB_PUBLIC_ORIGIN=https://archive.example.com
#   WEB_CORS_ORIGINS=https://archive.example.com
#   SMTP_* ...
#   CAPTCHA_SITE_KEY=<Turnstile>
#   CAPTCHA_SECRET=<Turnstile>
```

生成两个密钥：
```bash
# Fernet
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
# JWT
python -c "import secrets;print(secrets.token_hex(32))"
```

## 6. 数据库迁移 + 创建首个管理员

```bash
cd /srv/luogu-archive/backend
source .venv/bin/activate
alembic upgrade head
python -m scripts.create_admin  # 交互式；最后会显示 TOTP secret，必须立即加到 Authenticator
```

## 7. 前端构建

```bash
# 装 Node 20+（推荐 nvm）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
. ~/.bashrc
nvm install 20

cd /srv/luogu-archive/frontend
npm install -g pnpm
pnpm install
cp .env.example .env
# 修改：
#   NUXT_API_INTERNAL_URL=http://127.0.0.1:8000
#   NUXT_PUBLIC_API_BASE_URL=https://archive.example.com
#   NUXT_PUBLIC_CAPTCHA_PROVIDER=turnstile
#   NUXT_PUBLIC_CAPTCHA_SITE_KEY=...
pnpm build
```

## 8. systemd units

```bash
# 回到 root
exit

sudo cp /srv/luogu-archive/docs/systemd/luogu-archive-web.service /etc/systemd/system/
sudo cp /srv/luogu-archive/docs/systemd/luogu-archive-worker@.service /etc/systemd/system/
sudo cp /srv/luogu-archive/docs/systemd/luogu-archive-scheduler.service /etc/systemd/system/
sudo cp /srv/luogu-archive/docs/systemd/luogu-archive-frontend.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now luogu-archive-web
sudo systemctl enable --now luogu-archive-frontend
sudo systemctl enable --now luogu-archive-scheduler

# 4 个 worker 实例（对应 4 个队列）
sudo systemctl enable --now luogu-archive-worker@hi
sudo systemctl enable --now luogu-archive-worker@mid
sudo systemctl enable --now luogu-archive-worker@low
sudo systemctl enable --now luogu-archive-worker@feed
```

## 9. Nginx + HTTPS

```bash
# 复制并修改域名
sudo cp /srv/luogu-archive/docs/nginx.conf.example /etc/nginx/sites-available/luogu-archive
sudo sed -i 's/archive.example.com/<YOUR_DOMAIN>/g' /etc/nginx/sites-available/luogu-archive
sudo ln -s /etc/nginx/sites-available/luogu-archive /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# 申请证书
sudo certbot --nginx -d <YOUR_DOMAIN>

# 创建镜像图片目录
sudo mkdir -p /var/www/luogu-archive/image_mirror
sudo chown -R luogu:www-data /var/www/luogu-archive
sudo chmod 775 /var/www/luogu-archive/image_mirror
```

## 10. 备份

```bash
# 创建 ~luogu/.my.cnf 避免密码暴露
sudo -u luogu tee /srv/luogu-archive/.my.cnf <<EOF
[client]
user=luogu_archive
password=<强密码>
host=127.0.0.1
EOF
sudo -u luogu chmod 600 /srv/luogu-archive/.my.cnf

# 配置 cron
sudo crontab -u luogu -e
# 添加：
# 0 3 * * * HOME=/srv/luogu-archive bash /srv/luogu-archive/scripts/backup-mysql.sh >> /var/log/luogu-archive-backup.log 2>&1
```

## 11. 首次配置 Cookie 账号

访问 `https://<YOUR_DOMAIN>/admin/login`（用第 6 步的管理员账号）→ 侧栏「爬取账号」→「录入新账号」

填入：
- `label`: 自定义备注（如"主力 1"）
- `luogu_uid`: 你登录用的洛谷 UID
- `_uid`: Cookie 值
- `__client_id`: Cookie 值
- `C3VK`（可选）

保存后，犇犇爬虫就会开始使用这个账号。注意**保号原则**：不要在控制台里狂点测试。

## 12. 验证

- `curl https://<YOUR_DOMAIN>/healthz` → `{"status":"ok"}`
- 访问首页测试"快速跳转"：输入一个已知用户 UID 跳转 → 若未收录会触发异步爬取 → 稍等刷新
- 在管理后台「仪表盘」看队列长度和近 24h 统计

## 故障排查

- `systemctl status luogu-archive-web` 看服务状态
- `journalctl -u luogu-archive-web -n 200` 看日志
- `sudo -u luogu redis-cli llen dramatiq:crawler.hi.msgs` 看队列堆积
- MySQL 慢查询：`SHOW PROCESSLIST`
- Cookie 失效：管理后台「爬取账号」列表看 `last_status`
