# 本地开发指南（Windows / WSL）

## 前置

- **Windows 10/11** + **WSL2** 推荐（MySQL / Redis 在 Ubuntu 里更稳），或纯 Windows
- Python 3.11+
- Node 20+
- pnpm（或 npm）
- Git

## 选项 A：纯 Windows（最少环境改造）

### 1. 装 MySQL 8 + Redis

- MySQL：下载 [MySQL Installer](https://dev.mysql.com/downloads/installer/)，选 Server 8.x + Workbench
- Redis：下载 [Redis for Windows](https://github.com/tporadowski/redis/releases) 或用 [Memurai](https://www.memurai.com/)（生产级 Redis 兼容实现）

### 2. 建库

在 MySQL Workbench 或 mysql CLI：
```sql
CREATE DATABASE luogu_archive DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'luogu_archive'@'localhost' IDENTIFIED BY 'dev_password';
GRANT ALL ON luogu_archive.* TO 'luogu_archive'@'localhost';
```

### 3. 后端

```powershell
cd D:\code\luogu-archive\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

Copy-Item .env.example .env
# 编辑 .env，填入：
#   DB_PASSWORD=dev_password
#   ADMIN_TOTP_ENCRYPTION_KEY=<Fernet key>
#   JWT_SECRET=<64 位 hex>
# 生成两个密钥：
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
python -c "import secrets;print(secrets.token_hex(32))"

# 迁移
alembic upgrade head

# 创建首个管理员（交互式）
python -m scripts.create_admin

# 启动（建议 4 个 PowerShell 窗口）
# 窗口 1：Web
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 窗口 2：Worker（所有队列）
dramatiq app.tasks.actors.crawl --queues crawler.hi crawler.mid crawler.low crawler.feed

# 窗口 3：Scheduler（可选；开发时可手动触发任务）
python -m app.scheduler
```

### 4. 前端

```powershell
cd D:\code\luogu-archive\frontend
npm install -g pnpm
pnpm install
Copy-Item .env.example .env
pnpm dev
# 打开 http://localhost:3000
```

## 选项 B：WSL Ubuntu（推荐，更接近生产）

```bash
sudo apt install -y mysql-server redis-server python3.11 python3.11-venv nodejs npm
sudo systemctl start mysql redis

# 后续步骤同"选项 A 第 2 步起"
```

## 常用开发操作

### 触发一次爬取（不等定时）
```python
# 进入 Python shell
cd backend && python
>>> from app.tasks.actors.crawl import crawl_user
>>> crawl_user.send(8457, "manual")
# 任务会被 worker 消费
```

### 手动跑一次 judgement
```bash
curl -X POST http://localhost:8000/api/v1/save \
  -H 'Content-Type: application/json' \
  -d '{"content_type": "judgement", "id": "all"}'
```

### 生成新数据库迁移
```bash
# 修改 app/models/*.py 后
cd backend
alembic revision --autogenerate -m "描述"
alembic upgrade head
```

### 清空本地测试数据
```sql
-- 在开发数据库（不是生产！）
DROP DATABASE luogu_archive;
CREATE DATABASE luogu_archive DEFAULT CHARSET utf8mb4;
-- 然后 alembic upgrade head
```

### 查看队列堆积
```bash
redis-cli
> KEYS dramatiq:*
> LLEN dramatiq:crawler.hi.msgs
```

## 调试技巧

- **日志开发态彩色输出**：`APP_ENV=development` 时 structlog 自动用 ConsoleRenderer
- **SQL 调试**：修改 `app/core/db.py` 的 `echo=True` 临时开
- **Dramatiq 堆栈**：任务失败后 redis 里会有 dead letter，用 `redis-cli LRANGE dramatiq:default.DLQ 0 -1` 查
- **洛谷接口抓包**：浏览器 F12 → Network，对比本站爬虫是否字段一致
