"""在展示层递归补全犇犇回复中被截断的正文与链接。

洛谷回复会复制被回复犇犇的可见文字，但可能丢失 Markdown 链接或截断尾部。
本模块只生成展示内容，不修改数据库中的原始归档。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.luogu_content import Feed
from app.models.luogu_user import LuoguUser, UserNameVersion


@dataclass(frozen=True)
class FeedDisplay:
    """一条犇犇最终用于展示的正文和补全来源。"""

    content_md: str
    merged_suffix_md: str | None = None
    merged_from_id: int | None = None
    merged_link_md: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyReference:
    """回复末尾的对象标记和被引用正文。"""

    name: str | None
    uid: int | None
    quoted_prefix: str
    quoted_start: int
    quoted_end: int


@dataclass(frozen=True)
class MarkdownLink:
    """Markdown 链接及其在可见文字中的范围。"""

    plain_start: int
    plain_end: int
    raw: str


_REPLY_PATTERN = re.compile(
    r"(?<!\S)\|\|\s*@?"
    r"(?:\[([^\]]{1,128})\]\(/user/(\d+)\)|([^\s:]{1,128}))"
    r"\s*:\s*([\s\S]+)$"
)
_MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!\!)\[([^\]\n]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)"
)
_MAX_COMPLETION_DEPTH = 24


def _normalize_content(value: str | None) -> str:
    """统一换行符，避免不同平台的换行导致匹配失败。"""

    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def parse_reply_reference(content_md: str) -> ReplyReference | None:
    """只解析带明确回复对象的 ``|| 用户名: 正文`` 结构。"""

    normalized = _normalize_content(content_md)
    match = _REPLY_PATTERN.search(normalized)
    if match is None:
        return None

    markdown_name, markdown_uid, plain_name, quoted = match.groups()
    name = markdown_name or plain_name or ""
    quoted_prefix = _normalize_content(quoted).strip()
    if not name or not quoted_prefix:
        return None
    return ReplyReference(
        name=name,
        uid=int(markdown_uid) if markdown_uid else None,
        quoted_prefix=quoted_prefix,
        quoted_start=match.start(4),
        quoted_end=match.end(4),
    )


def _plain_text_and_links(content_md: str) -> tuple[str, list[MarkdownLink]]:
    """移除链接语法但保留链接标题，并记录标题在可见文字中的位置。"""

    parts: list[str] = []
    links: list[MarkdownLink] = []
    cursor = 0
    plain_length = 0
    for match in _MARKDOWN_LINK_PATTERN.finditer(content_md):
        normal = content_md[cursor:match.start()]
        parts.append(normal)
        plain_length += len(normal)

        label = match.group(1)
        parts.append(label)
        links.append(MarkdownLink(plain_length, plain_length + len(label), match.group(0)))
        plain_length += len(label)
        cursor = match.end()

    parts.append(content_md[cursor:])
    return "".join(parts), links


def _plain_boundaries(content_md: str) -> list[int]:
    """把每个可见文字边界映射回完整 Markdown 的字符边界。"""

    boundaries = [0]
    cursor = 0
    for match in _MARKDOWN_LINK_PATTERN.finditer(content_md):
        for raw_index in range(cursor, match.start()):
            boundaries.append(raw_index + 1)

        # 标题中间的边界落在 ``[标题]`` 内，标题末尾必须跨过完整链接语法。
        label_length = len(match.group(1))
        for label_index in range(1, label_length + 1):
            boundaries.append(match.start() + 1 + label_index)
        boundaries[-1] = match.end()
        cursor = match.end()

    for raw_index in range(cursor, len(content_md)):
        boundaries.append(raw_index + 1)
    return boundaries


def _timestamp(value: datetime) -> float:
    """把数据库时间统一为可比较的 UTC 时间戳。"""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _is_earlier(source: Feed, reply: Feed) -> bool:
    """补全来源只能是回复发布前已经存在的犇犇。"""

    source_key = (_timestamp(source.time), int(source.id))
    reply_key = (_timestamp(reply.time), int(reply.id))
    return source_key < reply_key


def _merge_source_display(
    reply: Feed,
    source: Feed,
    source_display: FeedDisplay,
    reference: ReplyReference,
) -> FeedDisplay | None:
    """把已递归补全的来源正文嵌入当前回复，并保留真实 Markdown 链接。"""

    reply_content = _normalize_content(reply.content_md)
    source_content = _normalize_content(source_display.content_md)
    quote_content = reply_content[reference.quoted_start:reference.quoted_end]
    source_plain, source_links = _plain_text_and_links(source_content)
    quote_plain, quote_links = _plain_text_and_links(quote_content)
    if not source_plain.startswith(quote_plain):
        return None

    existing_ranges = {(link.plain_start, link.plain_end) for link in quote_links}
    quote_boundaries = _plain_boundaries(quote_content)
    insertions: list[tuple[int, int, str]] = []
    for link in source_links:
        if link.plain_end > len(quote_plain):
            continue
        if (link.plain_start, link.plain_end) in existing_ranges:
            continue
        insertions.append(
            (
                quote_boundaries[link.plain_start],
                quote_boundaries[link.plain_end],
                link.raw,
            )
        )

    merged_quote = quote_content
    for raw_start, raw_end, raw_link in sorted(insertions, reverse=True):
        merged_quote = merged_quote[:raw_start] + raw_link + merged_quote[raw_end:]

    source_boundaries = _plain_boundaries(source_content)
    suffix = source_content[source_boundaries[len(quote_plain)]:]
    if not insertions and not suffix:
        return None

    return FeedDisplay(
        content_md=(
            reply_content[:reference.quoted_start]
            + merged_quote
            + reply_content[reference.quoted_end:]
            + suffix
        ),
        merged_suffix_md=suffix or None,
        merged_from_id=int(source.id),
        merged_link_md=tuple(raw_link for _, _, raw_link in insertions),
    )


async def merge_feed_rows(
    db: AsyncSession,
    rows: Sequence[Feed],
) -> dict[int, FeedDisplay]:
    """递归补全一批犇犇；每层都可以复用上一层刚补出的完整正文。"""

    if not rows:
        return {}

    display_cache: dict[int, FeedDisplay] = {}
    resolving: set[int] = set()
    name_uid_cache: dict[str, set[int]] = {}
    history_cache: dict[int, list[Feed]] = {}
    exact_cache: dict[tuple[int, str, int], list[Feed]] = {}

    async def resolve_uids(reference: ReplyReference) -> set[int]:
        if reference.uid is not None:
            return {reference.uid}
        name = reference.name or ""
        if name in name_uid_cache:
            return name_uid_cache[name]

        uids: set[int] = set()
        users = (
            await db.execute(select(LuoguUser).where(LuoguUser.name == name))
        ).scalars().all()
        uids.update(int(user.uid) for user in users)
        versions = (
            await db.execute(select(UserNameVersion).where(UserNameVersion.name == name))
        ).scalars().all()
        uids.update(int(version.uid) for version in versions)
        name_uid_cache[name] = uids
        return uids

    async def load_history(uid: int) -> list[Feed]:
        if uid not in history_cache:
            loaded = (
                await db.execute(
                    select(Feed)
                    .where(Feed.author_uid == uid)
                    .order_by(Feed.time.desc(), Feed.id.desc())
                )
            ).scalars().all()
            history_cache[uid] = list(loaded)
        return history_cache[uid]

    async def load_exact(uid: int, reference: ReplyReference, reply: Feed) -> list[Feed]:
        """先让数据库按原始前缀筛选，绝大多数普通补尾无需扫描用户历史。"""

        cache_key = (uid, reference.quoted_prefix, int(reply.id))
        if cache_key not in exact_cache:
            loaded = (
                await db.execute(
                    select(Feed)
                    .where(
                        Feed.author_uid == uid,
                        Feed.content_md.startswith(reference.quoted_prefix),
                        or_(
                            Feed.time < reply.time,
                            and_(Feed.time == reply.time, Feed.id < reply.id),
                        ),
                    )
                    .order_by(Feed.time.desc(), Feed.id.desc())
                )
            ).scalars().all()
            exact_cache[cache_key] = list(loaded)
        return exact_cache[cache_key]

    async def resolve(row: Feed, depth: int = 0) -> FeedDisplay:
        row_id = int(row.id)
        if row_id in display_cache:
            return display_cache[row_id]

        original = FeedDisplay(content_md=_normalize_content(row.content_md))
        if depth >= _MAX_COMPLETION_DEPTH or row_id in resolving:
            return original

        reference = parse_reply_reference(row.content_md)
        if reference is None:
            display_cache[row_id] = original
            return original

        uids = await resolve_uids(reference)
        if not uids:
            display_cache[row_id] = original
            return original

        resolving.add(row_id)
        try:
            exact_candidates: list[Feed] = []
            for uid in uids:
                exact_candidates.extend(await load_exact(uid, reference, row))

            async def try_candidates(candidates: list[Feed]) -> FeedDisplay | None:
                """按发布时间从近到远尝试，命中后立即停止继续追链。"""

                candidates = [
                    source
                    for source in candidates
                    if int(source.id) != row_id and _is_earlier(source, row)
                ]
                candidates.sort(
                    key=lambda source: (_timestamp(source.time), int(source.id)),
                    reverse=True,
                )
                quote_plain, _ = _plain_text_and_links(reference.quoted_prefix)
                seen: set[int] = set()
                for source in candidates:
                    source_id = int(source.id)
                    if source_id in seen:
                        continue
                    seen.add(source_id)
                    # 递归只会补长正文；两边至少一边是另一边的前缀才可能最终匹配。
                    raw_plain, _ = _plain_text_and_links(_normalize_content(source.content_md))
                    if not (
                        raw_plain.startswith(quote_plain)
                        or quote_plain.startswith(raw_plain)
                    ):
                        continue
                    source_display = await resolve(source, depth + 1)
                    merged = _merge_source_display(row, source, source_display, reference)
                    if merged is not None:
                        return merged
                return None

            merged = await try_candidates(exact_candidates)
            if merged is not None:
                display_cache[row_id] = merged
                return merged

            # 链接语法已经丢失时无法用原始 Markdown 前缀筛选，才回退到用户历史。
            history_candidates: list[Feed] = []
            for uid in uids:
                history_candidates.extend(await load_history(uid))
            history_candidates = [
                source
                for source in history_candidates
                if int(source.id) != row_id and _is_earlier(source, row)
            ]
            merged = await try_candidates(history_candidates)
            if merged is not None:
                display_cache[row_id] = merged
                return merged
        finally:
            resolving.discard(row_id)

        display_cache[row_id] = original
        return original

    for row in rows:
        await resolve(row)
    return {int(row.id): display_cache[int(row.id)] for row in rows}
