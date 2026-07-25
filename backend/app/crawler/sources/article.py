"""文章爬虫。

端点：GET <base>/article/{article_id}
走 lentille-context。格式猜测（实测确认 after 开发期第一次跑）：
    data.article = { title, content, authorUid, ... }
    或 data.post, 或 data.data ...

在字段未确定前，我们用 `_extract_article_fields` 做防御式解析：
- 优先找 data.article
- 其次遍历 data 里的 dict 找含 `content` 字段的
- 失败则抛错，task 记录失败，管理员可在后台看到

这样部署后第一次实跑，管理员凭日志的 `extracted_keys` 可以快速调整字段映射。
"""
from __future__ import annotations

import time as _t
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.lentille import data_from_lentille
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    sha256_hex,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_content import Article, ArticleVersion

log = get_logger(__name__)


async def crawl_one(article_id: str, *, trigger: str = "manual") -> None:
    async with task_lock("article", article_id) as got:
        if not got:
            log.info("crawl_article.skip_locked", article_id=article_id)
            return
        await _crawl_inner(article_id, trigger=trigger)


def _extract_article_fields(data: dict) -> dict[str, Any]:
    """从 lentille data 字段里找 title/content/author(dict)/author_uid。

    防御式：洛谷字段命名偶尔变动，这里多猜几个位置。
    """
    candidates = []
    if isinstance(data.get("article"), dict):
        candidates.append(data["article"])
    if isinstance(data.get("post"), dict):
        candidates.append(data["post"])
    # 还可能直接挂在 data 上
    if "content" in data or "title" in data:
        candidates.append(data)

    for node in candidates:
        content = node.get("content") or node.get("contentMd") or node.get("markdown")
        title = node.get("title")
        if content is not None and title is not None:
            author_raw = node.get("author") if isinstance(node.get("author"), dict) else None
            author_uid = (author_raw.get("uid") if author_raw else None) or node.get("authorUid")
            return {
                "title": str(title),
                "content_md": str(content),
                "author_uid": int(author_uid) if author_uid else None,
                "author_raw": author_raw,
                "admin_note": (
                    str(node["adminNote"])
                    if node.get("adminNote") is not None
                    else None
                ),
            }
    # 未能识别，抛错并带上 key 列表供排查
    raise CrawlerError(
        f"无法从 data 中提取文章字段，可见 keys: {list(data.keys())}"
    )


async def _crawl_inner(article_id: str, *, trigger: str) -> None:
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    url_path = f"/article/{article_id}"
    task_id = await record_task_start(
        "article", url_path, trigger=trigger_from(trigger), node_id=node.node_id
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(url_path, node=node, redis=redis)
        if result.data is None:
            raise CrawlerError("文章页无 lentille-context")
        data = data_from_lentille(result.data)
        fields = _extract_article_fields(data)

        async with db_session() as session:
            await _upsert_article(session, article_id, fields, node_id=node.node_id)
            await _upsert_author_brief(session, fields.get("author_raw"))
            await session.commit()

        # 作者用户若 author_raw 里信息不全（比如缺 slogan/introduction），
        # 额外派一次完整用户爬取（带去重锁，不会重复）
        if fields.get("author_uid"):
            try:
                from app.tasks.actors.crawl import crawl_user_bg
                crawl_user_bg.send(fields["author_uid"], "cascaded_from_article")
            except Exception as e:
                log.warning("crawl_article.cascade_user_failed", error=str(e))

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("crawl_article.failed", article_id=article_id, error=str(e))
        raise


async def _upsert_article(
    session: AsyncSession,
    article_id: str,
    fields: dict[str, Any],
    *,
    node_id: str,
) -> None:
    now = utcnow()
    content_hash = sha256_hex(fields["content_md"])

    existing = await session.get(Article, article_id)
    if existing is None:
        art = Article(
            article_id=article_id,
            author_uid=fields.get("author_uid"),
            title=fields["title"][:500],
            admin_note=fields.get("admin_note"),
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(art)
        await session.flush()
        v = ArticleVersion(
            article_id=article_id,
            title=fields["title"][:500],
            content_md=fields["content_md"],
            content_hash=content_hash,
            crawled_at=now,
            crawler_node_id=node_id,
        )
        session.add(v)
        await session.flush()
        art.current_version_id = v.id
        return

    # 已存在：判重
    q = select(ArticleVersion).where(
        ArticleVersion.article_id == article_id,
        ArticleVersion.content_hash == content_hash,
    )
    same = (await session.execute(q)).scalar_one_or_none()
    if same is not None:
        # 管理员提示与正文独立变化，即使正文未改也必须同步当前提示。
        existing.admin_note = fields.get("admin_note")
        existing.last_crawled_at = now
        return

    # 内容变化 → 新版本
    v = ArticleVersion(
        article_id=article_id,
        title=fields["title"][:500],
        content_md=fields["content_md"],
        content_hash=content_hash,
        crawled_at=now,
        crawler_node_id=node_id,
    )
    session.add(v)
    await session.flush()
    existing.title = fields["title"][:500]
    existing.author_uid = fields.get("author_uid") or existing.author_uid
    existing.admin_note = fields.get("admin_note")
    existing.current_version_id = v.id
    existing.last_crawled_at = now


async def _upsert_author_brief(session: AsyncSession, author: dict | None) -> None:
    """文章 lentille 里的 author 对象通常含 {uid, name, color, badge, avatar, ...}，
    顺手在 luogu_users 表里做一次 upsert，避免前端"作者未收录"。
    """
    if not isinstance(author, dict):
        return
    from app.models._common import LuoguColor
    from app.models.luogu_user import LuoguUser

    uid_raw = author.get("uid")
    if not uid_raw:
        return
    uid = int(uid_raw)
    name = author.get("name") or f"UID_{uid}"
    try:
        color = LuoguColor(author.get("color") or "Gray")
    except ValueError:
        color = LuoguColor.Gray

    now = utcnow()
    existing = await session.get(LuoguUser, uid)
    if existing is None:
        session.add(
            LuoguUser(
                uid=uid,
                name=name,
                avatar=author.get("avatar"),
                background=author.get("background"),
                slogan=author.get("slogan"),
                badge=author.get("badge"),
                color=color,
                is_admin=bool(author.get("isAdmin")),
                is_banned=bool(author.get("isBanned")),
                ccf_level=int(author.get("ccfLevel") or 0),
                xcpc_level=int(author.get("xcpcLevel") or 0),
                first_crawled_at=now,
                last_crawled_at=now,
            )
        )
    else:
        existing.avatar = author.get("avatar") or existing.avatar
        existing.badge = author.get("badge") or existing.badge
        existing.color = color
        existing.last_crawled_at = now
