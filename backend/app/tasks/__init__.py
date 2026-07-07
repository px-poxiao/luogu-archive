"""Dramatiq 任务队列配置 + actor 定义。

队列设计：
- crawler.hi    用户正在等待的任务：手动保存、首次访问未收录内容、管理员强制爬取
- crawler.mid   普通后台任务：发现、访问触发刷新、级联、定时犇犇 / 陶片
- crawler.low   题目任务：题目列表页轮询、题解开放状态检测

每个队列通过 worker 启动参数 `--queues` 指定。

- broker.py   broker 实例化
- asyncio_runner.py   在同步 actor 里调度 async 函数
- actors/     实际任务定义
"""