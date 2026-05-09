# 洛谷存档站 (luogu-archive)

第三方爬虫与保存站，永久保存洛谷社区的文章 / 剪贴板 / 犇犇 / 陶片放逐 / 题目信息。

**完整需求 + 架构决策见 [../3.md](../3.md)**。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 async |
| 数据库 | MySQL 8 |
| 队列 | Dramatiq + Redis |
| 调度 | APScheduler |
| 爬虫 | httpx (http2) + lentille-context 提取 |
| 渲染 | markdown-it-py + 洛谷语法插件 + KaTeX (前端) |
| 前端 | Nuxt 3 (Vue 3 + SSR) + Pinia |
| 反代 | Nginx |
| 认证 | argon2（密码） + TOTP（管理员 2FA） + JWT |

## 目录结构

```
luogu-archive/
├── backend/                       # FastAPI + 爬虫 + 任务队列
│   ├── app/
│   │   ├── api/                   # REST 路由（v1/）
│   │   ├── auth/                  # argon2 / TOTP / JWT
│   │   ├── core/                  # 配置 / DB / Redis / 限流 / 锁 / 日志 / 异常
│   │   ├── crawler/               # 节点 / HTTP 客户端 / Cookie 池 / 7 种数据源
│   │   ├── models/                # SQLAlchemy ORM（18 张表）
│   │   ├── render/                # Markdown 渲染管线 + 洛谷专有语法插件
│   │   ├── tasks/                 # Dramatiq broker + actors
│   │   ├── main.py                # FastAPI 入口
│   │   └── scheduler.py           # APScheduler 入口
│   ├── alembic/                   # 数据库迁移
│   ├── scripts/                   # CLI 工具（如 create_admin.py）
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                      # Nuxt 3
│   ├── pages/                     # 首页 / 文章 / 剪贴板 / 用户 / 陶片 / 犇犇 / 题目 / 管理后台
│   ├── components/                # 原文归属横幅 / 保存按钮 / 洛谷用户名 / 关注按钮
│   ├── composables/               # useApi / useAdminApi / useMarkdown
│   ├── stores/                    # auth / admin
│   ├── layouts/                   # default / admin
│   └── public/robots.txt          # 禁搜索引擎收录
├── docs/
│   ├── nginx.conf.example
│   ├── systemd/                   # systemd unit
│   ├── DEPLOY.md                  # 部署文档
│   └── DEV.md                     # 本地开发文档
└── scripts/
    └── backup-mysql.sh            # MySQL 备份脚本
```

## 快速开始

### 本地开发（Windows / WSL / Linux 同）

1. **准备环境**
   ```bash
   # MySQL 8 + Redis 7 本地运行
   # 创建库
   mysql -uroot -p -e "CREATE DATABASE luogu_archive DEFAULT CHARSET utf8mb4;"
   mysql -uroot -p -e "CREATE USER 'luogu_archive'@'localhost' IDENTIFIED BY 'dev_password';"
   mysql -uroot -p -e "GRANT ALL ON luogu_archive.* TO 'luogu_archive'@'localhost';"
   ```

2. **后端**
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"

   cp .env.example .env
   # 编辑 .env：
   #   DB_PASSWORD=dev_password
   #   ADMIN_TOTP_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
   #   JWT_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")

   # 迁移数据库
   alembic upgrade head

   # 创建第一个管理员（交互式）
   python -m scripts.create_admin

   # 启动 Web
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

   # 另起：启动 worker（开发只跑一个队列够用）
   dramatiq app.tasks.actors.crawl --queues crawler.hi crawler.mid crawler.low crawler.feed

   # 另起：启动调度器（可选，开发阶段可以不开，手动触发即可）
   python -m app.scheduler
   ```

3. **前端**
   ```bash
   cd frontend
   pnpm install        # 或 npm install
   cp .env.example .env
   pnpm dev
   # 访问 http://localhost:3000
   ```

### 生产部署（Linux + Nginx + systemd）

详见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 重要约束

### 合规底线
- `robots.txt` 全站禁收录
- 所有内容页顶部显示原文归属横幅
- 有 `/takedown` 删除申请入口，管理员 24h 响应
- **服务器部署在国外，不备案**

### 爬虫"保号"
- 仅犇犇爬取挂 Cookie，其他内容游客访问
- 匿名节点 1 req / 3s，认证节点 1 req / 6s + 账号每小时 ≤ 300 次
- Cookie 账号失效立即禁用告警；连续 3 节点被封→全局冷却

### 版本快照
- 文本字段（文章/剪贴板/用户介绍）逐版本保留
- 数值字段（follower / Elo / 咕值）存时间序列，不视作版本

### 用户名违规级联隐藏
- 命中（陶片关键词 / 系统格式 `_user_\d+` / 管理员手动）
- 此时刻之前所有历史名永久隐藏，解封不恢复
- 改成合规名后新名正常显示

## License

MIT（代码）。存档内容版权归洛谷原作者。
