"""剪贴板爬虫。结构与文章基本一致，字段更少。"""
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
from app.models.luogu_content import Paste, PasteVersion

log = get_logger(__name__)


async def crawl_one(paste_id: str, *, trigger: str = "manual") -> None:
    async with task_lock("paste", paste_id) as got:
        if not got:
            log.info("crawl_paste.skip_locked", paste_id=paste_id)
            return
        await _crawl_inner(paste_id, trigger=trigger)


def _extract_paste_fields(data: dict) -> dict[str, Any]:
    """防御式提取 data.paste / data.post / data 本身。"""
    for candidate in (data.get("paste"), data.get("post"), data):
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
    raise CrawlerError(f"无法从 data 中提取剪贴板字段，可见 keys: {list(data.keys())}")


async def _crawl_inner(paste_id: str, *, trigger: str) -> None:
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    url_path = f"/paste/{paste_id}"
    task_id = await record_task_start(
        "paste", url_path, trigger=trigger_from(trigger), node_id=node.node_id
    )
    start = _t.monotonic()
    try:
        result = await fetch_anon(url_path, node=node, redis=redis)
        if result.data is None:
            raise CrawlerError("剪贴板页无 lentille-context")
        data = data_from_lentille(result.data)
        fields = _extract_paste_fields(data)

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
