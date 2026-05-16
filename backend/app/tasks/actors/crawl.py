"""爬虫任务 actor 样板。

每个具体数据源的 actor 在这里声明：接收参数 → 调用 app.crawler.sources.*.crawl_one →
async 运行 → 错误转成可读信息。

目前只定义**函数签名与 actor 装饰器**，真正的 crawl_one 实现在阶段 2。
"""
from __future__ import annotations

import dramatiq

from app.core.exceptions import CrawlerAccountInvalid, CrawlerNotFound
from app.core.logging import get_logger
from app.tasks.asyncio_runner import run_async
from app.tasks.broker import (
    QUEUE_CRAWL_FEED,
    QUEUE_CRAWL_HI,
    QUEUE_CRAWL_LOW,
    QUEUE_CRAWL_MID,
    get_broker,
)

# 触发 broker 初始化
get_broker()

log = get_logger(__name__)


# 通用重试策略：3 次指数退避，最长 1 分钟。
# CrawlerNotFound（404）/ CrawlerAccountInvalid 走 throws，dramatiq 不重试。
_RETRY = {
    "max_retries": 3,
    "min_backoff": 5_000,
    "max_backoff": 60_000,
    "throws": (CrawlerNotFound, CrawlerAccountInvalid),
}


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_article(article_id: str, trigger: str = "manual") -> None:
    """爬取单篇文章。手动保存按钮默认走这里。"""
    from app.crawler.sources.article import crawl_one

    log.info("actor.crawl_article", article_id=article_id, trigger=trigger)
    run_async(crawl_one(article_id, trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_paste(paste_id: str, trigger: str = "manual") -> None:
    from app.crawler.sources.paste import crawl_one

    log.info("actor.crawl_paste", paste_id=paste_id, trigger=trigger)
    run_async(crawl_one(paste_id, trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_HI, **_RETRY)
def crawl_user(uid: int, trigger: str = "manual") -> None:
    from app.crawler.sources.user import crawl_one

    log.info("actor.crawl_user", uid=uid, trigger=trigger)
    run_async(crawl_one(uid, trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_FEED, **_RETRY)
def crawl_user_feeds(uid: int, page: int = 1, trigger: str = "scheduled") -> None:
    """用 Cookie 账号爬某用户的犇犇。"""
    from app.crawler.sources.feed import crawl_user_page

    log.info("actor.crawl_user_feeds", uid=uid, page=page, trigger=trigger)
    run_async(crawl_user_page(uid, page=page, trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_judgement(trigger: str = "scheduled") -> None:
    """爬全站陶片放逐 500 条。"""
    from app.crawler.sources.judgement import crawl_all

    log.info("actor.crawl_judgement", trigger=trigger)
    run_async(crawl_all(trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def crawl_problem_list_page(page: int, trigger: str = "scheduled") -> None:
    from app.crawler.sources.problem import crawl_list_page

    log.info("actor.crawl_problem_list_page", page=page, trigger=trigger)
    run_async(crawl_list_page(page, trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_MID, **_RETRY)
def crawl_problem_solution(pid: str, trigger: str = "scheduled") -> None:
    from app.crawler.sources.problem import crawl_solution_state

    log.info("actor.crawl_problem_solution", pid=pid, trigger=trigger)
    run_async(crawl_solution_state(pid, trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def discover_from_discuss(trigger: str = "scheduled") -> None:
    from app.crawler.sources.discovery import from_discuss

    log.info("actor.discover_from_discuss", trigger=trigger)
    run_async(from_discuss(trigger=trigger))


@dramatiq.actor(queue_name=QUEUE_CRAWL_LOW, **_RETRY)
def discover_from_article_list(trigger: str = "scheduled") -> None:
    from app.crawler.sources.discovery import from_article_list

    log.info("actor.discover_from_article_list", trigger=trigger)
    run_async(from_article_list(trigger=trigger))
