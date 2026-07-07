# 洛谷档案馆 (luogu-archive)

第三方爬虫与存档站，长期保存洛谷社区的**文章 / 剪贴板 / 犇犇 / 陶片放逐 / 题目**信息，并对用户名、难度、题解开放状态等做版本与时间序列追踪。

> 本站为第三方存档，与洛谷官方无关，所有内容版权归原作者。全站 `robots.txt` 禁收录，并提供 `/takedown` 侵权删除入口。**服务器部署在境外，不备案。**

---

## 目录

- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [架构要点](#架构要点)
  - [爬虫节点与限流](#爬虫节点与限流)
  - [任务队列优先级](#任务队列优先级)
  - [题目分层扫描](#题目分层扫描)
  - [邮箱验证](#邮箱验证)
  - [数据版本与隐藏规则](#数据版本与隐藏规则)
- [本地开发](#本地开发)
- [生产部署](#生产部署)
- [运维手册](#运维手册)
- [配置项参考](#配置项参考)
- [License](#license)

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async) |
| 数据库 | MySQL 8（aiomysql 异步 + pymysql 同步兜底） |
| 任务队列 | Dramatiq + Redis（4 条优先级队列） |
| 定时调度 | APScheduler |
| 爬虫 | httpx (HTTP/2) + lentille-context / `_feInjection` SSR 提取 |
| 渲染 | 前端 markdown-it + KaTeX；后端 markdown-it-py 管线 + 洛谷语法插件 |
| 前端 | Nuxt 3（Vue 3 + SSR）+ Pinia |
| 认证 | argon2（密码）+ TOTP（管理员 2FA）+ JWT（站内用户） |
| 邮件 | Resend HTTP API（推荐）/ SMTP |
| 反代 | Nginx（宝塔或裸机均可） |
| 进程管理 | `start.sh` / `stop.sh`（后台进程 + pid 文件）或 systemd |

---

## 目录结构

```
luogu-archive/
├── backend/                       # FastAPI + 爬虫 + 任务队列
│   ├── app/
│   │   ├── api/v1/                # save / content / user / auth / admin_auth / admin_panel / takedown
│   │   ├── auth/                  # argon2 / TOTP / JWT
│   │   ├── core/                  # 配置 / DB / Redis / 限流 / 锁 / 日志 / 邮件 / 验证码 / 异常
│   │   ├── crawler/
│   │   │   ├── nodes/             # 爬虫节点（anon/authed × 海外/主站，独立限流+熔断）
│   │   │   ├── sources/           # article/paste/user/feed/judgement/problem/discovery/image
│   │   │   ├── http.py            # 统一 HTTP 客户端（限流/熔断/lentille 提取）
│   │   │   ├── cookies.py         # Cookie 账号池（Redis INCR 轮询）
│   │   │   └── lentille.py        # SSR JSON 提取
│   │   ├── models/                # SQLAlchemy ORM
│   │   ├── render/                # Markdown 渲染 + 洛谷专有语法插件
│   │   ├── tasks/                 # Dramatiq broker + actors
│   │   ├── main.py                # FastAPI 入口
│   │   └── scheduler.py           # APScheduler 入口
│   ├── alembic/                   # 数据库迁移
│   ├── scripts/                   # CLI 工具（create_admin 等）
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                      # Nuxt 3
│   ├── pages/                     # 首页/文章/剪贴板/用户/陶片/犇犇/题目/登录注册/邮箱验证/管理后台
│   ├── components/                # 原文归属横幅+保存按钮 / 洛谷用户名 / 关注按钮 等
│   ├── composables/               # useApi / useAdminApi / useMarkdown / useTime
│   ├── layouts/                   # default（侧边栏）/ admin
│   ├── public/                    # favicon / robots.txt
│   └── .env.example
├── docs/
│   ├── nginx.conf.example         # Nginx 反代模板
│   └── systemd/                   # systemd unit 模板（可选部署方式）
├── start.sh / stop.sh             # 进程管理（宝塔兼容）
└── scripts/backup-mysql.sh        # MySQL 备份
```

---

## 架构要点

### 爬虫节点与限流

爬虫按「出口身份 × 目标域名」分成 4 个独立节点，各自独立的令牌桶 + 熔断状态：

| 节点 ID | 用途 | 速率 |
|---|---|---|
| `local-anon` | 海外镜像 luogu.com：犇犇接口、发现页 | `CRAWLER_ANON_RATE_PER_SEC`（默认 1 req/s） |
| `local-authed` | 海外镜像：带 Cookie 认证请求 | `CRAWLER_AUTH_RATE_PER_SEC`（默认 0.5 req/s） |
| `local-anon-cn` | 主站 luogu.com.cn：题目、陶片、标签字典 | **0.1 req/s（洛谷官方限制，硬编码）** |
| `local-authed-cn` | 主站：认证请求 | 0.1 req/s |

`/judgement`、`/problem`、`/_lfe` 等路径在 `crawler/http.py:_resolve_url` 里**强制走主站**，对应也必须用 `cn=True` 的节点取得方式（`get_default_node(kind, cn=True)`）。节点与域名错配会导致海外节点的限流计数被主站 0.1 req/s 污染、被错误熔断 —— 这是历史上"陶片保存不了"的根因。

**熔断**：单节点遇 429 / 明确反爬信号 → 该节点冷却 `CRAWLER_BREAKER_COOLDOWN_SEC`；10 分钟内连续 3 个节点被封 → 全局冷却。403/404 不直接熔断，走累计阈值 + 同类资源探针确认。

**Cookie 账号池**：仅犇犇爬取挂 Cookie。多账号用 Redis `INCR` 轮询，无 QPH 上限、无账号串行锁。账号失效自动禁用。

### 任务队列优先级

Dramatiq 使用 3 条队列，`scripts.priority_worker` 监督进程按严格顺序消费：只有 `crawler.hi` 为空时才跑 `crawler.mid`，只有 `crawler.mid` 也为空时才跑 `crawler.low`。

| 队列 | 内容 |
|---|---|
| `crawler.hi` | 用户正在等待的任务：手动保存、首次访问未收录内容、管理员强制爬取 |
| `crawler.mid` | 普通后台任务：发现、访问触发刷新、级联、定时犇犇 / 陶片 |
| `crawler.low` | 所有题目相关任务：题目列表页轮询、题解开放状态检测 |

用户手动保存用户主页时，`crawl_user_manual` 会在同一条 hi 任务里连续刷新用户主页和犇犇第一页，避免主页已更新但犇犇还卡在后台队列。题目任务即使由手动保存触发也统一走 low，避免一次列表刷新污染 hi 队列。

### 题目分层扫描

题解开放状态按难度分档轮询，避免一次性把上千题塞爆主站 0.1 req/s 队列：

- **tier1**（入门 / 普及-）：每小时，派距上次检查 ≥1h 的题
- **tier2**（普及/提高-）：每天，≥24h
- **tier3**（其他档 + 暂无评定）：每天派全档 1/7，7 天滚动一轮

列表页 cascade 派题解检测带 **30 分钟 Redis NX 去重**；scheduled / cascade 触发只派新题，老题交给分层轮询。这套机制是为了解决曾经队列堆积到 4 万+ 任务、把全站爬取拖死的问题。

### 邮箱验证

站内用户注册走邮箱验证：

```
注册 → 发验证邮件（24h token）→ 点链接打开前端 /auth/verify
     → 调 GET /api/v1/auth/verify?token=xxx → 标记 email_verified → 才能登录
```

支持「重发验证邮件」（`POST /auth/resend-verification`，同邮箱 60s 冷却 + 同 IP 每小时 5 次，不泄露邮箱是否存在）。邮件后端可选 Resend HTTP API（推荐）或 SMTP。

> 注意：从 MySQL 读回的 `DateTime` 是 naive（无时区），与 `utcnow()`（aware）比较前必须补 `tzinfo=timezone.utc`，否则抛 `TypeError` → 500。

### 数据版本与隐藏规则

- **文本字段**（文章 / 剪贴板 / 用户介绍）逐版本保留，按内容 SHA-256 去重；超长内容用 `LONGTEXT`
- **数值字段**（follower / Elo / 咕值）存时间序列，不算版本
- **用户名违规级联隐藏**：命中（陶片关键词 / 系统格式 `_user_\d+` / 管理员手动）后，该时刻之前所有历史名永久隐藏、解封不恢复；改回合规名后新名正常显示

---

## 本地开发

需要本地 MySQL 8 + Redis 7。

```bash
mysql -uroot -p -e "CREATE DATABASE luogu_archive DEFAULT CHARSET utf8mb4;"
mysql -uroot -p -e "CREATE USER 'luogu_archive'@'localhost' IDENTIFIED BY 'dev_password';"
mysql -uroot -p -e "GRANT ALL ON luogu_archive.* TO 'luogu_archive'@'localhost';"
```

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env
# 最少填：DB_PASSWORD / JWT_SECRET / ADMIN_TOTP_ENCRYPTION_KEY
#   JWT_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
#   ADMIN_TOTP_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")

alembic upgrade head
python -m scripts.create_admin     # 交互式创建管理员，记下 TOTP secret（只显示一次）

# 三个进程分别起：
uvicorn app.main:app --reload --port 8000
python -m scripts.priority_worker
python -m app.scheduler            # 可选，开发期可手动触发
```

### 前端

```bash
cd frontend
npm install                        # 或 pnpm install
cp .env.example .env
# 编辑：NUXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                        # http://localhost:3000
```

---

## 生产部署

目标：境外 Ubuntu/Debian 服务器（2 vCPU / 4 GB+），已装 MySQL 8 + Redis + Nginx + Node 20 + Python 3.11+。代码放在 `/data/luogu-archive`（宝塔默认）或自定义路径。

### 1. 数据库

```sql
CREATE DATABASE luogu_archive DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'luogu_archive'@'localhost' IDENTIFIED BY '<强密码>';
GRANT ALL ON luogu_archive.* TO 'luogu_archive'@'localhost';
FLUSH PRIVILEGES;
```

### 2. 后端环境

```bash
cd /data/luogu-archive/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# 关键字段（见下方“配置项参考”）：
#   APP_ENV=production / APP_DEBUG=false
#   DB_PASSWORD / JWT_SECRET / ADMIN_TOTP_ENCRYPTION_KEY
#   WEB_PUBLIC_ORIGIN=https://你的域名   ← 邮件验证链接靠它，务必填对
#   MAIL_PROVIDER=resend / RESEND_API_KEY / MAIL_FROM
#   CAPTCHA_SITE_KEY / CAPTCHA_SECRET

alembic upgrade head
python -m scripts.create_admin
```

生成密钥：

```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"   # ADMIN_TOTP_ENCRYPTION_KEY
python -c "import secrets;print(secrets.token_hex(32))"                                     # JWT_SECRET
```

### 3. 前端构建

```bash
cd /data/luogu-archive/frontend
npm install
cp .env.example .env
# NUXT_API_INTERNAL_URL=http://127.0.0.1:8000   （或后端实际端口）
# NUXT_PUBLIC_API_BASE_URL=https://你的域名
npm run build
```

### 4. 启动（start.sh）

```bash
cd /data/luogu-archive
./start.sh             # 启动 backend / worker / scheduler / frontend
./start.sh status      # 查看状态
```

`start.sh` 把进程放后台，pid 写 `run/`，日志写 `logs/`。后端默认监听 `127.0.0.1:8000`（或 .env 的 WEB_PORT），前端 `127.0.0.1:3000`。

### 5. Nginx 反代 + HTTPS

参考 `docs/nginx.conf.example`：把域名反代到前端 3000，`/api/` 反代到后端。宝塔可在面板里配反代 + 一键 SSL；裸机用 certbot。

### systemd 方式（可选）

如果不用 `start.sh` 而用 systemd，`docs/systemd/` 下有 unit 模板（web / frontend / scheduler / worker）。

---

## 运维手册

### 日常启停

```bash
cd /data/luogu-archive
./stop.sh backend && ./start.sh backend      # 改了后端代码/.env 后
./stop.sh worker && ./start.sh worker        # 改了爬虫/actor 后
./stop.sh scheduler && ./start.sh scheduler  # 改了定时任务后

# 前端改动需重新 build
cd frontend && rm -rf .nuxt .output && npm run build
cd .. && ./stop.sh frontend && ./start.sh frontend
```

### 看日志

```bash
tail -f /data/luogu-archive/logs/backend.log
tail -f /data/luogu-archive/logs/worker.log
grep -iE "judgement|RateLimit|Blocked" /data/luogu-archive/logs/worker.log | tail -30
```

### Redis 运维

```bash
# 队列堆积（注意 .msgs 是 hash，用 HLEN；就绪队列是 list，用 LLEN）
redis-cli -a <密码> HLEN dramatiq:crawler.mid.msgs
redis-cli -a <密码> LLEN dramatiq:crawler.hi

# 清空某条队列（中断积压，已爬数据不丢）
redis-cli -a <密码> DEL dramatiq:crawler.mid dramatiq:crawler.mid.msgs

# 清节点熔断状态
redis-cli -a <密码> --scan --pattern 'crawler:breaker:*' | xargs -r redis-cli -a <密码> DEL

# 清保存去重锁（保存按钮“没反应”时）
redis-cli -a <密码> DEL save:pending:judgement:all lk:crawl:judgement:all
```

### 首次配置 Cookie 账号（爬犇犇必须）

登录 `/admin/login`（管理员账号 + 密码 + TOTP）→「爬取账号」→「录入新账号」，填 `_uid` + `__client_id`（浏览器登录洛谷后 F12 → Application → Cookies 取）。保号原则：别在控制台狂点测试。

### 备份

`scripts/backup-mysql.sh` 做 mysqldump，建议挂 cron 每天跑一次。

### 常见故障

| 症状 | 排查 |
|---|---|
| 保存按钮没反应 | worker 是否在跑；mid/hi 队列是否堆积；`save:pending:*` 去重锁是否卡住 |
| 陶片/题目爬取超时 | cn 节点队列是否被全量任务堆满；`crawler:breaker:*` 是否残留 |
| 邮件发了收不到 | Resend 后台看投递状态；域名是否验证（SPF/DKIM）；`MAIL_FROM` 是否在验证域名下 |
| 验证链接 500 | naive/aware datetime 比较（见上）；看 `backend.log` traceback |
| 队列越堆越多 | 检查 cascade 去重是否生效；分层扫描配额是否过大 |

---

## 配置项参考

后端 `.env`（完整见 `backend/.env.example`）：

| 变量 | 说明 |
|---|---|
| `APP_ENV` / `APP_DEBUG` | 生产填 `production` / `false` |
| `DB_*` | MySQL 连接 |
| `REDIS_URL` | Redis（含密码，如 `redis://:pass@127.0.0.1:6379/0`） |
| `CRAWLER_BASE_URL` | 默认 `https://www.luogu.com.cn` |
| `CRAWLER_ANON_RATE_PER_SEC` / `CRAWLER_AUTH_RATE_PER_SEC` | 海外节点速率（主站固定 0.1，不由此控制） |
| `NODE_ID` | 多机部署时每台 worker 填唯一值，单机留空 |
| `JWT_SECRET` | 站内用户 JWT 密钥（256bit hex） |
| `ADMIN_TOTP_ENCRYPTION_KEY` | 管理员 TOTP secret 加密用 Fernet key |
| `WEB_PUBLIC_ORIGIN` | 对外域名，**邮件验证链接靠它拼，务必填对** |
| `WEB_CORS_ORIGINS` | 允许的前端来源，逗号分隔 |
| `MAIL_PROVIDER` | `resend` 或 `smtp` |
| `RESEND_API_KEY` / `MAIL_FROM` | Resend：`MAIL_FROM` 须为已验证域名地址 |
| `SMTP_*` | SMTP 配置 |
| `CAPTCHA_PROVIDER` / `CAPTCHA_SITE_KEY` / `CAPTCHA_SECRET` | Turnstile / hCaptcha |
| `SAVE_IP_WINDOW_*` | 保存按钮 IP 限流 |
| `IMAGE_MIRROR_*` | 图片镜像存储 |

前端 `.env`：

| 变量 | 说明 |
|---|---|
| `NUXT_API_INTERNAL_URL` | SSR 服务端访问后端的内网地址（如 `http://127.0.0.1:8000`） |
| `NUXT_PUBLIC_API_BASE_URL` | 浏览器访问后端的地址（生产填对外域名） |
| `NUXT_PUBLIC_CAPTCHA_PROVIDER` / `NUXT_PUBLIC_CAPTCHA_SITE_KEY` | 人机验证 |

---

## License

MIT（代码）。存档内容版权归洛谷原作者所有。
