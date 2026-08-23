"""在后台队列中执行删除申请可访问性探测。"""
from __future__ import annotations

from sqlalchemy import func, select

from app.core.db import db_session
from app.crawler.sources import article as article_crawler
from app.crawler.sources import feed as feed_crawler
from app.crawler.sources import paste as paste_crawler
from app.models._common import utcnow
from app.models.luogu_content import Article, Feed, Paste
from app.models.task import TakedownProbe


async def run_takedown_probe(token: str) -> None:
    """执行一次真实抓取；任何不明确的失败都按不可访问处理。"""
    async with db_session() as db:
        row = await db.get(TakedownProbe, token)
        if row is None or row.status == "completed":
            return
        row.status = "running"
        await db.commit()
        try:
            if row.target_type == "user":
                row.author_uid, row.accessible = int(row.target_id), None
            elif row.target_type == "article":
                await article_crawler.crawl_one(row.target_id, trigger="manual")
                item = await db.get(Article, row.target_id)
                row.accessible = item is not None and not item.is_deleted_on_source
                row.author_uid = item.author_uid if item and item.author_uid else row.author_uid
            elif row.target_type == "paste":
                await paste_crawler.crawl_one(row.target_id, trigger="manual")
                item = await db.get(Paste, row.target_id)
                row.accessible = item is not None and not item.is_deleted_on_source
                row.author_uid = item.author_uid if item and item.author_uid else row.author_uid
            else:
                item = await db.get(Feed, int(row.target_id))
                row.author_uid = item.author_uid if item and item.author_uid else row.author_uid
                if item is None or item.author_uid is None:
                    row.accessible = False
                else:
                    newer = await db.scalar(select(func.count()).select_from(Feed).where(
                        Feed.author_uid == item.author_uid, Feed.time > item.time)) or 0
                    page = int(newer) // 20 + 1
                    fetched = await feed_crawler.crawl_user_page(
                        item.author_uid, page=page, trigger="manual")
                    row.accessible = int(row.target_id) in fetched
            row.detail = None
        except Exception as exc:  # 403、404、超时等均不能阻断申请。
            # 保留创建探测任务时从档案读取的作者 UID，供本人申请自动批准。
            row.accessible, row.detail = False, type(exc).__name__
        row.status, row.completed_at = "completed", utcnow()
        await db.commit()
