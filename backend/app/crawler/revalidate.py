"""访问触发 (stale-while-revalidate)。

用户访问一个内容，若本站数据 > 阈值（默认 1 分钟）则异步派发一次重爬。
不阻塞当前请求返回，下次刷新就能看到新版。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models._common import utcnow


def is_stale(last_crawled_at: datetime | None, *, stale_after_sec: int = 60) -> bool:
    """数据是否过期。"""
    if last_crawled_at is None:
        return True
    return utcnow() - last_crawled_at > timedelta(seconds=stale_after_sec)


async def schedule_refresh_article(article_id: str) -> None:
    from app.tasks.actors.crawl import crawl_article
    crawl_article.send(article_id, "passive")


async def schedule_refresh_paste(paste_id: str) -> None:
    from app.tasks.actors.crawl import crawl_paste
    crawl_paste.send(paste_id, "passive")


async def schedule_refresh_user(uid: int) -> None:
    from app.tasks.actors.crawl import crawl_user
    crawl_user.send(uid, "passive")
