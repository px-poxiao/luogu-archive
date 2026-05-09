"""Dramatiq actor 集合。

每个 actor 对应一类爬取任务。真实爬取逻辑住在 app.crawler.sources，
这里只做薄封装：接收参数 → run_async 调用 → 记录 CrawlTask。

队列路由：
- 默认 crawler.low（定时批量）
- 手动保存 → crawler.hi
- 实时监听 → crawler.mid
- 犇犇 → crawler.feed
"""
