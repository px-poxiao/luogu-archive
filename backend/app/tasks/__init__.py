"""Dramatiq 任务队列配置 + actor 定义。

队列设计（按优先级分层）：
- crawler.hi    手动"保存"按钮、管理员强制爬取
- crawler.mid   实时监听、访问触发
- crawler.low   定时批量、入口发现
- crawler.feed  犇犇专用（走 AUTHED 节点，单独一队避免阻塞其他）

每个队列有独立的 worker 进程，通过启动参数 `--queues` 指定。

- broker.py   broker 实例化
- asyncio_runner.py   在同步 actor 里调度 async 函数（Dramatiq 自身是同步 API）
- actors/     实际任务定义
"""
