"""剪贴板爬虫。

**洛谷剪贴板用的是老版前端**，数据在 `window._feInjection` 里，
不是 `<script id="lentille-context">`。用 extract_page_data 自动识别两种结构。
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
from app.crawler.lentille import (
    current_data_from_injection,
    data_from_lentille,
    extract_page_data,
)
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    sha256_hex,
    task_lock,
    trigger_from,
)
from app.models._common import CrawlTaskStatus, utcnow
from app.models.luogu_content import Paste, PasteVersion

log = get_logger(__name__)


async def crawl_one(paste_id: str, *, trigger: str = "manual") -> None:
    async with task_lock("paste", paste_id) as got:
        if not got:
            log.info("crawl_paste.skip_locked", paste_id=paste_id)
            return
        await _crawl_inner(paste_id, trigger=trigger)


def _extract_paste_fields(kind: str, data: dict) -> dict[str, Any]:
    """从两种 SSR 结构里取字段。

    - kind="injection"（老版，剪贴板实际走这个）：
        currentData.paste = { id, user, data, time, public }
    - kind="lentille"（新版，暂未观察到但留兜底）：
        data.paste = { ..., content/data/contentMd }
    """
    if kind == "injection":
        current = current_data_from_injection(data)
        paste = current.get("paste") if isinstance(current.get("paste"), dict) else None
        if not paste:
            raise CrawlerError(f"injection.currentData 里无 paste: keys={list(current.keys())}")
        content = paste.get("data") or paste.get("content") or paste.get("contentMd") or ""
        user = paste.get("user") if isinstance(paste.get("user"), dict) else {}
        return {
            "content_md": str(content),
            "author_uid": int(user.get("uid")) if user.get("uid") else None,
        }

    # kind == "lentille"：按常见位置遍历
    inner = data_from_lentille(data)
    for candidate in (inner.get("paste"), inner.get("post"), inner):
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("data") or candidate.get("content") or candidate.get("contentMd")
        if content is None:
            continue
        author = candidate.get("user") if isinstance(candidate.get("user"), dict) else {}
        author_uid = author.get("uid") if author else candidate.get("authorUid")
        return {
            "content_md": str(content),
            "author_uid": int(author_uid) if author_uid else None,
        }
    raise CrawlerError(f"无法从 data 中提取剪贴板字段，可见 keys: {list(inner.keys())}")


async def _crawl_inner(paste_id: str, *, trigger: str) -> None:
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    url_path = f"/paste/{paste_id}"
    task_id = await record_task_start(
        "paste", url_path, trigger=trigger_from(trigger), node_id=node.node_id
    )
    start = _t.monotonic()
    try:
        # 不依赖 fetch_anon 自动 lentille 解析，手动处理
        result = await fetch_anon(url_path, node=node, redis=redis, parse="html")
        kind, page_data = extract_page_data(result.body_text)
        fields = _extract_paste_fields(kind, page_data)

        async with db_session() as session:
            await _upsert_paste(session, paste_id, fields, node_id=node.node_id)
            await session.commit()

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
        log.error("crawl_paste.failed", paste_id=paste_id, error=str(e))
        raise


async def _upsert_paste(
    session: AsyncSession,
    paste_id: str,
    fields: dict[str, Any],
    *,
    node_id: str,
) -> None:
    now = utcnow()
    content_hash = sha256_hex(fields["content_md"])

    existing = await session.get(Paste, paste_id)
    if existing is None:
        p = Paste(
            paste_id=paste_id,
            author_uid=fields.get("author_uid"),
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(p)
        await session.flush()
        v = PasteVersion(
            paste_id=paste_id,
            content_md=fields["content_md"],
            content_hash=content_hash,
            crawled_at=now,
            crawler_node_id=node_id,
        )
        session.add(v)
        await session.flush()
        p.current_version_id = v.id
        return

    q = select(PasteVersion).where(
        PasteVersion.paste_id == paste_id,
        PasteVersion.content_hash == content_hash,
    )
    if (await session.execute(q)).scalar_one_or_none() is not None:
        existing.last_crawled_at = now
        return

    v = PasteVersion(
        paste_id=paste_id,
        content_md=fields["content_md"],
        content_hash=content_hash,
        crawled_at=now,
        crawler_node_id=node_id,
    )
    session.add(v)
    await session.flush()
    existing.author_uid = fields.get("author_uid") or existing.author_uid
    existing.current_version_id = v.id
    existing.last_crawled_at = now
