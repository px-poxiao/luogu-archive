# 宝塔面板部署（luogu-archive）

本文假设你熟悉宝塔，不拆开讲如何装宝塔本身。

**目标流程**：

```
宝塔 Nginx（80/443 + SSL）
    ↓ 反代
  luogu-archive 的 start.sh 起的两个进程
    ├─ 前端 Nuxt   127.0.0.1:3000
    └─ 后端 FastAPI 127.0.0.1:8000
```

MySQL / Redis / Python / Node 都交给宝塔管，应用只管自己那部分。

---

## 一、宝塔里先装好这几样

打开宝塔面板 → **软件商店**，按需安装：

| 组件 | 版本要求 | 说明 |
|---|---|---|
| **Nginx** | 任意稳定版 | 宝塔自带，用作反代 |
| **MySQL** | 8.0+ | 应用用 utf8mb4 |
| **Redis** | 6+ | 默认端口 6379 |
| **Python 项目管理器** 或 Python 版本管理 | 3.11 / 3.12 | 用于装 Python 3.11+（默认的 3.6/3.8 不够） |
| **PM2 管理器** | 最新 | 用来管 Node 20+（或宝塔自带 Node 管理） |

确保能直接在 shell 里执行：

```bash
python3.12 --version    # Python 3.12.x
node --version          # v20.x 或更高
pnpm --version          # 若没有，下文会装
mysql --version         # 8.0+
redis-cli ping          # PONG
```

如果 `python3.12` 命令不通，宝塔 Python 版本管理器里装一个 3.12 后，它一般装在 `/www/server/python_manager/versions/3.12.x/bin/python3`，可以软链一下：

```bash
sudo ln -sf /www/server/python_manager/versions/3.12.*/bin/python3 /usr/local/bin/python3.12
```

如果 node 没全局可用，宝塔 PM2 管理器里 Node 版本一般在 `/www/server/nvm/versions/node/v20.x.x/bin/node`，把这个路径加 PATH 或软链。

---

## 二、宝塔里建好数据库

**宝塔面板 → 数据库 → 添加数据库**

- 数据库名：`luogu_archive`
- 字符集：`utf8mb4`
- 用户名：`luogu_archive`
- 密码：**强随机**（记下来，install.sh 要填）
- 访问权限：本地服务器

---

## 三、上传代码

把你 Windows 上的 `D:\code\luogu-archive\` 整个目录传到服务器，放哪都行，推荐 `/www/wwwroot/luogu-archive` 或 `/home/luogu-archive`。

### 上传方式（3 选 1）

**方式 A · 宝塔文件管理器**：网站 → 文件 → 右侧工具 → 上传，直接拖压缩包上来解压。

**方式 B · SCP**：

PowerShell 里：
```powershell
cd D:\code
tar --exclude='luogu-archive/backend/.venv' `
    --exclude='luogu-archive/frontend/node_modules' `
    --exclude='luogu-archive/frontend/.output' `
    --exclude='luogu-archive/backend/__pycache__' `
    --exclude='luogu-archive/**/.env' `
    -czf luogu-archive.tar.gz luogu-archive/

scp luogu-archive.tar.gz root@<server-ip>:/www/wwwroot/
```

服务器上：
```bash
cd /www/wwwroot
tar -xzf luogu-archive.tar.gz
chmod +x luogu-archive/install.sh luogu-archive/start.sh luogu-archive/stop.sh
```

**方式 C · Git 拉取**：服务器 `git clone https://...`

---

## 四、跑安装向导

```bash
cd /www/wwwroot/luogu-archive
./install.sh
```

安装向导会交互式问你：

- MySQL 主机 / 端口 / 库名 / 用户 / 密码 → **填宝塔里建的那一套**
- Redis 地址 → 默认 `redis://127.0.0.1:6379/0` 即可
- 站点域名 → 不带 https:// 前缀
- 联系邮箱（爬虫 User-Agent 用）
- SMTP（邮箱验证用，可以先留空，后续手改 .env）
- Turnstile 验证码 key（可选）
- 后端/前端监听端口 → 默认 8000 / 3000

向导会自动：
1. 装 Python 依赖到 `backend/.venv`
2. 跑 alembic 迁移（建 18 张表）
3. 装前端依赖 + `pnpm build`
4. 若没管理员，引导你**交互式创建第一个管理员** —— 注意打印的 TOTP secret 只出现一次，立刻加到 Google Authenticator / Authy

跑完后向导会提示"下一步：./start.sh"。

---

## 五、启动

```bash
cd /www/wwwroot/luogu-archive
./start.sh
```

看到 4 个服务 `✓ pid=...` 就对了。

```bash
./start.sh status     # 看进程状态
./stop.sh             # 全部停止
./start.sh backend    # 只重启某个
```

日志在 `./logs/<服务名>.log`，PID 在 `./run/<服务名>.pid`。

---

## 六、宝塔 Nginx 反代配置

**宝塔 → 网站 → 添加站点**

- 域名：`archive.example.com`（你的域名）
- PHP 版本：**纯静态**（我们不用 PHP）
- 数据库：不创建（已经在第二步建了）
- 建站目录：留默认

建好后点**站点 → 设置**：

### 6.1 SSL

面板 → SSL → **Let's Encrypt**，点"申请"即可。前提是域名 DNS 已经指向本服务器。强制 HTTPS 打开。

### 6.2 反向代理 → 自定义配置

因为宝塔"反向代理"向导只能反代一个后端，而我们有两个（前端 + API），所以**直接改配置**。

**站点 → 设置 → 配置文件**，在 `server { ... }` 块最里面（在 access_log 附近）加上：

```nginx
    # ---- luogu-archive 反代 ----

    # 禁搜索引擎收录（合规底线）
    add_header X-Robots-Tag "noindex, nofollow, noarchive" always;

    # robots.txt 直接返回
    location = /robots.txt {
        add_header Content-Type text/plain;
        return 200 "User-agent: *\nDisallow: /\n";
    }

    # 镜像图片：nginx 直接发，不走应用
    location /static/img/ {
        alias /www/wwwroot/luogu-archive/data/image_mirror/;
        expires 30d;
        access_log off;
        add_header Cache-Control "public, max-age=2592000";
        try_files $uri =404;
    }

    # 后端 API
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        client_max_body_size 20m;
    }

    location = /healthz {
        proxy_pass http://127.0.0.1:8000/healthz;
        access_log off;
    }

    # 前端 Nuxt SSR
    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_read_timeout 60s;
    }

    # ---- end of luogu-archive ----
```

保存，宝塔会自动 `nginx -t` + reload。

---

## 七、验证

浏览器打开：

- `https://archive.example.com/healthz` → `{"status":"ok"}`
- `https://archive.example.com/` → 首页
- `https://archive.example.com/admin/login` → 管理后台登录页

用户名 + 密码 + TOTP 6 位，登录管理后台：

1. 首次必须操作：**爬取账号 → 录入新账号**
   - Luogu UID、_uid、__client_id（F12 从洛谷网站复制）
2. 犇犇爬虫任务派发后就会走这个 cookie

---

## 八、更新代码

```bash
cd /www/wwwroot/luogu-archive
./stop.sh

# 用新压缩包覆盖（rsync 保留 .env / data）
# 假设新版本已上传到 /tmp/luogu-archive-new.tar.gz
tar -xzf /tmp/luogu-archive-new.tar.gz -C /tmp/
rsync -a --exclude='.env' --exclude='data' --exclude='.venv' --exclude='node_modules' \
    --exclude='.output' --exclude='run' --exclude='logs' \
    /tmp/luogu-archive/ /www/wwwroot/luogu-archive/

cd /www/wwwroot/luogu-archive
# 重装依赖 + 重跑迁移
./install.sh      # 会自动跳过已配置好的部分，只装新依赖 + 跑迁移
./start.sh
```

---

## 九、定时备份（宝塔计划任务）

**宝塔 → 计划任务 → 添加任务**

- 任务类型：**Shell 脚本**
- 执行周期：**每天 3:00**
- 脚本内容：
  ```bash
  cd /www/wwwroot/luogu-archive
  HOME=/www/wwwroot/luogu-archive bash scripts/backup-mysql.sh
  ```

也可以用**宝塔的"数据库备份"**功能，更直观。

---

## 十、常见问题

### `pnpm: command not found`
`npm install -g pnpm` 装一下。

### 宝塔的 Python 在哪？
`/www/server/python_manager/versions/3.12.*/bin/` 下面有 `python3` `pip3`，可以 `ln -s` 到 `/usr/local/bin/python3.12`。

### install.sh 里数据库迁移失败
检查：
- 宝塔里建的库名/用户名/密码是否和向导输入的一致
- 宝塔 → MySQL → 管理，看 MySQL 服务是否在跑
- `mysql -u<user> -p<pass> -h 127.0.0.1 -e 'SELECT 1'` 能不能连通

### 爬虫一直显示"被拦截"
- 管理后台 → 爬取账号，看 `last_status`，是否被洛谷封了
- 换一个 cookie 账号

### 开机自启
宝塔 → 计划任务 → 添加任务：
- 类型：Shell
- 执行周期：每分钟（只是让它被写到 crontab，不是真的每分钟跑）
- 改成 `@reboot`（宝塔的不支持直接写 @reboot，可以改成 `crontab -e` 手加）
- 或者**更简单**：开机自启脚本
  ```bash
  # /etc/systemd/system/luogu-archive.service
  [Unit]
  Description=luogu-archive one-shot starter
  After=network.target mysqld.service redis.service
  [Service]
  Type=oneshot
  RemainAfterExit=yes
  WorkingDirectory=/www/wwwroot/luogu-archive
  ExecStart=/www/wwwroot/luogu-archive/start.sh all
  ExecStop=/www/wwwroot/luogu-archive/stop.sh all
  [Install]
  WantedBy=multi-user.target
  ```
  然后 `systemctl enable luogu-archive`

---

## 十一、给自己一个运维 cheat sheet

```bash
# 看状态
./start.sh status

# 重启
./stop.sh && ./start.sh

# 实时看某服务日志
tail -f logs/backend.log
tail -f logs/worker.log

# 看任务队列长度
redis-cli llen dramatiq:crawler.hi.msgs
redis-cli llen dramatiq:crawler.feed.msgs

# 手动触发一次陶片爬取
cd backend
.venv/bin/python -c "from app.tasks.actors.crawl import crawl_judgement; crawl_judgement.send('manual')"

# 进数据库
mysql -u luogu_archive -p luogu_archive

# 清空当次会话，重新安装
./stop.sh
rm -rf backend/.venv frontend/node_modules frontend/.output backend/.env frontend/.env
./install.sh
```
