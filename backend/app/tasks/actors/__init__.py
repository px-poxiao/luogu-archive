"""资源队列任务集合。

每个 actor 对应一类爬取任务。真实爬取逻辑住在 app.crawler.sources；
这里只做薄封装：接收参数 -> run_async 调用 -> 记录 CrawlTask。

队列路由：
- 用户等待中的任务 -> crawler.hi
- 普通后台任务 -> crawler.mid
- 所有题目相关任务 -> crawler.low
"""
