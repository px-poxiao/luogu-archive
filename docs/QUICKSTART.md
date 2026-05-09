# 一键部署指南（Ubuntu 22.04/24.04 · 全新机器 · 有域名）

本文假设你：
- 有一台全新 Ubuntu 22.04/24.04 服务器（2 vCPU / 4 GB RAM / 50 GB 起）
- 服务器在**中国大陆境外**（如 AWS Singapore / Tokyo、Vultr Tokyo、DigitalOcean Singapore）
- 有域名 `archive.example.com`，DNS A 记录已指向服务器公网 IP
- Windows 电脑 + PowerShell
- 本地代码在 `D:\code\luogu-archive\`

下文每一步都可以复制粘贴。

---

## 一、把代码传到服务器

### 方法 A（推荐）：用 SCP

**Windows 10/11 自带 `scp`、`ssh`，直接用 PowerShell**：

```powershell
# 先把代码打成压缩包（避免 .venv / node_modules 被一起传上去）
cd D:\code
# 用 tar 打包（Windows 自带），排除大目录
tar --exclude='luogu-archive/backend/.venv' `
    --exclude='luogu-archive/frontend/node_modules' `
    --exclude='luogu-archive/frontend/.nuxt' `
    --exclude='luogu-archive/frontend/.output' `
    --exclude='luogu-archive/backend/__pycache__' `
    --exclude='luogu-archive/**/.env' `
    -czf luogu-archive.tar.gz luogu-archive/

# 传到服务器（替换 your-server-ip）
scp luogu-archive.tar.gz root@your-server-ip:/tmp/
```

在服务器上解压：
```bash
ssh root@your-server-ip
mkdir -p /srv/luogu-archive
tar -xzf /tmp/luogu-archive.tar.gz -C /tmp/
mv /tmp/luogu-archive/* /srv/luogu-archive/
mv /tmp/luogu-archive/.gitignore /srv/luogu-archive/ 2>/dev/null || true
rm -rf /tmp/luogu-archive /tmp/luogu-archive.tar.gz
ls /srv/luogu-archive/
```

### 方法 B：用 Git（如果你有私有仓库）

```bash
# 在服务器上
cd /srv
git clone https://github.com/<your>/luogu-archive.git
```

### 方法 C：用 VSCode Remote-SSH

1. 装 VSCode 扩展 Remote-SSH
2. 连接到服务器
3. 打开远端的 `/srv/luogu-archive`
4. 在 VSCode 里拖拽本地文件夹上传（最笨但可视化）

---

## 二、在服务器上跑一键脚本

所有脚本都在 `scripts/` 目录里。

### 阶段 1：系统环境 + 数据库（大约 5~10 分钟）

```bash
ssh root@your-server-ip
cd /srv/luogu-archive
chmod +x scripts/*.sh

# 跑初始化，安装所有系统依赖 + 建库 + 生成密钥
sudo ./scripts/00-bootstrap.sh
```

**脚本会做**：
- `apt install` 安装 Python 3.12、Node 20、pnpm、MySQL 8、Redis、nginx、certbot
- 创建 Linux 用户 `luogu`
- 建 MySQL 库 `luogu_archive` + 用户 + 自动生成强密码
- 生成 Fernet 加密 key + JWT 密钥
- 配置 UFW 防火墙（仅开 22/80/443）
- 把所有密钥写到 `/srv/luogu-archive/INIT_SECRETS.txt`（权限 600）

脚本跑完后**一定要先看一眼密钥文件**：
```bash
sudo cat /srv/luogu-archive/INIT_SECRETS.txt
```

### 阶段 2：配置 .env

后端：
```bash
# 复制 example
sudo -u luogu cp /srv/luogu-archive/backend/.env.example /srv/luogu-archive/backend/.env
sudo -u luogu nano /srv/luogu-archive/backend/.env
```

**必改字段**（从 `INIT_SECRETS.txt` 复制）：
```ini
APP_ENV=production
APP_DEBUG=false

DB_PASSWORD=<INIT_SECRETS.txt 里的 DB_PASSWORD>
ADMIN_TOTP_ENCRYPTION_KEY=<INIT_SECRETS.txt 里的>
JWT_SECRET=<INIT_SECRETS.txt 里的>

# 国外部署，切成 .com 海外镜像
CRAWLER_BASE_URL=https://luogu.com
CRAWLER_CONTACT_EMAIL=you@example.com   # 必填你的联系邮箱

WEB_PUBLIC_ORIGIN=https://archive.example.com
WEB_CORS_ORIGINS=https://archive.example.com

# SMTP（发邮箱验证用，填你的 SMTP 服务商）
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=<smtp 密码>
SMTP_FROM=noreply@example.com

# 可选：Cloudflare Turnstile（人机验证）
CAPTCHA_PROVIDER=turnstile
CAPTCHA_SITE_KEY=<到 dash.cloudflare.com 申请>
CAPTCHA_SECRET=<同上>
```

前端：
```bash
sudo -u luogu cp /srv/luogu-archive/frontend/.env.example /srv/luogu-archive/frontend/.env
sudo -u luogu nano /srv/luogu-archive/frontend/.env
```

```ini
NUXT_API_INTERNAL_URL=http://127.0.0.1:8000
NUXT_PUBLIC_API_BASE_URL=https://archive.example.com
NUXT_PUBLIC_CAPTCHA_PROVIDER=turnstile
NUXT_PUBLIC_CAPTCHA_SITE_KEY=<同后端 CAPTCHA_SITE_KEY>
```

### 阶段 3：部署后端（含数据库迁移 + 创建管理员）

```bash
sudo -u luogu bash /srv/luogu-archive/scripts/01-deploy-backend.sh
```

**脚本会做**：
- 创建 `backend/.venv` + `pip install -e .`
- 校验 `.env` 没留占位符
- `alembic upgrade head` 建表
- 若库里无管理员，交互式创建第一个

**创建管理员时会让你输入**：
- 用户名
- 密码（≥ 10 位）
- 会打印一个 TOTP secret 和 otpauth:// URL —— **必须立刻**用 Google Authenticator / Authy 加上，这行只显示一次

### 阶段 4：构建前端

```bash
sudo -u luogu bash /srv/luogu-archive/scripts/02-deploy-frontend.sh
```

大约 2~5 分钟（看服务器性能）。

### 阶段 5：systemd + nginx + HTTPS

**先确认**：`archive.example.com` 的 DNS A 记录已指向服务器公网 IP（用 `dig archive.example.com` 能看到结果）。

```bash
sudo bash /srv/luogu-archive/scripts/03-systemd-nginx.sh archive.example.com
```

**脚本会做**：
- 安装 4 个 systemd unit 文件（web / frontend / scheduler / worker）并启用
- 启动 4 个 worker 实例（hi / mid / low / feed 四个队列）
- 先起一个临时 HTTP nginx
- `certbot --nginx` 自动申请 Let's Encrypt 证书并改 nginx
- 替换为完整 nginx 配置
- 给 luogu 用户装 cron：每天 03:00 mysqldump

---

## 三、验证上线

```bash
# 关键服务状态（应该都是 active (running)）
systemctl status luogu-archive-web \
                 luogu-archive-frontend \
                 luogu-archive-scheduler \
                 'luogu-archive-worker@*'

# 健康检查
curl https://archive.example.com/healthz    # → {"status":"ok"}
curl https://archive.example.com/           # → Nuxt 首页 HTML
```

浏览器访问：
- 前台：https://archive.example.com
- 管理后台：https://archive.example.com/admin/login

---

## 四、首次配置 Cookie 账号（爬犇犇必须）

1. 用刚才创建的管理员账号登录 `/admin/login`（账号 + 密码 + TOTP 6 位）
2. 导航到「爬取账号」
3. 点「录入新账号」，填入：
   - **备注**：`主力-1`（自定义）
   - **Luogu UID**：你登录用的洛谷账号的 UID
   - **_uid**：浏览器里复制的 Cookie 值
   - **__client_id**：浏览器里复制的 Cookie 值
   - **C3VK**：可选

取 Cookie 方法：浏览器登录洛谷 → F12 → Application → Cookies → 复制 `_uid` 和 `__client_id` 的值。

保存后，下次犇犇爬虫任务被调度时就会使用此账号。

---

## 五、常用运维命令

```bash
# 看日志
sudo journalctl -u luogu-archive-web -f
sudo journalctl -u luogu-archive-worker@hi -f
sudo journalctl -u luogu-archive-scheduler -f

# 重启某个服务
sudo systemctl restart luogu-archive-web

# 查看队列堆积
redis-cli llen dramatiq:crawler.hi.msgs
redis-cli llen dramatiq:crawler.feed.msgs

# 手动触发一次陶片爬取（从前台点「保存」按钮也行）
sudo -u luogu bash -c "
  cd /srv/luogu-archive/backend
  source .venv/bin/activate
  python -c 'from app.tasks.actors.crawl import crawl_judgement; crawl_judgement.send(\"manual\")'
"

# 手动跑一次备份
sudo -u luogu HOME=/srv/luogu-archive bash /srv/luogu-archive/scripts/backup-mysql.sh
ls -lh /var/backups/luogu-archive/
```

---

## 六、更新代码（后续迭代用）

```powershell
# Windows 本地：重新打包传上去
cd D:\code
tar --exclude='luogu-archive/backend/.venv' --exclude='luogu-archive/frontend/node_modules' --exclude='luogu-archive/frontend/.output' --exclude='luogu-archive/**/.env' -czf luogu-archive.tar.gz luogu-archive/
scp luogu-archive.tar.gz root@your-server-ip:/tmp/
```

```bash
# 服务器
sudo systemctl stop luogu-archive-web luogu-archive-frontend luogu-archive-scheduler 'luogu-archive-worker@*'
sudo rm -rf /tmp/luogu-archive && tar -xzf /tmp/luogu-archive.tar.gz -C /tmp/

# 小心：这会覆盖 .env。我们选择性复制
sudo rsync -a --exclude='.env' /tmp/luogu-archive/ /srv/luogu-archive/
sudo chown -R luogu:luogu /srv/luogu-archive

# 跑迁移 + 重建前端
sudo -u luogu bash /srv/luogu-archive/scripts/01-deploy-backend.sh
sudo -u luogu bash /srv/luogu-archive/scripts/02-deploy-frontend.sh

# 重启
sudo systemctl start luogu-archive-web luogu-archive-frontend luogu-archive-scheduler 'luogu-archive-worker@*'
```

---

## 七、故障排查

| 症状 | 排查命令 |
|---|---|
| 首页 502/504 | `systemctl status luogu-archive-frontend` 看前端 / `journalctl -u luogu-archive-web -n 100` |
| API 401 | Cookie/Authorization 没带；浏览器 F12 → Network 看 |
| 爬虫全挂 | `journalctl -u luogu-archive-worker@hi -n 200`，看是否是 MySQL 连接失败 / Cookie 失效 |
| Cookie 账号自动禁用 | 管理后台「爬取账号」看 `disabled_reason`；通常是 403 返回"用户尚未登录"→ 重新录入 Cookie |
| certbot 失败 | 确认 `dig <domain>` 解析到本机 IP；手动 `sudo certbot --nginx -d <domain>` |
| MySQL "Too many connections" | 低可能，默认 151 够用；`SHOW STATUS LIKE 'Threads_connected'` |

---

## 八、上线后清理

```bash
# 删掉初始化时生成的密钥明文文件
sudo rm /srv/luogu-archive/INIT_SECRETS.txt

# 定期检查备份是否正常
ls -lh /var/backups/luogu-archive/

# 查看是否有爬虫账号被禁用
# 登录管理后台 → 爬取账号 页
```

Done. 有问题回来问。
