"""爬虫模块。

层次：
- nodes/       CrawlerNode 抽象与实现（节点身份 + 独立限流 + 熔断）
- http.py      基于 httpx 的 HTTP 客户端工厂（匿名 / 带账号）
- lentille.py  从洛谷 HTML 里提取 lentille-context JSON 的工具
- cookies.py   爬取账号 Cookie 池（加密存储、轮换、自检）
- sources/     具体数据源爬虫（article/paste/feed/judgement/problem/user）
"""
